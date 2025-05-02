# services/v1/video/create_final_video.py

import os
import shutil
import subprocess
import requests
import logging

from config import (
    LOCAL_STORAGE_PATH, S3_ENDPOINT_URL, S3_ACCESS_KEY, 
    S3_SECRET_KEY, S3_BUCKET_NAME, S3_REGION
)
from services.s3_toolkit import upload_to_s3  # Import S3 toolkit

logger = logging.getLogger(__name__)


def _send_webhook(url: str, payload: dict):
    """Envia o resultado para a webhook URL."""
    try:
        logger.info(f"Sending webhook to {url} with payload: {payload}")
        response = requests.post(url, json=payload, timeout=10)
        # Raise HTTPError for bad responses (4xx or 5xx)
        response.raise_for_status()
        logger.info(
            f"Webhook sent successfully to {url}, "
            f"status code: {response.status_code}"
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send webhook to {url}: {e}")
    except Exception as e:
        logger.error(
            f"Unexpected error sending webhook to {url}: {e}", 
            exc_info=True
        )


class VideoCreationError(Exception):
    """Erro genérico na criação do vídeo final."""
    pass


def create_final_video(content_id: str,
                       title: str,
                       scenes: list[dict],
                       webhook_url: str):
    """
    Monta o vídeo, faz upload para S3, e envia a URL S3 para a webhook.
    """
    work_dir = None  # Initialize work_dir
    final_video_path = None
    s3_url = None  # Initialize s3_url
    status = "failed"
    error_message = None

    try:
        # 1. Cria pasta de trabalho limpa
        work_dir = os.path.join(LOCAL_STORAGE_PATH, f"video_{content_id}")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir, exist_ok=True)

        segment_paths = []
        # 2. Processa cada cena (em ordem)
        for scene in sorted(scenes, key=lambda s: s['order']):
            try:
                seg = _create_scene_segment(scene, work_dir)
                segment_paths.append(seg)
            except Exception as exc:
                # Capture scene-specific error
                raise VideoCreationError(
                    f"Scene {scene['order']} error: {exc}"
                )

        # 3. Concatena segmentos
        final_video_path = os.path.join(work_dir, f"{content_id}_final.mp4")
        _concat_segments(segment_paths, final_video_path)
        logger.info(f"Video concatenado localmente: {final_video_path}")

        # 4. Upload para S3
        logger.info(f"Iniciando upload para S3: {S3_BUCKET_NAME}")
        # Use just filename as key for now. Consider adding a path prefix.
        # s3_key_base = os.path.basename(final_video_path) 
        s3_url = upload_to_s3(
            file_path=final_video_path,
            s3_url=S3_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket_name=S3_BUCKET_NAME,
            region=S3_REGION
            # Consider passing a specific s3_key like 
            # f"videos/{content_id}/{os.path.basename(final_video_path)}"
        )
        logger.info(f"Upload para S3 concluído: {s3_url}")

        # 5. TODO: Apply overlays, captions, background music etc.
        #     to final_video_path before declaring completed status.

        status = "completed"

    except VideoCreationError as e:
        logger.error(f"VideoCreationError for {content_id}: {e}")
        error_message = str(e)
        status = "failed"

    except Exception as e:
        logger.error(
            f"Unexpected error creating/uploading video for {content_id}: {e}", 
            exc_info=True
        )
        # Assign generic error message for unexpected errors
        error_message = (
            f"Unexpected internal error during video creation/upload "
            f"for {content_id}."
        )
        status = "failed"

    finally:
        # --- Send webhook --- 
        webhook_payload = {
            "content_id": content_id,
            "status": status
        }
        if status == "completed" and s3_url:
            # Send s3_url instead of local path
            webhook_payload["s3_url"] = s3_url  
        elif error_message:
            webhook_payload["error"] = error_message
        
        _send_webhook(webhook_url, webhook_payload)
        # --- --- --- --- ---

        # --- Clean up local files --- 
        if work_dir and os.path.exists(work_dir):
            try:
                logger.info(f"Cleaning up local work directory: {work_dir}")
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.error(f"Failed to clean up work directory {work_dir}: {e}")
        # --- --- --- --- --- --- ---

    # This function now doesn't return anything directly


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

    # -- download image
    _download_stream(img_url, img_path)
    # -- download audio
    _download_stream(aud_url, aud_path)

    # -- obtém duração real do áudio
    duration = _get_audio_duration(aud_path)
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

        cmd = [
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
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', img_path,
            '-c:v', 'libx264',
            '-t', str(duration),
            '-r', str(fps),
            '-pix_fmt', 'yuv420p',
            raw_vid
        ]

    _run_ffmpeg(cmd, f"Failed to render video for scene {order}")

    # -- insere áudio
    mux_cmd = [
        'ffmpeg', '-y',
        '-i', raw_vid, '-i', aud_path,
        '-c:v', 'copy',
        '-c:a', 'copy',
        '-shortest',
        final_seg
    ]
    _run_ffmpeg(mux_cmd, f"Failed to mux audio for scene {order}")

    return final_seg


def _concat_segments(segment_paths: list[str], output_path: str):
    """
    Concatena todos os MP4s (com áudio) numa sequência única.
    """
    list_file = os.path.join(os.path.dirname(output_path), 'concat_list.txt')
    with open(list_file, 'w') as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', list_file,
        '-c', 'copy',
        output_path
    ]
    _run_ffmpeg(cmd, "Failed to concatenate final video")


def _get_audio_duration(path: str) -> float:
    """
    Chama ffprobe para extrair a duração exata (em segundos) do
    arquivo de áudio.
    """
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise VideoCreationError(
            f"ffprobe failed on {path}: {proc.stderr.strip()}"
        )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise VideoCreationError(f"Invalid duration for {path}")


def _download_stream(url: str, dest: str):
    """
    Baixa de forma streaming da URL para o arquivo `dest`.
    """
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)


def _run_ffmpeg(cmd: list[str], err_msg: str):
    """
    Executa um comando ffmpeg e verifica saída.
    """
    logger.debug("Running ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        stderr_lines = proc.stderr.splitlines()
        last_line = stderr_lines[-1] if stderr_lines else "(no stderr output)"
        logger.error("ffmpeg error: %s", proc.stderr)
        raise VideoCreationError(f"{err_msg}: {last_line}")