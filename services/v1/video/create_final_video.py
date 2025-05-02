# services/v1/video/create_final_video.py
import os
import shutil
import logging
import subprocess
import requests
import tempfile
from typing import List, Dict, Optional, Any

from config import (
    LOCAL_STORAGE_PATH,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY
)
from services.file_management import download_file
from services.s3_toolkit import upload_to_s3

logger = logging.getLogger(__name__)

# Default background music URL if user does not specify
DEFAULT_BG_MUSIC_URL = os.getenv("DEFAULT_BG_MUSIC_URL")  # e.g. set via env var


def _get_media_duration(path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        return float(val) if val and val.replace('.', '', 1).isdigit() else 10.0
    except Exception:
        logger.warning(f"Could not get duration for {path}, fallback 10s")
        return 10.0


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    logger.debug("FFmpeg: %s", ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"{err_msg}: {e.stderr}")
        raise


def _prepare_scene(job_dir: str, idx: int, scene: Dict[str, Any]) -> (str, str, str):
    seg_dir = os.path.join(job_dir, f"segment_{idx}")
    os.makedirs(seg_dir, exist_ok=True)
    img = os.path.join(seg_dir, f"image_{idx}.jpg")
    aud = os.path.join(seg_dir, f"audio_{idx}.mp3")
    download_file(scene['image_url'], img)
    download_file(scene['audio_url'], aud)
    logger.info("Downloaded %s and %s", scene['image_url'], scene['audio_url'])
    return img, aud, seg_dir


def _create_segment(img: str, aud: str, zoom: Dict[str, Any], out_path: str) -> None:
    duration = _get_media_duration(aud)
    # zoom on image
    if zoom['type'] != 'Nenhum':
        temp_vid = out_path.replace('segment_', 'zoom_')
        speed = max(1, min(20, zoom['speed'])) / 10.0
        flt = f"zoompan=z='if(eq(on,1),1,min(zoom+{speed/100},1.5))':d={int(duration*25)}:s=1920x1080"
        cmd1 = ['ffmpeg','-y','-loop','1','-i',img,'-filter_complex',flt,'-t',str(duration),'-c:v','libx264','-pix_fmt','yuv420p',temp_vid]
        _run_ffmpeg(cmd1, f"zoom error {img}")
        # merge audio\        
        cmd2 = ['ffmpeg','-y','-i',temp_vid,'-i',aud,'-c:v','copy','-c:a','aac','-shortest',out_path]
        _run_ffmpeg(cmd2, f"merge error {temp_vid}")
    else:
        # static image video
        cmd = ['ffmpeg','-y','-loop','1','-i',img,'-i',aud,'-c:v','libx264','-tune','stillimage','-c:a','aac','-b:a','192k','-pix_fmt','yuv420p','-shortest','-t',str(duration),out_path]
        _run_ffmpeg(cmd, f"segment error {img}")


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, Any]],
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content_id: Optional[str] = None,
    advanced_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"final_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    segments = []
    opts = advanced_options or {}
    try:
        logger.info(f"Job {job_id}: processing {len(scenes)} scenes")
        # build each segment
        for i, sc in enumerate(scenes):
            img, aud, segd = _prepare_scene(job_dir, i, sc)
            zoom_opt = opts.get('zoom', {'type':'Nenhum','speed':5})
            out_seg = os.path.join(segd, f"segment_{i}.mp4")
            _create_segment(img, aud, zoom_opt, out_seg)
            segments.append(out_seg)
            logger.info(f"scene {i} ready {out_seg}")
        # concat
        temp_out = os.path.join(job_dir, f"{job_id}_temp.mp4")
        listf = os.path.join(job_dir, 'list.txt')
        with open(listf,'w') as f:
            for s in segments: f.write(f"file '{s}'\n")
        cmdc = ['ffmpeg','-y','-f','concat','-safe','0','-i',listf,'-c','copy',temp_out]
        _run_ffmpeg(cmdc, "concat error")
        # background music: apply only if user DID NOT inform and default exists
        bg = opts.get('background_music',{}).get('url')
        if not bg and DEFAULT_BG_MUSIC_URL:
            bg = DEFAULT_BG_MUSIC_URL
        if bg:
            fm = os.path.join(job_dir, 'with_bgm.mp4')
            dur = _get_media_duration(temp_out)
            vol = opts.get('background_music',{}).get('volume',20)/100.0
            cmdm = ['ffmpeg','-y','-i',temp_out,'-stream_loop','-1','-i',bg,'-filter_complex',f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=end={dur}[bg];[0:a][bg]amix=inputs=2:duration=first[a]",'-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-shortest',fm]
            _run_ffmpeg(cmdm, "bgm error")
            shutil.move(fm, temp_out)
        # upload
        key = f"final_videos/{job_id}.mp4"
        s3_url = upload_to_s3(temp_out, key, S3_BUCKET_NAME, S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY)
        shutil.rmtree(job_dir)
        result = {'status':'completed','video_url':s3_url,'title':title,'id':content_id}
        if webhook_url: requests.post(webhook_url, json={'job_id':job_id,'status':'completed','data':result})
        return result
    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        if webhook_url: requests.post(webhook_url, json={'job_id':job_id,'status':'failed','error':str(e)})
        try: shutil.rmtree(job_dir)
        except: pass
        return {'status':'failed','error':str(e)}


