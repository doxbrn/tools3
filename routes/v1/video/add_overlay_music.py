# routes/v1/video/add_overlay_music.py

import logging
import threading
from flask import Blueprint, request, jsonify
# Import service function and position mapping
from services.v1.video.add_overlay_music import (
    add_overlay_and_music, OVERLAY_POSITIONS
)
from services.authentication import authenticate
from app_utils import validate_payload

logger = logging.getLogger(__name__)

# Define Blueprint
v1_video_add_overlay_music_bp = Blueprint(
    'add_overlay_music',
    __name__,
    url_prefix='/v1/video'
)


# JSON Schema for Payload Validation
_payload_schema = {
    "type": "object",
    "properties": {
        "input_video_url": {"type": "string", "format": "uri"},
        "overlay_image_url": {"type": "string", "format": "uri"},
        "background_music_url": {"type": "string", "format": "uri"},
        "webhook_url": {"type": "string", "format": "uri"},
        "content_id": {"type": "string"},  # Required for tracking/temp files
        "overlay_position": {
            "type": "string",
            "enum": list(OVERLAY_POSITIONS.keys()),
            "default": "bottom-right"
        },
        "music_volume": {
            "type": "number",
            "minimum": 0,
            "maximum": 2.0,  # Allow doubling volume, default is 0.5
            "default": 0.5
        },
        "output_filename": {"type": "string", "minLength": 1}
    },
    "required": [
        "input_video_url",
        "overlay_image_url",
        "background_music_url",
        "webhook_url",
        "content_id"
    ]
}


@v1_video_add_overlay_music_bp.route('/add-overlay-music', methods=['POST'])
@authenticate
@validate_payload(_payload_schema)
def add_overlay_music_endpoint():
    """
    Receives video, overlay, music URLs, webhook URL, and options.
    Starts the overlay/music addition process in the background.
    Returns 202 Accepted immediately.
    """
    payload = request.get_json()
    content_id = payload['content_id']
    webhook_url = payload['webhook_url']
    
    logger.info(
        f"[{content_id}] Received request to add overlay/music, "
        f"notifying: {webhook_url}"
    )

    # Prepare arguments for the background task
    overlay_default = _payload_schema['properties']['overlay_position']['default']
    music_vol_default = _payload_schema['properties']['music_volume']['default']
    
    task_kwargs = {
        'content_id': content_id,
        'input_video_url': payload['input_video_url'],
        'overlay_image_url': payload['overlay_image_url'],
        'background_music_url': payload['background_music_url'],
        'webhook_url': webhook_url,
        'overlay_position': payload.get('overlay_position', overlay_default),
        'music_volume': payload.get('music_volume', music_vol_default),
         # Optional, defaults to None
        'output_filename': payload.get('output_filename')
    }

    # Start processing in a background thread
    thread = threading.Thread(
        target=add_overlay_and_music,
        kwargs=task_kwargs,
        daemon=True
    )
    thread.start()

    # Respond immediately
    message = (
        f"Overlay/music addition process started for {content_id}. "
        f"Result will be sent to {webhook_url}"
    )
    return jsonify({
        "status": "processing",
        "message": message
    }), 202 