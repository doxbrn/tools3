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
        "id": {"type": "string"},
        "advanced_options": {
            "type": "object",
            "properties": {
                "effects": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "zoom": {"type": "boolean"},
                            "zoom_factor": {"type": "number", "minimum": 1.0, "maximum": 3.0},
                            "zoom_duration": {"type": "string", "enum": ["in", "out", "full"]},
                            "overlay_url": {"type": "string", "format": "uri"},
                            "overlay_position": {"type": "string", "enum": [
                                "top-left", "top-right", "bottom-left", "bottom-right", "center"
                            ]},
                            "overlay_opacity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "color_filter": {"type": "string", "enum": [
                                "greyscale", "sepia", "warm", "cold"
                            ]}
                        }
                    }
                },
                "music": {
                    "type": "object",
                    "properties": {
                        "music_url": {"type": "string", "format": "uri"},
                        "music_volume": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "original_volume": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                    },
                    "required": ["music_url"]
                },
                "captions": {
                    "type": "object",
                    "properties": {
                        "caption_text": {"type": "string"},
                        "caption_type": {"type": "string", "enum": ["srt", "ass", "vtt"]},
                        "caption_style": {
                            "type": "object",
                            "properties": {
                                "font_name": {"type": "string"},
                                "font_size": {"type": "integer", "minimum": 8, "maximum": 72},
                                "primary_color": {"type": "string"},
                                "outline_color": {"type": "string"},
                                "back_color": {"type": "string"},
                                "bold": {"type": "integer", "enum": [0, 1]},
                                "italic": {"type": "integer", "enum": [0, 1]},
                                "alignment": {"type": "integer", "minimum": 1, "maximum": 9}
                            }
                        }
                    }
                }
            }
        }
    },
    "required": ["scenes"],
    "additionalProperties": False
})
@queue_task_wrapper(bypass_queue=False)
def create_final_video_v1_route(job_id, data):
    scenes = data['scenes']
    title = data.get('title')
    webhook_url = data.get('webhook_url')
    request_id = data.get('id')  # Rename to avoid conflict with built-in id
    advanced_options = data.get('advanced_options')

    logger.info(
        f"Job {job_id}: Received create-final-video request for "
        f"{len(scenes)} scenes, id: {request_id}"
    )

    try:
        # Call the imported create_final_video function from the services module
        result = create_final_video(
            job_id, scenes, title, webhook_url, request_id, advanced_options
        )
        
        # Check if the result is a dictionary with status or a direct path
        if isinstance(result, dict):
            if result.get('status') == 'failed':
                error_message = result.get('error', 'Unknown error')
                logger.error(
                    f"Job {job_id}: Video creation failed: {error_message}"
                )
                return error_message, "/v1/video/create-final-video", 500
            
            # If success, get the video_url from the result
            output_file = result.get('video_url')
            if not output_file:
                raise ValueError("No video URL in the success response")
        else:
            # Assume result is the direct output file path
            output_file = result
            
        logger.info(
            f"Job {job_id}: Final video creation completed successfully"
        )

        cloud_url = upload_file(output_file)
        logger.info(
            f"Job {job_id}: Final video uploaded to cloud storage: {cloud_url}"
        )

        return cloud_url, "/v1/video/create-final-video", 200

    except Exception as e:
        error_message = (f"Job {job_id}: Error during final video creation - "
                         f"{str(e)}")
        logger.error(error_message)
        return str(e), "/v1/video/create-final-video", 500 