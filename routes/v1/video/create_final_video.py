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

from flask import Blueprint
from app_utils import validate_payload, queue_task_wrapper
import logging
from services.v1.video.create_final_video import process_create_final_video
from services.authentication import authenticate
from services.cloud_storage import upload_file

v1_video_create_final_video_bp = Blueprint(
    'v1_video_create_final_video', __name__
)
logger = logging.getLogger(__name__)


@v1_video_create_final_video_bp.route(
    '/v1/video/create-final-video', methods=['POST']
)
@authenticate
@validate_payload({
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image_url": {"type": "string", "format": "uri"},
                    "audio_url": {"type": "string", "format": "uri"}
                },
                "required": ["image_url", "audio_url"]
            },
            "minItems": 1
        },
        "title": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "id": {"type": "string"}
    },
    "required": ["scenes"],
    "additionalProperties": False
})
@queue_task_wrapper(bypass_queue=False)
def create_final_video(job_id, data):
    scenes = data['scenes']
    title = data.get('title')
    webhook_url = data.get('webhook_url')
    request_id = data.get('id')  # Rename to avoid conflict with built-in id

    logger.info(
        f"Job {job_id}: Received create-final-video request for "
        f"{len(scenes)} scenes, id: {request_id}"
    )

    try:
        output_file = process_create_final_video(
            scenes, job_id, title, webhook_url
        )
        logger.info(
            f"Job {job_id}: Final video creation process completed successfully"
        )

        cloud_url = upload_file(output_file)
        logger.info(
            f"Job {job_id}: Final video uploaded to cloud storage: {cloud_url}"
        )

        return cloud_url, "/v1/video/create-final-video", 200

    except Exception as e:
        error_message = f"Job {job_id}: Error during final video creation - {str(e)}"
        logger.error(error_message)
        return str(e), "/v1/video/create-final-video", 500 