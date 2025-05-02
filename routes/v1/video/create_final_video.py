# routes/v1/video/create_final_video.py

import logging
import threading  # Import threading
from flask import Blueprint, request, jsonify
from services.v1.video.create_final_video import create_final_video
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
        },
        "webhook_url": {"type": "string", "format": "uri"}
    },
    "required": ["content_id", "scenes", "webhook_url"]
}

@v1_video_create_final_video_bp.route('/create-final-video', methods=['POST'])
@authenticate
@validate_payload(_payload_schema)
def create_final_video_endpoint():
    """
    Recebe JSON com content_id, title?, scenes, webhook_url.
    Inicia a criação do vídeo em background e retorna 202 Accepted.
    Envia o resultado final para o webhook_url.
    """
    payload = request.get_json()
    content_id = payload['content_id']
    title = payload.get('title')
    scenes = payload['scenes']
    webhook_url = payload['webhook_url']  # Get webhook_url

    logger.info(
        f"Received request to create video for content_id: {content_id}, "
        f"notifying: {webhook_url}"
    )

    # --- Start video creation in a background thread --- 
    thread = threading.Thread(
        target=create_final_video,
        kwargs={
            'content_id': content_id,
            'title': title,
            'scenes': scenes,
            'webhook_url': webhook_url  # Pass webhook_url to the service
        },
        # Allows main thread to exit even if this thread is running
        daemon=True 
    )
    thread.start()
    # -----------------------------------------------------

    # Return 202 Accepted immediately
    message = (
        f"Video creation started for {content_id}. "
        f"Result will be sent to {webhook_url}"
    )
    return jsonify({
        "status": "processing",
        "message": message
    }), 202

    # Removed the synchronous error handling here, it will be handled
    # by the background thread sending to the webhook.