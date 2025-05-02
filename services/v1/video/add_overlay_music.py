# services/v1/video/add_overlay_music.py

import os
import shutil
import logging
from typing import Optional  # Import Optional

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


class OverlayMusicError(Exception):
    """Custom error for overlay/music addition failures."""
    pass


# Mapping for overlay positions to ffmpeg filter values
OVERLAY_POSITIONS = {
    "top-left": "10:10",
    "top-right": "W-w-10:10",
    "bottom-left": "10:H-h-10",
    "bottom-right": "W-w-10:H-h-10",
    "center": "(W-w)/2:(H-h)/2",
}


def add_overlay_and_music(
    content_id: str,  # Used for naming temp dirs/files
    input_video_url: str,
    overlay_image_url: str,
    background_music_url: str,
    webhook_url: str,
    overlay_position: str = "bottom-right",
    music_volume: float = 0.5,  # Default to 50% volume
    output_filename: Optional[str] = None  # Use Optional[str]
):
    """
    Downloads assets, applies looping overlay (img/vid) & looping music.
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
        # Basic name from URL, remove query string
        base_name = os.path.splitext(
            os.path.basename(input_video_url).split('?')[0]
        )[0]
        # Assume inputs are compatible with ffmpeg
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

        # --- 3. Get Main Video Duration --- 
        try:
            main_duration = _get_media_duration(input_video_path)
            logger.info(
                f"[{content_id}] Input video duration: {main_duration} seconds"
            )
        except Exception as e:
            raise OverlayMusicError(
                f"Could not get duration of input video "
                f"{input_video_path}: {e}"
            )

        # --- 4. FFmpeg Processing (with looping inputs) ---
        # Get overlay position coords
        overlay_coords = OVERLAY_POSITIONS.get(
            overlay_position, OVERLAY_POSITIONS["bottom-right"]
        )

        # Adjusted Filter complex for looping music
        # Overlay (shortest=1 makes overlay duration match video)
        filter_overlay = f"[0:v][1:v]overlay={overlay_coords}:shortest=1[vout]"
        # Adjust music volume
        filter_volume = f"[2:a]volume={music_volume}[a_music]"
        # Mix main audio and looped music
        filter_mix = f"[0:a][a_music]amix=inputs=2:duration=first[aout]"
        filter_complex = f"{filter_overlay};{filter_volume};{filter_mix}"

        cmd = [
            'ffmpeg', '-y',
            # Input 0: Main Video (no loop)
            '-i', input_video_path,
            # Input 1: Overlay Media (looped)
            '-stream_loop', '-1', '-i', overlay_media_path,
            # Input 2: Music Media (looped)
            '-stream_loop', '-1', '-i', music_media_path,

            '-filter_complex', filter_complex,
            '-map', '[vout]',        # Map video output
            '-map', '[aout]',        # Map audio output
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-t', str(main_duration),  # Set output duration explicitly
            # Removed -shortest
            final_video_path
        ]

        logger.info(
            f"[{content_id}] Running ffmpeg for looping overlay and music..."
        )
        _run_ffmpeg(cmd, f"[{content_id}] Failed to apply looping overlay/music")

        if not os.path.exists(final_video_path):
            raise OverlayMusicError(
                f"[{content_id}] Output video file not found after ffmpeg: "
                f"{final_video_path}"
            )
        logger.info(
            f"[{content_id}] FFmpeg processing complete: {final_video_path}"
        )

        # --- 5. Upload to S3 ---
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
        # --- 6. Send Webhook ---
        webhook_payload = {
            # Include original content_id for tracking
            "content_id": content_id,
            "status": status
        }
        if status == "completed" and s3_url:
            webhook_payload["s3_url"] = s3_url
        elif error_message:
            webhook_payload["error"] = error_message

        logger.info(f"[{content_id}] Sending final webhook to: {webhook_url}")
        _send_webhook(webhook_url, webhook_payload)

        # --- 7. Cleanup ---
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