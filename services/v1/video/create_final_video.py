# Copyright (c) 2025 Stephen G. Pope
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import shutil
import logging
import subprocess
import requests
from config import (
    LOCAL_STORAGE_PATH,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_REGION
)
from services.file_management import download_file
from services.s3_toolkit import upload_to_s3

logger = logging.getLogger(__name__)


def _send_webhook_notification(webhook_url, job_id, status, data=None,
                               error_message=None):
    """Helper function to send webhook notification."""
    if not webhook_url:
        logger.info(
            f"Job {job_id}: No webhook URL provided, skipping notification.")
        return

    payload = {
        "job_id": job_id,
        "status": status,
    }
    if data:
        payload.update(data)
    if error_message:
        payload["error"] = error_message

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(
            f"Job {job_id}: Successfully sent {status} "
            f"notification to {webhook_url}"
        )
    except requests.exceptions.RequestException as e:
        logger.error(
            f"Job {job_id}: Failed to send notification to {webhook_url}: {e}"
        )


def process_create_final_video(scenes, job_id, title=None, webhook_url=None):
    """
    Create a final video from a list of scenes, each containing image
    and audio. Uploads the final video to S3 and sends a webhook notification.

    Args:
        scenes (list): List of scenes, each with image_url and audio_url
        job_id (str): Unique job identifier
        title (str, optional): Title of the video. Included in webhook.
        webhook_url (str, optional): Webhook URL for notifications

    Returns:
        str: S3 URL of the final video file upon success.

    Raises:
        Exception: If any critical step (download, ffmpeg, upload) fails.
    """
    temp_dir = os.path.join(LOCAL_STORAGE_PATH, f"final_video_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)

    segment_files = []
    final_video_local_path = os.path.join(
        LOCAL_STORAGE_PATH, f"{job_id}_final.mp4"
    )
    concat_file_path = os.path.join(temp_dir, "concat_list.txt")
    s3_url = None

    try:
        logger.info(
            f"Job {job_id}: Starting final video creation with "
            f"{len(scenes)} scenes. Title: {title}"
        )

        for i, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: Processing scene {i+1}/{len(scenes)}")

            image_url = scene.get('image_url')
            audio_url = scene.get('audio_url')

            if not image_url or not audio_url:
                logger.warning(
                    f"Job {job_id}: Scene {i+1} missing image/audio url, "
                    f"skipping"
                )
                continue

            # Default ext
            image_ext = os.path.splitext(image_url)[1] or '.jpg'
            # Default ext
            audio_ext = os.path.splitext(audio_url)[1] or '.wav'
            image_filename = f"image_{i}{image_ext}"
            audio_filename = f"audio_{i}{audio_ext}"
            local_image_path = os.path.join(temp_dir, image_filename)
            local_audio_path = os.path.join(temp_dir, audio_filename)

            image_path = download_file(image_url, local_image_path)
            audio_path = download_file(audio_url, local_audio_path)

            segment_path = os.path.join(temp_dir, f"segment_{i}.mp4")
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1',
                '-i', image_path,
                '-i', audio_path,
                '-c:v', 'libx264',
                '-tune', 'stillimage',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                '-shortest',
                segment_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            segment_files.append(segment_path)

            os.remove(image_path)
            os.remove(audio_path)

        if not segment_files:
            raise ValueError("No valid scenes processed to create a video.")

        with open(concat_file_path, 'w') as f:
            for segment in segment_files:
                f.write(f"file '{os.path.abspath(segment)}'\\n")

        concat_cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file_path,
            '-c', 'copy',
            final_video_local_path
        ]
        subprocess.run(concat_cmd, check=True, capture_output=True)
        logger.info(
            f"Job {job_id}: Local final video created: "
            f"{final_video_local_path}"
        )

        logger.info(f"Job {job_id}: Uploading {final_video_local_path} to S3 "
                    f"bucket {S3_BUCKET_NAME}")
        s3_url = upload_to_s3(
            file_path=final_video_local_path,
            s3_url=S3_ENDPOINT_URL,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket_name=S3_BUCKET_NAME,
            region=S3_REGION
        )
        if not s3_url:
            raise Exception(
                f"Failed to upload {final_video_local_path} to S3."
            )
        logger.info(
            f"Job {job_id}: Successfully uploaded video to S3: {s3_url}")

        webhook_data = {"video_url": s3_url, "title": title}
        _send_webhook_notification(webhook_url, job_id, "success",
                                   data=webhook_data)

        return s3_url

    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode() if e.stderr else "No stderr output"
        logger.error(
            f"Job {job_id}: FFmpeg command failed: {e.cmd}\\nError: "
            f"{error_output}")
        error_message = f"FFmpeg error: {error_output}"
        _send_webhook_notification(webhook_url, job_id, "failure",
                                   error_message=error_message,
                                   data={"title": title})
        raise Exception(error_message) from e
    except Exception as e:
        logger.error(f"Job {job_id}: Error creating final video: {str(e)}")
        _send_webhook_notification(webhook_url, job_id, "failure",
                                   error_message=str(e), data={"title": title})
        raise

    finally:
        try:
            if os.path.exists(final_video_local_path):
                os.remove(final_video_local_path)
                logger.debug(
                    f"Job {job_id}: Removed local final video "
                    f"{final_video_local_path}"
                )
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(
                    f"Job {job_id}: Cleaned up temporary directory {temp_dir}"
                )
        except Exception as e:
            logger.warning(
                f"Job {job_id}: Error cleaning up local files: {str(e)}"
            )

# Example usage (for testing purposes,
# not called by the route directly usually)
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.INFO)
#     test_scenes = [
#         {'image_url': 'URL_TO_IMAGE_1', 'audio_url': 'URL_TO_AUDIO_1'},
#         {'image_url': 'URL_TO_IMAGE_2', 'audio_url': 'URL_TO_AUDIO_2'}
#     ]
#     test_job_id = 'test-123'
#     test_webhook = 'YOUR_TEST_WEBHOOK_URL'
#     try:
#         final_url = process_create_final_video(
#               test_scenes, test_job_id, title="Test Video",
#               webhook_url=test_webhook
#         )
#         print(f"Process completed. Final URL: {final_url}")
#     except Exception as e:
#         print(f"Process failed: {e}")