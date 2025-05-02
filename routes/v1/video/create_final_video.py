# routes/v1/video/create_final_video.py

import logging
from flask import Blueprint, request, jsonify
from services.v1.video.create_final_video import (
    create_final_video,
    VideoCreationError
)
from services.authentication import authenticate
from app_utils import validate_payload

# Rename bp to follow convention expected by app.py
v1_video_create_final_video_bp = Blueprint(
    'video', __name__, url_prefix='/v1/video'
)
logger = logging.getLogger(__name__)

# JSON schema for incoming payload
_payload_schema = {
    "type": "object",
    "properties": {
        "content_id": {"type": "string"},
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "image_url": {"type": "string", "format": "uri"},
                    "audio_url": {"type": "string", "format": "uri"},
                    "order": {"type": "integer", "minimum": 1},
                    "zoom_type": {
                        "type": "string",
                        "enum": ["None", "Zoom In", "Zoom Out"]
                    },
                    "zoom_speed": {"type": "number", "minimum": 0},
                    "transition_type": {
                        "type": "string",
                        "enum": ["None", "Fade", "Cut"]
                    },
                    "transition_duration": {"type": "number", "minimum": 0}
                },
                "required": ["image_url", "audio_url", "order"]
            }
        }
    },
    "required": ["content_id", "scenes"]
}

@v1_video_create_final_video_bp.route('/create-final-video', methods=['POST'])
@authenticate
@validate_payload(_payload_schema)
def create_final_video_endpoint():
    """
    Recebe um JSON com content_id, title (opcional) e lista de scenes.
    Cada scene inclui image_url, audio_url, order e opções de zoom/transição.
    Retorna um JSON com status e o path do vídeo final.
    """
    payload = request.get_json()
    content_id = payload['content_id']
    title = payload.get('title')
    scenes = payload['scenes']

    try:
        final_path = create_final_video(
            content_id=content_id,
            title=title,
            scenes=scenes
        )
        return jsonify({
            "status": "completed",
            "video_path": final_path
        }), 200

    except VideoCreationError as e:
        # Log specific video creation error
        logger.error(f"Video creation failed for {content_id}: {e}")
        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500

    except Exception as e:
        # unexpected
        logger.error(
            f"Unexpected error during video creation for {content_id}: {e}",
            exc_info=True
        )
        return jsonify({
            "status": "failed",
            "error": "Unexpected error during video creation"
        }), 500