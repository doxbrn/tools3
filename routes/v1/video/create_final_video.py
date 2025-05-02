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

from flask import Blueprint, jsonify, request
from app_utils import validate_payload, queue_task_wrapper
import logging
from services.v1.video.create_final_video import create_final_video
from services.authentication import authenticate

v1_video_create_bp = Blueprint('v1_video_create_final_video', __name__)
logger = logging.getLogger(__name__)

# JSON Schema alinhado aos parâmetros esperados pelo create_final_video
CREATE_FINAL_VIDEO_SCHEMA = {
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
        "title":        {"type": "string"},
        "webhook_url":  {"type": "string", "format": "uri"},
        "content_id":   {"type": "string"},
        "advanced_options": {
            "type": "object",
            "properties": {
                "overlay": {
                    "type": "object",
                    "properties": {
                        "url":      {"type": ["string", "null"], "format": "uri"},
                        "position": {"type": ["string", "null"]},
                        "opacity":  {"type": ["number", "null"]}
                    }
                },
                "zoom": {
                    "type": "object",
                    "properties": {
                        "type":  {"type": ["string", "null"]},
                        "speed": {"type": ["number", "null"]}
                    }
                },
                "background_music": {
                    "type": "object",
                    "properties": {
                        "url":    {"type": ["string", "null"], "format": "uri"},
                        "volume": {"type": ["number", "null"]}
                    }
                },
                "captions": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": ["boolean", "null"]},
                        "style":   {"type": ["string", "null"]}
                    }
                },
                "transitions": {
                    "type": "object",
                    "properties": {
                        "type":     {"type": ["string", "null"]},
                        "duration": {"type": ["number", "null"]}
                    }
                }
            },
            "additionalProperties": False
        }
    },
    "required": ["scenes"],
    "additionalProperties": False
}

@v1_video_create_bp.route('/v1/video/create-final-video', methods=['POST'])
@authenticate
@validate_payload(CREATE_FINAL_VIDEO_SCHEMA)
@queue_task_wrapper(bypass_queue=False)
def create_final_video_route(job_id: str, data: dict):
    """
    Rota para criação de vídeo final. Valida payload, autentica,
    enfileira job e chama o serviço de criação de vídeo.
    Retorna JSON com URL do vídeo ou mensagem de erro.
    """
    scenes = data['scenes']
    title = data.get('title')
    webhook_url = data.get('webhook_url')
    content_id = data.get('content_id')
    advanced_options = data.get('advanced_options')

    logger.info(
        f"Job {job_id}: Received create-final-video request for {len(scenes)} scenes, content_id: {content_id}"
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
            return jsonify({'error': error_msg}), 500

        # Sucesso: 'video_url' já é um link público ao S3
        video_url = result.get('video_url')
        logger.info(f"Job {job_id}: Video created successfully: {video_url}")
        return jsonify({'video_url': video_url}), 200

    except Exception as e:
        logger.exception(f"Job {job_id}: Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500
