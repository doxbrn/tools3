# routes/v1/video/render_video.py

import logging
import threading
from flask import Blueprint, request, jsonify
from services.v1.video.render_video import render_video
from services.authentication import authenticate
from app_utils import validate_payload
# Import constants for schema validation
from services.v1.video.add_overlay_music import (
    OVERLAY_POSITION_COORDS, SUPPORTED_BLEND_MODES
)

logger = logging.getLogger(__name__)

# Define Blueprint
v1_video_render_bp = Blueprint(
    'render_video', 
    __name__, 
    url_prefix='/v1/video'
)

# --- JSON Schema Definition --- #
# (This is quite detailed and reflects the unified service capabilities)

_scene_schema = {
    "type": "object",
    "properties": {
        "order": {"type": "integer", "minimum": 1},
        "image_url": {"type": "string", "format": "uri"},
        "audio_url": {"type": "string", "format": "uri"},
        "zoom_type": {
            "type": "string",
            "enum": ["None", "Zoom In", "Zoom Out"],
            "default": "None"
        },
        "zoom_speed": {"type": "number", "minimum": 0, "default": 1.0},
        # TODO: Add text overlay options per scene
        # TODO: Add advanced zoom/pan options per scene
        # TODO: Add transition options *to* next scene
    },
    "required": ["order", "image_url", "audio_url"]
}

_overlay_schema = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "position": {
            "type": "string", 
            "enum": ["full"] + list(OVERLAY_POSITION_COORDS.keys()), 
            "default": "bottom-right"
        },
        "opacity": {
            "type": "number", 
            "minimum": 0.0, 
            "maximum": 1.0, 
            "default": 1.0
        },
        "blend_mode": {
            "type": "string", 
            "enum": SUPPORTED_BLEND_MODES
        }
    },
    "required": ["url"] # URL is mandatory if overlay_options is present
}

_music_schema = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "volume": {"type": "number", "minimum": 0, "maximum": 2.0, "default": 0.5}
    },
    "required": ["url"] # URL is mandatory if music_options is present
}

_caption_schema = {
    "type": "object",
    "properties": {
        # For now, only support providing a pre-generated ASS file URL
        "source": {"type": "string", "format": "uri"},
        # TODO: Add options for Whisper generation (language, model)
        # TODO: Add options for SRT source
        # TODO: Add rich styling options (font, color, etc.) - REQUIRES DEPENDENCIES
    },
    "required": ["source"]
}

_output_schema = {
    "type": "object",
    "properties": {
        "filename": {"type": "string", "minLength": 1},
        # TODO: Add S3 path prefix option?
    },
    "additionalProperties": False
}

# --- Main Payload Schema --- #
_payload_schema = {
    "type": "object",
    "properties": {
        "content_id": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": _scene_schema
        },
        "overlay_options": _overlay_schema, # Optional object
        "music_options": _music_schema,     # Optional object
        "caption_options": _caption_schema, # Optional object
        "output_options": _output_schema     # Optional object
    },
    "required": ["content_id", "webhook_url", "scenes"]
}

# --- Route Definition --- #
@v1_video_render_bp.route('/render', methods=['POST'])
@authenticate
@validate_payload(_payload_schema)
def render_video_endpoint():
    """
    Unified endpoint to render a video with scenes, overlay, music, captions.
    Starts the process in the background and returns 202 Accepted.
    """
    payload = request.get_json()
    content_id = payload['content_id']
    webhook_url = payload['webhook_url']
    log_prefix = f"[{content_id}]"
    
    logger.info(f"{log_prefix} Received request for unified render, notifying: {webhook_url}")

    # Start processing in a background thread
    # Pass the whole validated payload to the service function
    thread = threading.Thread(
        target=render_video,
        kwargs={'payload': payload},
        daemon=True
    )
    thread.start()

    # Respond immediately
    message = (
        f"Unified video render process started for {content_id}. "
        f"Result will be sent to {webhook_url}"
    )
    return jsonify({
        "status": "processing",
        "message": message
    }), 202 