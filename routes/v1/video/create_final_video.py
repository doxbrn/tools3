# routes/v1/video/create_final_video.py

from flask import Blueprint, jsonify
import logging

from app_utils import validate_payload, queue_task_wrapper
from services.authentication import authenticate
from services.v1.video.create_final_video import create_final_video

logger = logging.getLogger(__name__)
bp = Blueprint("v1_video_create", __name__)

SCHEMA = {
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
        "title":           {"type": "string"},
        "webhook_url":     {"type": "string", "format": "uri"},
        "content_id":      {"type": "string"},
        "advanced_options":{"type": "object"}
    },
    "required": ["scenes"],
    "additionalProperties": False
}

@bp.route("/v1/video/create-final-video", methods=["POST"])
@authenticate
@validate_payload(SCHEMA)
@queue_task_wrapper(bypass_queue=False)
def create_final_route(job_id, data):
    logger.info(f"Job {job_id}: enqueued")
    try:
        res = create_final_video(
            job_id=job_id,
            scenes=data["scenes"],
            title=data.get("title"),
            webhook_url=data.get("webhook_url"),
            content_id=data.get("content_id"),
            advanced=data.get("advanced_options", {})
        )
        if res.get("status") == "failed":
            logger.error(f"Job {job_id}: {res['error']}")
            return jsonify({"error": res["error"]}), 500
        return jsonify({"job_id": job_id}), 202

    except Exception as e:
        logger.exception(f"Job {job_id}: unexpected")
        return jsonify({"error": str(e)}), 500