# routes/v1/video/create_final_video.py
from flask import Blueprint
import logging
from app_utils import validate_payload, queue_task_wrapper
from services.authentication import authenticate
from services.v1.video.create_final_video import create_final_video

logger = logging.getLogger(__name__)
v1_video_create_final_video_bp = Blueprint(
    "v1_video_create_final_video", __name__
)

CREATE_FINAL_VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes":           {"type": "array", "minItems": 1},
        "title":            {"type": "string"},
        "webhook_url":      {"type": "string", "format": "uri"},
        "content_id":       {"type": "string"},
        "advanced_options": {"type": "object"},
    },
    "required": ["scenes"],
    "additionalProperties": False
}


@v1_video_create_final_video_bp.route(
    "/v1/video/create-final-video", methods=["POST"]
)
@authenticate
@validate_payload(CREATE_FINAL_VIDEO_SCHEMA)
@queue_task_wrapper(bypass_queue=False)
def create_final_video_route(job_id: str, data: dict):
    scenes           = data["scenes"]
    title            = data.get("title")
    webhook_url      = data.get("webhook_url")
    content_id       = data.get("content_id")
    advanced_options = data.get("advanced_options")

    logger.info(
        f"Job {job_id}: creating video for {len(scenes)} scenes (content_id={content_id})"
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

        if result.get("status") == "failed":
            err = result.get("error", "unknown error")
            logger.error(f"Job {job_id}: creation failed: {err}")
            return ({"error": err}, "/v1/video/create-final-video", 500)

        url = result["video_url"]
        logger.info(f"Job {job_id}: video ready → {url}")
        return ({"video_url": url}, "/v1/video/create-final-video", 202)

    except Exception as e:
        logger.exception(f"Job {job_id}: unexpected error: {e}")
        return ({"error": str(e)}, "/v1/video/create-final-video", 500)
