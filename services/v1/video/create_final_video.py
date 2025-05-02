# services/v1/video/create_final_video.py

import os
import shutil
import logging
import subprocess
import tempfile
from typing import List, Dict, Optional, Any
import requests

from config import LOCAL_STORAGE_PATH, DEFAULT_BACKGROUND_MUSIC_URL
from services.file_management import download_file
from services.s3_toolkit import upload_to_s3

logger = logging.getLogger(__name__)
SEGMENT_PREFIX = "segment_"
DEFAULT_DURATION = 10.0


def _probe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except Exception:
        logger.warning(f"Could not probe duration of {path}, using {DEFAULT_DURATION}s")
        return DEFAULT_DURATION


def _ffmpeg(cmd: List[str], errmsg: str):
    logger.debug("FFmpeg ▶ " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="ignore").strip()
        logger.error(f"{errmsg}: {err}")
        raise


def _prepare_scene(job_dir: str, idx: int, scene: Dict[str, str]):
    seg_dir = os.path.join(job_dir, f"{SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)
    img = os.path.join(seg_dir, f"image_{idx}{os.path.splitext(scene['image_url'])[1]}")
    aud = os.path.join(seg_dir, f"audio_{idx}.mp3")
    download_file(scene["image_url"], img)
    download_file(scene["audio_url"], aud)
    return img, aud


def _render_segment(
    img: str, aud: str, out: str,
    zoom: Optional[Dict[str, Any]]
):
    dur = _probe_duration(aud)
    if zoom and zoom.get("type") != "None":
        spd = zoom.get("speed", 1) / 10.0
        filt = f"zoompan=z='min(zoom+{spd},1.5)':d={int(dur*25)}:s=1920x1080"
        tmp = out.replace(".mp4", "_z.mp4")
        _ffmpeg(
            ["ffmpeg","-y","-loop","1","-i",img,"-filter_complex",filt,
             "-t",str(dur),"-c:v","libx264","-pix_fmt","yuv420p", tmp],
            f"zoom failed for {img}"
        )
        _ffmpeg(
            ["ffmpeg","-y","-i",tmp,"-i",aud,
             "-c:v","copy","-c:a","aac","-shortest", out],
            f"merge zoom+audio failed for {img}"
        )
        os.remove(tmp)
    else:
        _ffmpeg(
            ["ffmpeg","-y","-loop","1","-i",img,"-i",aud,
             "-c:v","libx264","-tune","stillimage","-c:a","aac","-b:a","192k",
             "-pix_fmt","yuv420p","-shortest","-t",str(dur), out],
            f"static segment fail for {img}"
        )


def _concat(segments: List[str], out: str):
    lst = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt")
    for p in segments:
        lst.write(f"file '{os.path.abspath(p)}'\n")
    lst.close()
    try:
        _ffmpeg(
            ["ffmpeg","-y","-f","concat","-safe","0","-i",lst.name,"-c","copy",out],
            "concat failed"
        )
    finally:
        os.remove(lst.name)


def _add_bgm(video: str, bgm_url: str, out: str):
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    download_file(bgm_url, tmp.name)
    dur = _probe_duration(video)
    _ffmpeg(
        ["ffmpeg","-y","-i",video,"-stream_loop","-1","-i",tmp.name,
         "-filter_complex",f"[1:a]volume=0.2,aloop=loop=-1:size=2e+09,atrim=end={dur}[bgm];"
                           "[0:a][bgm]amix=inputs=2:duration=first[a]",
         "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-shortest",out],
        "bgm merge failed"
    )
    os.remove(tmp.name)


def _notify(webhook: Optional[str], job: str, status: str, data: dict=None, error: str=None):
    if not webhook:
        return
    payload = {"job_id": job, "status": status}
    if data:  payload["data"]  = data
    if error: payload["error"] = error
    try:
        r = requests.post(webhook, json=payload, timeout=5)
        if r.status_code // 100 != 2:
            logger.warning(f"Webhook {status} → {r.status_code}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, str]],
    title: Optional[str],
    webhook_url: Optional[str],
    content_id: Optional[str],
    advanced: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"final_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    segments: List[str] = []

    zoom_cfg = (advanced or {}).get("zoom", {})
    bgm_url  = (advanced or {}).get("background_music", {}).get("url") \
               or DEFAULT_BACKGROUND_MUSIC_URL

    try:
        logger.info(f"Job {job_id}: rendering {len(scenes)} scenes")
        for i, sc in enumerate(scenes):
            img, aud = _prepare_scene(job_dir, i, sc)
            out = os.path.join(job_dir, f"{SEGMENT_PREFIX}{i}.mp4")
            _render_segment(img, aud, out, zoom_cfg)
            segments.append(out)

        temp = os.path.join(job_dir, f"{job_id}_temp.mp4")
        _concat(segments, temp)

        if bgm_url:
            bgm_out = temp.replace("_temp", "_bgm")
            _add_bgm(temp, bgm_url, bgm_out)
            os.replace(bgm_out, temp)

        s3_key = f"videos/{job_id}.mp4"
        s3_url = upload_to_s3(temp, s3_key)

        result = {
            "status":    "completed",
            "video_url": s3_url,
            "title":     title,
            "id":        content_id
        }
        _notify(webhook_url, job_id, "completed", data=result)
        return result

    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        _notify(webhook_url, job_id, "failed", error=str(e))
        return {"status":"failed", "error": str(e)}

    finally:
        shutil.rmtree(job_dir, ignore_errors=True)