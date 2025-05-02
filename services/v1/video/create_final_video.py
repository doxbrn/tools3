# services/v1/video/create_final_video.py

import os
import shutil
# Use subprocess from video_utils if needed, or remove if not used directly here
# import subprocess 
# Removed requests import, now in video_utils
import logging

from config import (
    LOCAL_STORAGE_PATH, S3_ENDPOINT_URL, S3_ACCESS_KEY,
    S3_SECRET_KEY, S3_BUCKET_NAME, S3_REGION
)
from services.s3_toolkit import upload_to_s3  # Import S3 toolkit
# Import helpers from video_utils
from .video_utils import (
    _send_webhook, _download_stream, _run_ffmpeg, 
    _get_media_duration, FFmpegExecutionError, FFprobeError
)

logger = logging.getLogger(__name__)

# Remove _send_webhook, _download_stream, _get_media_duration, _run_ffmpeg 
# as they are now imported from video_utils

class VideoCreationError(Exception):
    """Erro genérico na criação do vídeo final."""
    pass


def create_final_video(content_id: str,
                       title: str,  # Title currently unused
                       scenes: list[dict],
                       webhook_url: str):
    """
    Monta o vídeo, faz upload para S3, e envia a URL S3 para a webhook.
    """
    work_dir = None
    final_video_path = None
    s3_url = None
    status = "failed"
    error_message = None

    try:
        # 1. Setup
        work_dir = os.path.join(LOCAL_STORAGE_PATH, f"video_{content_id}")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        logger.info(f"[{content_id}] Created work dir: {work_dir}")

        # 2. Process scenes
        segment_paths = []
        for scene in sorted(scenes, key=lambda s: s['order']):
             # Wrap scene processing in its own try-except
             scene_order = scene.get('order', 'N/A')
             try:
                logger.info(f"[{content_id}] Processing scene {scene_order}...")
                seg = _create_scene_segment(scene, work_dir)
                segment_paths.append(seg)
                logger.info(f"[{content_id}] Finished scene {scene_order}.")
             except (IOError, FFmpegExecutionError, FFprobeError, KeyError, Exception) as exc:
                 # Catch specific and general errors during scene processing
                 logger.error(f"[{content_id}] Error in scene {scene_order}: {exc}", exc_info=True)
                 raise VideoCreationError(f"Scene {scene_order} error: {exc}") from exc

        # 3. Concatenate segments
        if not segment_paths:
            raise VideoCreationError("No video segments were created.")
        
        final_video_path = os.path.join(work_dir, f"{content_id}_final.mp4")
        logger.info(f"[{content_id}] Concatenating {len(segment_paths)} segments...")
        _concat_segments(segment_paths, final_video_path)
        logger.info(f"[{content_id}] Concatenation complete: {final_video_path}")

        # 4. Upload to S3
        logger.info(f"[{content_id}] Uploading {final_video_path} to S3 bucket {S3_BUCKET_NAME}")
        s3_url = upload_to_s3(
            file_path=final_video_path,
            s3_url=S3_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket_name=S3_BUCKET_NAME,
            region=S3_REGION
        )
        logger.info(f"[{content_id}] Upload complete. S3 URL: {s3_url}")

        # 5. TODO (Now part of unified service)

        status = "completed"

    except (VideoCreationError, FFmpegExecutionError, FFprobeError, IOError) as e:
        logger.error(f"[{content_id}] VideoCreationError: {e}", exc_info=False) # Don't log full trace for expected errors
        error_message = str(e)
        status = "failed"
    except Exception as e:
        logger.error(f"[{content_id}] Unexpected error in create_final_video: {e}", exc_info=True)
        error_message = f"Unexpected internal error for {content_id}."
        status = "failed"

    finally:
        # Send webhook
        webhook_payload = {"content_id": content_id, "status": status}
        if status == "completed" and s3_url:
            webhook_payload["s3_url"] = s3_url
        elif error_message:
            webhook_payload["error"] = error_message
        _send_webhook(webhook_url, webhook_payload)

        # Clean up
        if work_dir and os.path.exists(work_dir):
            try:
                logger.info(f"[{content_id}] Cleaning up work directory: {work_dir}")
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.error(f"[{content_id}] Failed to clean up {work_dir}: {e}")

# Function remains mostly the same, but uses imported _download_stream, _run_ffmpeg, etc.
def _create_scene_segment(scene: dict, work_dir: str) -> str:
    """
    Para uma cena, faz:
    - Download de image_url e audio_url
    - Extrai duração exata do áudio
    - Gera um MP4 com zoom (se houver) e aplica o áudio
    Retorna o path do segmento pronto.
    """
    order = scene['order']
    img_url = scene['image_url']
    aud_url = scene['audio_url']
    zoom_type = scene.get('zoom_type', 'None')
    zoom_speed = scene.get('zoom_speed', 1.0)

    # paths locais
    img_path = os.path.join(work_dir, f"scene_{order}.jpg")
    aud_path = os.path.join(work_dir, f"scene_{order}.wav")
    raw_vid = os.path.join(work_dir, f"scene_{order}_raw.mp4")
    final_seg = os.path.join(work_dir, f"scene_{order}.mp4")

    logger.debug(f"[{order}] Downloading scene assets...")
    _download_stream(img_url, img_path)
    _download_stream(aud_url, aud_path)
    duration = _get_media_duration(aud_path)

    # -- obtém duração real do áudio
    fps = 30
    frames = int(duration * fps)

    # -- gera vídeo sem áudio
    if zoom_type != 'None':
        # zoom in / out
        max_zoom = 1.5
        delta = (max_zoom - 1.0) / max(1, frames) * zoom_speed
        if zoom_type == 'Zoom In':
            expr = f"if(eq(on,1),1, min(zoom+{delta:.6f},{max_zoom}))"
        else:  # Zoom Out
            expr = f"if(eq(on,1),{max_zoom}, max(zoom-{delta:.6f},1))"

        cmd_render = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', img_path,
            '-filter_complex',
            f"zoompan=z='{expr}':d={frames}:s=1920x1080",
            '-c:v', 'libx264',
            '-r', str(fps),
            '-t', str(duration),
            '-pix_fmt', 'yuv420p',
            raw_vid
        ]
    else:
        # imagem fixa
        cmd_render = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', img_path,
            '-c:v', 'libx264',
            '-t', str(duration),
            '-r', str(fps),
            '-pix_fmt', 'yuv420p',
            raw_vid
        ]

    logger.debug(f"[{order}] Rendering raw video segment...")
    _run_ffmpeg(cmd_render, f"Failed to render video for scene {order}")

    # --- Check if raw video file was created --- 
    if not os.path.exists(raw_vid):
        logger.error(f"Raw video file was not created: {raw_vid}")
        raise VideoCreationError(
            f"ffmpeg command completed for scene {order} "
            f"but failed to create {raw_vid}"
        )
    logger.info(f"[{order}] Raw video created successfully: {raw_vid}")
    # -------------------------------------------

    # -- insere áudio
    mux_cmd = [
        'ffmpeg', '-y',
        '-i', raw_vid, '-i', aud_path,
        '-c:v', 'copy',
        '-c:a', 'copy',
        '-shortest',
        final_seg
    ]
    logger.debug(f"[{order}] Muxing audio...")
    _run_ffmpeg(mux_cmd, f"Failed to mux audio for scene {order}")

    logger.info(f"[{order}] Scene segment created: {final_seg}")
    return final_seg

# Function remains mostly the same, uses imported _run_ffmpeg
def _concat_segments(segment_paths: list[str], output_path: str):
    """
    Concatena todos os MP4s (com áudio) numa sequência única.
    """
    list_file = os.path.join(os.path.dirname(output_path), 'concat_list.txt')
    logger.debug(f"Creating concat list: {list_file}")
    with open(list_file, 'w') as f:
        for p in segment_paths:
            f.write(f"file '{os.path.basename(p)}'\n") # Use relative paths within work dir

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', list_file,
        '-c', 'copy',
        output_path
    ]
     # Run inside the work_dir for relative paths in concat_list.txt to work
    work_dir = os.path.dirname(output_path)
    original_cwd = os.getcwd()
    try:
        os.chdir(work_dir)
        _run_ffmpeg(cmd, "Failed to concatenate final video")
    finally:
        os.chdir(original_cwd) # Change back CWD