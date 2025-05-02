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

from flask import Blueprint, request, jsonify
from app_utils import validate_payload, queue_task_wrapper
import logging
import uuid
from services.v1.video.create_final_video import create_final_video
from services.authentication import authenticate
from services.cloud_storage import upload_file

v1_video_create_final_video_bp = Blueprint(
    'v1_video_create_final_video', __name__
)
logger = logging.getLogger(__name__)


@v1_video_create_final_video_bp.route('/create-final-video', methods=['POST'])
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
                    "audio_url": {"type": "string", "format": "uri"},
                    "text": {"type": "string"},
                    "options": {
                        "type": "object",
                        "properties": {
                            "overlay": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string", "format": "uri"},
                                    "position": {"type": "string", "enum": ["Topo", "Centro", "Base", "Personalizado"]},
                                    "opacity": {"type": "number", "minimum": 0, "maximum": 100}
                                }
                            },
                            "zoom": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["Zoom In", "Zoom Out", "Pan Horizontal", "Pan Vertical", "Ken Burns", "Nenhum"]},
                                    "speed": {"type": "number", "minimum": 1, "maximum": 20}
                                }
                            }
                        }
                    }
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
                "overlay": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "format": "uri"},
                        "position": {"type": "string", "enum": ["Topo", "Centro", "Base", "Personalizado"]},
                        "opacity": {"type": "number", "minimum": 0, "maximum": 100}
                    }
                },
                "zoom": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["Zoom In", "Zoom Out", "Pan Horizontal", "Pan Vertical", "Ken Burns", "Nenhum"]},
                        "speed": {"type": "number", "minimum": 1, "maximum": 20}
                    }
                },
                "background_music": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "format": "uri"},
                        "volume": {"type": "number", "minimum": 0, "maximum": 100}
                    }
                },
                "captions": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "style": {"type": "string", "enum": ["Padrão", "Contrastado", "Minimalista", "Grande"]}
                    }
                },
                "transitions": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["Corte Seco", "Fade", "Dissolver", "Deslizar", "Zoom"]},
                        "duration": {"type": "number", "minimum": 0.1, "maximum": 3.0}
                    }
                }
            }
        }
    },
    "required": ["scenes"]
})
@queue_task_wrapper(bypass_queue=False)
def create_final_video_route():
    """
    Create a final video by combining multiple scenes (image + audio).
    Each scene can have visual effects applied, and the final video
    can include background music and captions/subtitles.

    Request body must include:
    - scenes: Array of scenes, each with image_url and audio_url
    
    Optional parameters:
    - title: Title of the video
    - webhook_url: URL to notify when processing is complete
    - id: Custom identifier for the video
    - advanced_options: Advanced video processing options including:
        - overlay: Options for overlay image
        - zoom: Options for zoom/pan effects
        - background_music: Options for background music
        - captions: Options for captions/subtitles
        - transitions: Options for transitions between scenes

    Returns:
        JSON with job_id and status
    """
    request_data = request.json
    scenes = request_data.get('scenes', [])
    title = request_data.get('title')
    webhook_url = request_data.get('webhook_url')
    content_id = request_data.get('id')
    advanced_options = request_data.get('advanced_options')

    job_id = str(uuid.uuid4())
    logger.info(f"Job {job_id}: Received create-final-video request for {len(scenes)} scenes, id: {content_id}")

    # Process asynchronously
    import threading
    thread = threading.Thread(
        target=create_final_video,
        args=(job_id, scenes, title, webhook_url, content_id, advanced_options)
    )
    thread.start()

    return jsonify({
        "job_id": job_id,
        "status": "processing",
        "message": "Video creation started. You will be notified via webhook when complete."
    })


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
                    },
                    "required": ["caption_text"]
                }
            }
        }
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
    advanced_options = data.get('advanced_options')

    logger.info(
        f"Job {job_id}: Received create-final-video request for "
        f"{len(scenes)} scenes, id: {request_id}"
    )

    try:
        output_file = process_create_final_video(
            scenes, job_id, title, webhook_url, advanced_options
        )
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