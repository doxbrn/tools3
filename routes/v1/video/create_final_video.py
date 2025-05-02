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
from services.v1.video.create_final_video import create_final_video
from services.authentication import authenticate

v1_video_create_final_video_bp = Blueprint(
    'v1_video_create_final_video', __name__
)
logger = logging.getLogger(__name__)

# Schema de validação para payload compatível com create_final_video
CREATE_FINAL_VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {"type": "array", "minItems": 1},
        "title": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "content_id": {"type": "string"},
        "advanced_options": {"type": "object"}
    },
    "required": ["scenes"],
    "additionalProperties": False
}

@v1_video_create_final_video_bp.route(
    '/v1/video/create-final-video', methods=['POST']
)
@authenticate
@validate_payload(CREATE_FINAL_VIDEO_SCHEMA)
@queue_task_wrapper(bypass_queue=False)
def create_final_video_route(job_id: str, data: dict):
    """
    Rota que enfileira a tarefa de criação de vídeo.
    Retorna tuple: (payload, endpoint, status_code) para o queue wrapper.
    """
    scenes = data['scenes']
    title = data.get('title')
    webhook_url = data.get('webhook_url')
    content_id = data.get('content_id')
    advanced_options = data.get('advanced_options')

    logger.info(
        f"Job {job_id}: Received create-final-video for {len(scenes)} scenes, content_id={content_id}"
    )

    try:
        result = create_final_video(
            job_id=job_id,
            scenes=scenes,
            title=title,
            webhook_url=webhook_url,
            content_id=content_id,
            advanced_options=advanced_options
        )

        if result.get('status') == 'failed':
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Job {job_id}: Video creation failed: {error_msg}")
            return ({'error': error_msg}, '/v1/video/create-final-video', 500)

        video_url = result.get('video_url')
        logger.info(f"Job {job_id}: Video created successfully: {video_url}")
        return ({'video_url': video_url}, '/v1/video/create-final-video', 200)

    except Exception as e:
        logger.exception(f"Job {job_id}: Unexpected error: {str(e)}")
        return ({'error': str(e)}, '/v1/video/create-final-video', 500)
