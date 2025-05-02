# routes/v1/video/create_final_video.py
from flask import Blueprint
from app_utils import validate_payload, queue_task_wrapper
import logging
from services.authentication import authenticate
from services.v1.video.create_final_video import create_final_video

logger = logging.getLogger(__name__)
v1_video_create_final_video_bp = Blueprint('v1_video_create_final_video', __name__)

SCHEMA = {
    'type': 'object',
    'properties': {
        'scenes': {'type':'array','minItems':1},
        'title': {'type':'string'},
        'webhook_url': {'type':'string','format':'uri'},
        'content_id': {'type':'string'},
        'advanced_options': {'type':'object'}
    },
    'required':['scenes'],
    'additionalProperties':False
}

@v1_video_create_final_video_bp.route('/v1/video/create-final-video', methods=['POST'])
@authenticate
@validate_payload(SCHEMA)
@queue_task_wrapper(bypass_queue=False)
def route_create_final_video(job_id: str, data: dict):
    logger.info(f"Job {job_id}: enqueue video build")
    try:
        res = create_final_video(
            job_id=job_id,
            scenes=data['scenes'],
            title=data.get('title'),
            webhook_url=data.get('webhook_url'),
            content_id=data.get('content_id'),
            advanced_options=data.get('advanced_options')
        )
        if res.get('status')=='failed':
            return ({'error':res['error']}, '/v1/video/create-final-video', 500)
        return ({'video_url':res['video_url']}, '/v1/video/create-final-video', 202)
    except Exception as e:
        logger.exception(e)
        return ({'error':str(e)}, '/v1/video/create-final-video', 500)
