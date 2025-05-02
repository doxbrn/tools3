from flask import Blueprint
from app_utils import validate_payload, queue_task_wrapper
import logging

from services.authentication import authenticate
from services.v1.video.create_final_video import create_final_video

logger = logging.getLogger(__name__)
v1_video_create_final_video_bp = Blueprint(
    "v1_video_create_final_video", __name__
)

# Schema mínimo alinhado ao serviço
CREATE_FINAL_VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes":           {"type": "array", "minItems": 1},
        "title":            {"type": "string"},
        "webhook_url":      {"type": "string", "format": "uri"},
        "content_id":       {"type": "string"},
        "advanced_options": {"type": "object"}
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
    """
    Enfileira criação de vídeo:

    - job_id: gerado pelo queue_task_wrapper
    - data: JSON validado pelo validate_payload
    Retorna tuple (payload, endpoint, status_code).
    """
    scenes           = data["scenes"]
    title            = data.get("title")
    webhook_url      = data.get("webhook_url")
    content_id       = data.get("content_id")
    advanced_options = data.get("advanced_options")

    logger.info(
        f"Job {job_id}: criando vídeo para {len(scenes)} cenas (content_id={content_id})"
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
            err = result.get("error", "erro desconhecido")
            logger.error(f"Job {job_id}: falha na criação: {err}")
            return ({"error": err}, "/v1/video/create-final-video", 500)

        video_url = result["video_url"]
        logger.info(f"Job {job_id}: vídeo gerado com sucesso: {video_url}")
        return ({"video_url": video_url}, "/v1/video/create-final-video", 202)

    except Exception as e:
        logger.exception(f"Job {job_id}: erro inesperado: {e}")
        return ({"error": str(e)}, "/v1/video/create-final-video", 500)