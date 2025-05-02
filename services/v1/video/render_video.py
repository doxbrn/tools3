# services/v1/video/render_video.py

import os
import shutil
import logging
from typing import Optional, List, Dict, Any

from config import (
    LOCAL_STORAGE_PATH, S3_ENDPOINT_URL, S3_ACCESS_KEY,
    S3_SECRET_KEY, S3_BUCKET_NAME, S3_REGION
)
from services.s3_toolkit import upload_to_s3
from .video_utils import (
    _download_stream, _run_ffmpeg, _send_webhook,
    _get_media_duration, _get_video_dimensions,
    FFmpegExecutionError, FFprobeError, VideoCreationError
)

logger = logging.getLogger(__name__)

# Constants for filter complex generation
OVERLAY_POSITION_COORDS = {
    "top-left": "10:10", "top-right": "W-w-10:10",
    "bottom-left": "10:H-h-10", "bottom-right": "W-w-10:H-h-10",
    "center": "(W-w)/2:(H-h)/2",
}
SUPPORTED_BLEND_MODES = ["normal", "screen", "multiply", "overlay", "difference"]

class RenderVideoError(Exception):
    """Custom error for the unified rendering process."""
    pass

# --- Main Rendering Function --- #

def render_video(payload: Dict[str, Any]):
    """ 
    Orchestrates the full video rendering pipeline based on payload.
    Payload expected keys: content_id, scenes, webhook_url, 
                          overlay_options?, music_options?, caption_options?, output_options?
    """
    content_id = payload.get('content_id', 'no_id')
    webhook_url = payload.get('webhook_url')
    if not webhook_url:
        logger.error(f"[{content_id}] Webhook URL missing in payload.")
        # Cannot report status without webhook, maybe raise an error?
        return 

    # --- Initialize state --- 
    work_dir = None
    final_s3_url = None
    status = "failed"
    error_message = None
    rendered_video_path = None # Path after all steps

    log_prefix = f"[{content_id}]" # For logging

    try:
        logger.info(f"{log_prefix} Starting unified render process.")
        
        # --- 1. Setup Workspace --- 
        work_dir = os.path.join(LOCAL_STORAGE_PATH, f"render_{content_id}")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        logger.info(f"{log_prefix} Created work dir: {work_dir}")

        # --- 2. Prepare Scene Segments --- 
        scenes = payload.get('scenes', [])
        if not scenes:
             raise RenderVideoError("No scenes provided in payload.")
             
        segment_paths = _process_scenes(content_id, scenes, work_dir)
        if not segment_paths:
             raise RenderVideoError("Scene processing failed to produce segments.")
        
        # --- 3. Concatenate Scenes (Simple Concat for now) --- 
        concatenated_video_path = os.path.join(work_dir, "concatenated.mp4")
        _simple_concat_segments(segment_paths, concatenated_video_path)
        rendered_video_path = concatenated_video_path # Start with concat output

        # --- 4. Apply Captions (ASS only for now) --- 
        caption_options = payload.get('caption_options')
        if caption_options:
            rendered_video_path = _apply_captions(content_id, rendered_video_path, caption_options, work_dir)

        # --- 5. Apply Overlay and Music --- 
        overlay_options = payload.get('overlay_options')
        music_options = payload.get('music_options')
        if overlay_options or music_options:
            rendered_video_path = _apply_overlay_music(
                content_id, rendered_video_path, overlay_options, music_options, work_dir
            )

        # --- 6. Final Output Naming --- 
        output_options = payload.get('output_options', {})
        output_filename = output_options.get('filename', f"{content_id}_rendered.mp4")
        # Ensure .mp4 extension
        output_filename = os.path.splitext(output_filename)[0] + ".mp4"
        final_local_path = os.path.join(work_dir, output_filename)
        
        # If the last step already produced the final name, skip rename
        if rendered_video_path != final_local_path:
             logger.info(f"{log_prefix} Renaming final output to {output_filename}")
             shutil.move(rendered_video_path, final_local_path)
        else:
             logger.info(f"{log_prefix} Final output already named {output_filename}")
        
        # --- 7. Upload to S3 --- 
        logger.info(f"{log_prefix} Uploading {final_local_path} to S3...")
        final_s3_url = upload_to_s3(
            file_path=final_local_path,
            s3_url=S3_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket_name=S3_BUCKET_NAME,
            region=S3_REGION
            # Consider adding path prefix: key=f"renders/{content_id}/{output_filename}"
        )
        logger.info(f"{log_prefix} Upload complete: {final_s3_url}")
        status = "completed"

    except (RenderVideoError, VideoCreationError, FFprobeError, FFmpegExecutionError, IOError, KeyError) as e:
        logger.error(f"{log_prefix} Render failed: {e}", exc_info=False)
        error_message = f"Render failed: {e}"
        status = "failed"
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected render error: {e}", exc_info=True)
        error_message = "Unexpected internal error during video render."
        status = "failed"

    finally:
        # --- Send Webhook --- 
        webhook_payload = {"content_id": content_id, "status": status}
        if status == "completed" and final_s3_url:
            webhook_payload["s3_url"] = final_s3_url
        elif error_message:
            webhook_payload["error"] = error_message
        _send_webhook(webhook_url, webhook_payload)

        # --- Cleanup --- 
        if work_dir and os.path.exists(work_dir):
            try:
                logger.info(f"{log_prefix} Cleaning up work directory: {work_dir}")
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.error(f"{log_prefix} Failed to clean up {work_dir}: {e}")

# --- Helper Sub-Functions for render_video --- #

def _process_scenes(content_id: str, scenes: List[Dict], work_dir: str) -> List[str]:
    """Processes each scene (download, render zoom/pan). Returns list of segment paths."""
    log_prefix = f"[{content_id}]"
    segment_paths = []
    for i, scene in enumerate(sorted(scenes, key=lambda s: s.get('order', i))):
        scene_order = scene.get('order', i + 1)
        scene_log_prefix = f"{log_prefix}[Scene {scene_order}]"
        try:
            logger.info(f"{scene_log_prefix} Processing...")
            img_url = scene['image_url']
            aud_url = scene['audio_url']
            # TODO: Add text overlay processing here if needed per scene
            # TODO: Add advanced zoom/pan from scene options here
            zoom_type = scene.get('zoom_type', 'None') # Basic zoom for now
            zoom_speed = scene.get('zoom_speed', 1.0)

            img_path = os.path.join(work_dir, f"scene_{scene_order}_img.jpg") # Use specific names
            aud_path = os.path.join(work_dir, f"scene_{scene_order}_aud.wav")
            raw_vid_path = os.path.join(work_dir, f"scene_{scene_order}_raw.mp4")
            final_seg_path = os.path.join(work_dir, f"scene_{scene_order}_seg.mp4")

            _download_stream(img_url, img_path)
            _download_stream(aud_url, aud_path)
            duration = _get_media_duration(aud_path)
            fps = 30
            frames = int(duration * fps)

            # -- Render video (no audio yet) --
            if zoom_type != 'None':
                max_zoom = 1.5
                delta = (max_zoom - 1.0) / max(1, frames) * zoom_speed
                expr = f"if(eq(on,1),1, min(zoom+{delta:.6f},{max_zoom}))" if zoom_type == 'Zoom In' else f"if(eq(on,1),{max_zoom}, max(zoom-{delta:.6f},1))"
                cmd_render = [
                    'ffmpeg', '-y', '-loop', '1', '-i', img_path,
                    '-filter_complex', f"zoompan=z='{expr}':d={frames}:s=1920x1080:fps={fps}",
                    '-c:v', 'libx264', '-t', str(duration), '-pix_fmt', 'yuv420p',
                    raw_vid_path
                ]
            else:
                 cmd_render = [
                    'ffmpeg', '-y', '-loop', '1', '-i', img_path, '-c:v', 'libx264',
                    '-t', str(duration), '-r', str(fps), '-pix_fmt', 'yuv420p',
                    raw_vid_path
                 ]
            _run_ffmpeg(cmd_render, f"{scene_log_prefix} Failed to render video")
            if not os.path.exists(raw_vid_path):
                 raise VideoCreationError(f"Rendered video file not found: {raw_vid_path}")

            # -- Mux audio --
            cmd_mux = [
                'ffmpeg', '-y', '-i', raw_vid_path, '-i', aud_path,
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', # Encode audio
                '-shortest', final_seg_path
            ]
            _run_ffmpeg(cmd_mux, f"{scene_log_prefix} Failed to mux audio")
            if not os.path.exists(final_seg_path):
                raise VideoCreationError(f"Muxed segment file not found: {final_seg_path}")

            segment_paths.append(final_seg_path)
            logger.info(f"{scene_log_prefix} Segment created: {final_seg_path}")

        except (IOError, FFmpegExecutionError, FFprobeError, KeyError, Exception) as exc:
            logger.error(f"{scene_log_prefix} Processing failed: {exc}", exc_info=True)
            # Decide: skip scene or fail entire job? For now, fail job.
            raise RenderVideoError(f"Failed processing scene {scene_order}: {exc}") from exc
            
    return segment_paths

def _simple_concat_segments(segment_paths: List[str], output_path: str):
    """ Concatenates segments using simple concat demuxer (-c copy). """
    list_file = os.path.join(os.path.dirname(output_path), 'concat_list.txt')
    logger.debug(f"Creating simple concat list: {list_file}")
    with open(list_file, 'w') as f:
        for p in segment_paths:
            # Use relative paths for concat demuxer
            f.write(f"file '{os.path.basename(p)}'\n")

    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_file, '-c', 'copy', output_path
    ]
    # Run inside the work_dir for relative paths to work
    work_dir = os.path.dirname(output_path)
    original_cwd = os.getcwd()
    try:
        os.chdir(work_dir)
        _run_ffmpeg(cmd, "Failed to concatenate segments")
    finally:
        os.chdir(original_cwd)
    logger.info(f"Segments concatenated to: {output_path}")

# TODO: Implement _complex_concat_segments using xfade for transitions

def _apply_captions(content_id: str, input_video_path: str, caption_options: Dict, work_dir: str) -> str:
    """Applies captions using subtitles filter. ASS only for now."""
    log_prefix = f"[{content_id}]"
    logger.info(f"{log_prefix} Applying captions...")
    source = caption_options.get('source')
    if not source or not isinstance(source, str):
        logger.warning(f"{log_prefix} No valid caption source URL provided. Skipping captions.")
        return input_video_path

    # Assume source is a URL to an ASS file for now
    ass_url = source
    ass_path = os.path.join(work_dir, "captions.ass")
    output_path = os.path.join(work_dir, "captioned.mp4")

    try:
        _download_stream(ass_url, ass_path)
        if not os.path.exists(ass_path):
             raise RenderVideoError("Downloaded ASS file not found.")
             
        # Use subtitles filter. Ensure path escaping if needed.
        # Note: This requires ffmpeg compiled with --enable-libass
        subtitle_filter = f"subtitles='{os.path.basename(ass_path)}'"

        cmd = [
            'ffmpeg', '-y',
            '-i', input_video_path,
            '-vf', subtitle_filter,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', # Re-encode needed
            '-c:a', 'copy', # Copy original audio
            output_path
        ]

        # Run inside the work_dir for relative subtitle path to work
        original_cwd = os.getcwd()
        try:
             os.chdir(work_dir)
             _run_ffmpeg(cmd, f"{log_prefix} Failed to apply captions")
        finally:
             os.chdir(original_cwd)

        if not os.path.exists(output_path):
            raise RenderVideoError("Video file after captioning not found.")
        
        logger.info(f"{log_prefix} Captions applied: {output_path}")
        return output_path # Return path to the new captioned video
        
    except (IOError, FFmpegExecutionError) as e:
        logger.error(f"{log_prefix} Failed during caption step: {e}")
        raise RenderVideoError(f"Captioning failed: {e}") from e
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error applying captions: {e}", exc_info=True)
        raise RenderVideoError("Unexpected error during captioning.") from e

def _apply_overlay_music(content_id: str, input_video_path: str, 
                           overlay_options: Optional[Dict], music_options: Optional[Dict], 
                           work_dir: str) -> str:
    """Applies looping overlay and/or looping music."""
    log_prefix = f"[{content_id}]"
    logger.info(f"{log_prefix} Applying overlay/music...")
    
    overlay_media_path = None
    music_media_path = None
    inputs = ['-i', input_video_path] # Start with main video input
    video_filters = []
    audio_filters = []
    map_video = "[0:v]" # Default map to input video
    map_audio = "[0:a]" # Default map to input audio
    current_video_input_index = 0

    # --- Download and prepare overlay input --- 
    if overlay_options:
        overlay_url = overlay_options.get('url')
        if overlay_url:
            overlay_media_path = os.path.join(work_dir, "overlay.media")
            logger.info(f"{log_prefix} Downloading overlay media: {overlay_url}")
            _download_stream(overlay_url, overlay_media_path)
            current_video_input_index += 1
            inputs.extend(['-stream_loop', '-1', '-i', overlay_media_path])
            overlay_input_stream_index = current_video_input_index
            map_video = "[vout]" # Output will come from overlay filter
        else:
             logger.warning(f"{log_prefix} Overlay options provided but no URL found.")
             overlay_options = None # Disable overlay if no URL
             
    # --- Download and prepare music input --- 
    if music_options:
        music_url = music_options.get('url')
        if music_url:
            music_media_path = os.path.join(work_dir, "music.media")
            logger.info(f"{log_prefix} Downloading music media: {music_url}")
            _download_stream(music_url, music_media_path)
            current_video_input_index += 1
            inputs.extend(['-stream_loop', '-1', '-i', music_media_path])
            music_input_stream_index = current_video_input_index
            map_audio = "[aout]" # Output will come from amix filter
        else:
             logger.warning(f"{log_prefix} Music options provided but no URL found.")
             music_options = None # Disable music if no URL

    # If neither overlay nor music is applied, return input path
    if not overlay_options and not music_options:
         logger.info(f"{log_prefix} No overlay or music to apply. Skipping.")
         return input_video_path

    # Get dimensions/duration of the *current* input video
    main_duration = _get_media_duration(input_video_path)
    main_width, main_height = _get_video_dimensions(input_video_path)

    # --- Build Overlay Filters (if applicable) --- 
    overlay_input_stream = f"[{overlay_input_stream_index}:v]" if overlay_options else None
    if overlay_options and overlay_input_stream:
        overlay_position = overlay_options.get('position', 'bottom-right')
        overlay_opacity = overlay_options.get('opacity', 1.0)
        overlay_blend_mode = overlay_options.get('blend_mode')
        current_overlay_stream_name = overlay_input_stream

        if overlay_position == "full":
            video_filters.append(f"{current_overlay_stream_name}scale={main_width}:{main_height}[scaled_overlay]")
            current_overlay_stream_name = "[scaled_overlay]"

        if 0.0 <= overlay_opacity < 1.0:
            video_filters.append(f"{current_overlay_stream_name}colorchannelmixer=aa={overlay_opacity}[transparent_overlay]")
            current_overlay_stream_name = "[transparent_overlay]"

        overlay_filter_params = "shortest=1"
        overlay_coords = "0:0" if overlay_position == "full" else OVERLAY_POSITION_COORDS.get(overlay_position, OVERLAY_POSITION_COORDS["bottom-right"])
        if overlay_blend_mode and overlay_blend_mode in SUPPORTED_BLEND_MODES:
             overlay_filter_params += f":blend_mode={overlay_blend_mode}"
        
        video_filters.append(f"[0:v]{current_overlay_stream_name}overlay={overlay_coords}:{overlay_filter_params}[vout]")

    # --- Build Audio Filters (if applicable) --- 
    if music_options:
         music_volume = music_options.get('volume', 0.5)
         audio_filters.append(f"[{music_input_stream_index}:a]volume={music_volume}[a_music]")
         audio_filters.append(f"[0:a][a_music]amix=inputs=2:duration=first[aout]")
    
    # --- Construct Final Command --- 
    filter_complex = ";".join(video_filters + audio_filters)
    output_path = os.path.join(work_dir, "overlay_music_applied.mp4")

    cmd = [ 'ffmpeg', '-y' ] + inputs + [
        '-filter_complex', filter_complex,
        '-map', map_video,
        '-map', map_audio, 
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-t', str(main_duration),
        output_path
    ]

    logger.info(f"{log_prefix} Running ffmpeg for overlay/music...")
    try:
         _run_ffmpeg(cmd, f"{log_prefix} Failed overlay/music step")
         if not os.path.exists(output_path):
              raise RenderVideoError("Video file after overlay/music not found.")
         logger.info(f"{log_prefix} Overlay/music applied: {output_path}")
         return output_path
    except (FFmpegExecutionError, IOError) as e:
         logger.error(f"{log_prefix} Failed during overlay/music step: {e}")
         raise RenderVideoError(f"Overlay/Music step failed: {e}") from e
    except Exception as e:
         logger.error(f"{log_prefix} Unexpected error applying overlay/music: {e}", exc_info=True)
         raise RenderVideoError("Unexpected error during overlay/music.") from e 