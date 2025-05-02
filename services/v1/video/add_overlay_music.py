# services/v1/video/add_overlay_music.py

import os
import shutil
import logging
import subprocess
from typing import Optional  # Ensure Optional is imported

from config import (
    LOCAL_STORAGE_PATH, S3_ENDPOINT_URL, S3_ACCESS_KEY,
    S3_SECRET_KEY, S3_BUCKET_NAME, S3_REGION
)
from services.s3_toolkit import upload_to_s3
from services.v1.video.create_final_video import (
    _download_stream, _run_ffmpeg, _send_webhook, VideoCreationError,
    _get_media_duration
)

logger = logging.getLogger(__name__)


def _get_video_dimensions(path: str) -> tuple[int, int]:
    """Gets video width and height using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',  # Select first video stream
        '-show_entries', 'stream=width,height',
        '-of', 'csv=s=x:p=0',  # Output format widthxheight
        path
    ]
    logger.debug(f"Getting dimensions for {path}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        logger.error(
            f"ffprobe dimension check failed for {path}. Code: {proc.returncode}"
        )
        logger.error(f"ffprobe stderr: {stderr}")
        raise OverlayMusicError(
            f"ffprobe failed to get dimensions for {path}: {stderr}"
        )
    try:
        dimensions_str = proc.stdout.strip()
        width, height = map(int, dimensions_str.split('x'))
        logger.debug(f"Dimensions for {path}: {width}x{height}")
        if width <= 0 or height <= 0:
            raise ValueError("Invalid dimensions")
        return width, height
    except Exception as e:
        logger.error(
            f"Could not parse dimensions '{dimensions_str}' for {path}: {e}"
        )
        raise OverlayMusicError(
            f"Invalid dimensions '{dimensions_str}' for {path}"
        )


class OverlayMusicError(Exception):
    """Custom error for overlay/music addition failures."""
    pass


# Mapping for overlay positions to ffmpeg filter values (excluding 'full')
OVERLAY_POSITION_COORDS = {
    "top-left": "10:10",
    "top-right": "W-w-10:10",
    "bottom-left": "10:H-h-10",
    "bottom-right": "W-w-10:H-h-10",
    "center": "(W-w)/2:(H-h)/2",
}

# Supported blend modes (add more if needed)
SUPPORTED_BLEND_MODES = ["normal", "screen", "multiply", "overlay", "difference"]

def add_overlay_and_music(
    content_id: str,  # Used for naming temp dirs/files
    input_video_url: str,
    overlay_image_url: str,
    background_music_url: str,
    webhook_url: str,
    overlay_position: str = "bottom-right", # Now includes "full"
    music_volume: float = 0.5,  # Default to 50% volume
    output_filename: Optional[str] = None, # Use Optional[str]
    overlay_opacity: float = 1.0, # Opacity (0.0 to 1.0)
    overlay_blend_mode: Optional[str] = None # e.g., "screen"
):
    """
    Downloads assets, applies looping overlay (img/vid) & looping music.
    Supports full scaling, opacity, and blend modes for overlay.
    Uploads the result to S3 and sends a webhook notification.
    """
    work_dir = None
    s3_url = None
    status = "failed"
    error_message = None
    final_video_path = None

    try:
        # --- 1. Setup ---
        logger.info(f"[{content_id}] Starting overlay/music process.")
        work_dir = os.path.join(LOCAL_STORAGE_PATH, f"overlay_{content_id}")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir, exist_ok=True)

        # Define local file paths (use generic extensions)
        base_name = os.path.splitext(
            os.path.basename(input_video_url).split('?')[0]
        )[0]
        input_video_path = os.path.join(work_dir, f"{base_name}_input.mp4")
        overlay_media_path = os.path.join(work_dir, "overlay.media")  # Generic
        music_media_path = os.path.join(work_dir, "music.media")  # Generic

        if output_filename:
            output_base = os.path.splitext(output_filename)[0]
            final_video_path = os.path.join(work_dir, f"{output_base}.mp4")
        else:
            final_video_path = os.path.join(
                work_dir, f"{base_name}_overlay_music.mp4"
            )

        logger.info(f"[{content_id}] Work directory: {work_dir}")

        # --- 2. Download Files ---
        logger.info(
            f"[{content_id}] Downloading input video: {input_video_url}"
        )
        _download_stream(input_video_url, input_video_path)

        logger.info(
            f"[{content_id}] Downloading overlay media: {overlay_image_url}"
        )
        _download_stream(overlay_image_url, overlay_media_path)

        logger.info(
            f"[{content_id}] Downloading background music: "
            f"{background_music_url}"
        )
        _download_stream(background_music_url, music_media_path)
        logger.info(f"[{content_id}] Downloads complete.")

        # --- 3. Get Main Video Duration & Dimensions --- 
        main_duration = 0
        main_width = 0
        main_height = 0
        try:
            main_duration = _get_media_duration(input_video_path)
            main_width, main_height = _get_video_dimensions(input_video_path)
            logger.info(
                f"[{content_id}] Input video: {main_width}x{main_height}, {main_duration}s"
            )
        except Exception as e:
             raise OverlayMusicError(
                 f"Could not get dimensions/duration of input video {input_video_path}: {e}"
             )

        # --- 4. Build Filter Complex --- 
        video_filters = []
        overlay_input_stream = "[1:v]" # Initial overlay stream
        
        # 4a. Overlay Scaling (if 'full')
        if overlay_position == "full":
            logger.info(f"[{content_id}] Scaling overlay to full size: {main_width}x{main_height}")
            video_filters.append(f"{overlay_input_stream}scale={main_width}:{main_height}[scaled_overlay]")
            overlay_input_stream = "[scaled_overlay]" # Next filter uses scaled output

        # 4b. Overlay Opacity (if not 1.0)
        if 0.0 <= overlay_opacity < 1.0:
            logger.info(f"[{content_id}] Applying overlay opacity: {overlay_opacity}")
            # Use colorchannelmixer to adjust alpha (aa)
            video_filters.append(f"{overlay_input_stream}colorchannelmixer=aa={overlay_opacity}[transparent_overlay]")
            overlay_input_stream = "[transparent_overlay]" # Next filter uses transparent output
        elif overlay_opacity < 0.0 or overlay_opacity > 1.0:
             logger.warning(f"[{content_id}] Invalid overlay_opacity ({overlay_opacity}), ignoring.")

        # 4c. Overlay Blending
        overlay_filter_params = "shortest=1"
        if overlay_position == "full":
            overlay_filter_coords = "0:0" # Position doesn't matter when scaled
        else:
            overlay_filter_coords = OVERLAY_POSITION_COORDS.get(overlay_position, OVERLAY_POSITION_COORDS["bottom-right"])
            
        if overlay_blend_mode and overlay_blend_mode in SUPPORTED_BLEND_MODES:
             logger.info(f"[{content_id}] Applying overlay blend mode: {overlay_blend_mode}")
             overlay_filter_params += f":blend_mode={overlay_blend_mode}"
        elif overlay_blend_mode:
             logger.warning(f"[{content_id}] Unsupported blend mode '{overlay_blend_mode}', using default.")

        # Apply the overlay filter itself
        video_filters.append(f"[0:v]{overlay_input_stream}overlay={overlay_filter_coords}:{overlay_filter_params}[vout]")
        
        # 4d. Audio Filters (Volume and Mix)
        audio_filters = [
            f"[2:a]volume={music_volume}[a_music]", # Adjust music volume
            f"[0:a][a_music]amix=inputs=2:duration=first[aout]" # Mix
        ]
        
        # Combine all filters
        filter_complex = ";".join(video_filters + audio_filters)
        logger.debug(f"[{content_id}] Generated filter_complex: {filter_complex}")
        
        # --- 5. FFmpeg Command --- 
        cmd = [
            'ffmpeg', '-y',
            '-i', input_video_path,  # Input 0: Main Video (no loop)
            '-stream_loop', '-1', '-i', overlay_media_path,  # Input 1: Overlay (looped)
            '-stream_loop', '-1', '-i', music_media_path,  # Input 2: Music (looped)
            '-filter_complex', filter_complex,
            '-map', '[vout]',        # Map video output
            '-map', '[aout]',        # Map audio output
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-t', str(main_duration),  # Set output duration explicitly
            final_video_path
        ]

        # --- 6. Execute FFmpeg --- 
        logger.info(f"[{content_id}] Running ffmpeg command...")
        _run_ffmpeg(cmd, f"[{content_id}] Failed to apply overlay/music")

        if not os.path.exists(final_video_path):
            raise OverlayMusicError(
                f"[{content_id}] Output video file not found after ffmpeg: "
                f"{final_video_path}"
            )
        logger.info(
            f"[{content_id}] FFmpeg processing complete: {final_video_path}"
        )

        # --- 7. Upload to S3 ---
        logger.info(
            f"[{content_id}] Uploading final video to S3 bucket: "
            f"{S3_BUCKET_NAME}"
        )
        s3_url = upload_to_s3(
            file_path=final_video_path,
            s3_url=S3_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket_name=S3_BUCKET_NAME,
            region=S3_REGION
        )
        logger.info(f"[{content_id}] Upload complete. S3 URL: {s3_url}")
        status = "completed"

    except (OverlayMusicError, VideoCreationError) as e:  # Catch specific errors
        logger.error(f"[{content_id}] Error processing overlay/music: {e}")
        error_message = str(e)
        status = "failed"
    except Exception as e:
        logger.error(f"[{content_id}] Unexpected error: {e}", exc_info=True)
        error_message = (
            f"Unexpected internal error during overlay/music processing "
            f"for {content_id}."
        )
        status = "failed"

    finally:
        # --- 8. Send Webhook ---
        webhook_payload = {
            "content_id": content_id,  # Include original content_id
            "status": status
        }
        if status == "completed" and s3_url:
            webhook_payload["s3_url"] = s3_url
        elif error_message:
            webhook_payload["error"] = error_message

        logger.info(f"[{content_id}] Sending final webhook to: {webhook_url}")
        _send_webhook(webhook_url, webhook_payload)

        # --- 9. Cleanup ---
        if work_dir and os.path.exists(work_dir):
            try:
                logger.info(
                    f"[{content_id}] Cleaning up work directory: {work_dir}"
                )
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.error(
                    f"[{content_id}] Failed to clean up {work_dir}: {e}"
                ) 