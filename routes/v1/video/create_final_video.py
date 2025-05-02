# routes/v1/video/create_final_video.py
from flask import Blueprint
import logging
import time
from app_utils import validate_payload, queue_task_wrapper
from services.authentication import authenticate
from services.v1.video.create_final_video import create_final_video
from services.airtable_client import AirtableClient

logger = logging.getLogger(__name__)
v1_video_create_final_video_bp = Blueprint(
    "v1_video_create_final_video", __name__
)

CREATE_FINAL_VIDEO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {"type": "array", "minItems": 1},
        "title": {"type": "string"},
        "webhook_url": {"type": "string", "format": "uri"},
        "content_id": {"type": "string"},
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
    scenes = data["scenes"]
    title = data.get("title")
    webhook_url = data.get("webhook_url")
    content_id = data.get("content_id")
    advanced_options = data.get("advanced_options")

    scene_count = len(scenes)
    logger.info(
        f"Job {job_id}: creating video for {scene_count} scenes "
        f"(content_id={content_id})"
    )

    # Track job in Airtable
    airtable = AirtableClient()
    
    # Create initial route log entry with request data
    route_log = airtable.create_job_log(
        job_id=f"route-{job_id}",
        job_type="Video_Processing",
        service_name="create_final_video_route",
        related_content_id=content_id,
        metadata={
            "route": "/v1/video/create-final-video",
            "scene_count": scene_count,
            "has_webhook": webhook_url is not None,
            "has_advanced_options": advanced_options is not None
        }
    )
    
    start_time = time.time()
    
    try:
        result = create_final_video(
            job_id=job_id,
            scenes=scenes,
            title=title,
            webhook_url=webhook_url,
            content_id=content_id,
            advanced_options=advanced_options
        )

        duration = time.time() - start_time
        
        if result.get("status") == "failed":
            err = result.get("error", "unknown error")
            logger.error(f"Job {job_id}: creation failed: {err}")
            
            # Update job log with failure
            airtable.update_job_status(
                log_record_id=route_log.get("id"),
                status="Failed",
                log_message=f"Video creation failed: {err}",
                error_details=err,
                duration_seconds=int(duration)
            )
            
            return ({"error": err}, "/v1/video/create-final-video", 500)

        url = result["video_url"]
        logger.info(f"Job {job_id}: video ready → {url}")
        
        # Update job log with success
        airtable.update_job_status(
            log_record_id=route_log.get("id"),
            status="Completed",
            log_message=f"Video creation completed successfully. URL: {url}",
            duration_seconds=int(duration),
            metadata_updates={
                "results": {
                    "video_url": url,
                    "processing_time": round(duration, 2)
                }
            }
        )
        
        return ({"video_url": url}, "/v1/video/create-final-video", 202)

    except Exception as e:
        duration = time.time() - start_time
        logger.exception(f"Job {job_id}: unexpected error: {e}")
        
        # Update job log with error
        airtable.update_job_status(
            log_record_id=route_log.get("id"),
            status="Failed",
            log_message=f"Unexpected error in video creation route: {str(e)}",
            error_details=str(e),
            duration_seconds=int(duration)
        )
        
        return ({"error": str(e)}, "/v1/video/create-final-video", 500)
