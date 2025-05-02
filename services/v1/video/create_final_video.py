# services/v1/video/create_final_video.py
import os
import shutil
import logging
import subprocess
import requests
import tempfile
import urllib.parse
import time
from typing import List, Dict, Optional, Any

from config import (
    LOCAL_STORAGE_PATH,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_REGION,
)
from services.s3_toolkit import upload_to_s3
from services.caption_video import process_captioning
from services.airtable_client import AirtableClient

logger = logging.getLogger(__name__)

# ====== Configurações Padrão ======
DEFAULT_STORAGE_PREFIX = "final_video_"
DEFAULT_SEGMENT_PREFIX = "segment_"
DEFAULT_DURATION_FALLBACK = 10.0  # duração padrão ao não obter duração real
DEFAULT_VIDEO_OPTIONS: Dict[str, Dict[str, Any]] = {
    "overlay": {"url": None, "position": "Topo", "opacity": 100},
    "zoom": {"type": "Nenhum", "speed": 5},
    "background_music": {"url": None, "volume": 20},
    "captions": {"enabled": False, "type": "srt", "style": "Padrão"},
    "transitions": {"type": "Fade", "duration": 1.0},
}
# ===================================

def _download_file(url: str, dest_path: str) -> None:
    """
    Baixa uma URL e grava em disco no caminho indicado.
    """
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Downloaded {url} → {dest_path}")


def _get_media_duration(path: str) -> float:
    """
    Retorna a duração em segundos de um arquivo multimídia via ffprobe.
    Usa fallback se falhar.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        if val.replace('.', '', 1).isdigit():
            return float(val)
        return DEFAULT_DURATION_FALLBACK
    except Exception:
        logger.warning(
            f"Could not get duration for {path}, using fallback "
            f"{DEFAULT_DURATION_FALLBACK}s"
        )
        return DEFAULT_DURATION_FALLBACK


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    """
    Executa comando ffmpeg, lança erro em caso de falha.
    """
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _merge_options(
    defaults: Dict[str, Dict[str, Any]],
    overrides: Optional[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Mescla opções avançadas do request com as defaults.
    """
    opts = {k: v.copy() for k, v in defaults.items()}
    if not overrides:
        return opts
    for k, v in overrides.items():
        if k in opts and isinstance(v, dict):
            opts[k].update(v)
    logger.info("Merged advanced options: %s", opts)
    return opts


def _prepare_scene_files(job_dir: str, idx: int, scene: Dict[str, Any]) -> (str, str):
    """
    Cria pasta do segmento e baixa image + audio.
    Retorna caminhos (image_path, audio_path).
    """
    seg_dir = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)
    
    def get_filename(url):
        return os.path.basename(urllib.parse.urlparse(url).path)
        
    img_path = os.path.join(seg_dir, get_filename(scene["image_url"]))
    aud_path = os.path.join(seg_dir, get_filename(scene["audio_url"]))
    _download_file(scene["image_url"], img_path)
    _download_file(scene["audio_url"], aud_path)
    return img_path, aud_path


def _send_webhook_notification(
    webhook_url: Optional[str], job_id: str, status: str,
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> None:
    """
    Envia payload ao webhook configurado (status updates).
    """
    if not webhook_url:
        logger.debug("No webhook URL for job %s", job_id)
        return
    payload = {"job_id": job_id, "status": status}
    if data:
        payload["data"] = data
    if error_message:
        payload["error"] = error_message
    try:
        resp = requests.post(webhook_url, json=payload)
        logger.info("Webhook status %s for job %s", resp.status_code, job_id)
    except Exception as e:
        logger.error("Webhook error for job %s: %s", job_id, e)


def _create_segment_from_image(image_path: str, audio_path: str, out_path: str) -> None:
    """
    Cria vídeo estático da imagem com áudio.
    Duração igual à do áudio.
    """
    dur = _get_media_duration(audio_path)
    logger.info("Creating static segment %s (dur=%.2fs)", out_path, dur)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", "-t", str(dur), out_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error creating static segment {out_path}")
    except Exception:
        logger.info("Fallback static for %s", out_path)
        fb = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            out_path
        ]
        _run_ffmpeg(fb, f"Fallback static error {out_path}")


def _apply_zoom_effect(
    image_path: str,
    output_path: str,
    zoom_type: str,
    zoom_speed: int,
    audio_path: str
) -> None:
    """
    Cria vídeo com efeito zoom baseado na duração do áudio.
    """
    dur = _get_media_duration(audio_path)
    speed = max(1, min(20, zoom_speed)) / 10.0
    logger.info("Applying zoom %s speed=%d", zoom_type, zoom_speed)
    if zoom_type == "Nenhum":
        _create_segment_from_image(image_path, audio_path, output_path)
        return
    # define filter_complex usando dur
    if zoom_type == "Zoom In":
        zoom_factor = speed / 100
        filt = f"zoompan=z='min(zoom+{zoom_factor},1.5)':d={int(dur*25)}:s=1920x1080"
    elif zoom_type == "Zoom Out":
        zoom_factor = speed / 100
        filt = (
            f"zoompan=z='if(eq(on,1),1.5,max(1.5-{zoom_factor}*on/d,1))'"
            f":d={int(dur*25)}:s=1920x1080"
        )
    else:
        zoom_factor = speed / 100
        filt = (
            f"zoompan=z='min(max(zoom,pzoom)+{zoom_factor},1.5)'"
            f":d={int(dur*25)}:s=1920x1080"
        )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-filter_complex", filt,
        "-t", str(dur),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-shortest", output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error applying zoom effect to {output_path}")
    except Exception:
        _create_segment_from_image(image_path, audio_path, output_path)


def _create_segment_with_audio(
    video_path: str,
    audio_path: str,
    output_path: str
) -> None:
    """
    Substitui trilha de vídeo existente por áudio fornecido.
    """
    logger.info("Merging %s + %s → %s", video_path, audio_path, output_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", output_path
    ]
    _run_ffmpeg(cmd, f"Error combining audio to {video_path}")


def _apply_overlay(
    video_path: str,
    overlay_url: str,
    output_path: str,
    position: str = "Topo",
    opacity: int = 100
) -> None:
    """
    Aplica overlay (watermark) ao vídeo inteiro.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    _download_file(overlay_url, tmp.name)
    pos_map = {
        "Topo": "x=(main_w-overlay_w)/2:y=10",
        "Centro": "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2",
        "Base": "x=(main_w-overlay_w)/2:y=main_h-overlay_h-10"
    }
    pos = pos_map.get(position, pos_map["Topo"])
    alpha = max(0, min(100, opacity)) / 100.0
    logger.info("Applying overlay %s opacity=%d", overlay_url, opacity)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", tmp.name,
        "-filter_complex",
        f"[1:v]format=rgba,colorchannelmixer=a={alpha}[ovl];"
        f"[0:v][ovl]overlay={pos}",
        "-c:a", "copy", output_path
    ]
    _run_ffmpeg(cmd, f"Error applying overlay to {video_path}")
    os.remove(tmp.name)


def _concatenate_with_transitions(
    segment_files: List[str],
    output_path: str,
    trans_type: str,
    trans_dur: float
) -> None:
    """
    Concatenação avançada com transições (xfade + acrossfade).
    """
    inputs, fc = [], []
    for i, seg in enumerate(segment_files):
        inputs += ["-i", seg]
        filter_str = (
            f"[{i}:v]setpts=PTS-STARTPTS[v{i}];"
            f"[{i}:a]asetpts=PTS-STARTPTS[a{i}];"
        )
        fc.append(filter_str)
    for i in range(len(segment_files)-1):
        dur = _get_media_duration(segment_files[i])
        off = max(0, dur-trans_dur)
        xf = f"xfade=transition=fade:duration={trans_dur}:offset={off}"
        fc.append(f"[v{i}][v{i+1}]{xf}[vt{i}];")
        fc.append(f"[a{i}][a{i+1}]acrossfade=d={trans_dur}[at{i}];")
    last = len(segment_files)-2
    filter_complex = "".join(fc) + f"[vt{last}][at{last}]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-c:a", "aac", output_path
    ]
    try:
        _run_ffmpeg(
            cmd, f"Error concatenating with transitions to {output_path}"
        )
    except Exception:
        logger.info("Fallback simple concat")
        listf = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        )
        for seg in segment_files:
            listf.write(f"file '{os.path.abspath(seg)}'\n")
        listf.close()
        fb = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
            "-c", "copy", output_path
        ]
        _run_ffmpeg(fb, f"Error fallback concat {output_path}")
        os.remove(listf.name)


def _add_background_music(
    video_path: str,
    music_url: str,
    output_path: str,
    volume: int = 20
) -> None:
    """
    Adiciona música de fundo em loop, mixando com áudio original.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    _download_file(music_url, tmp.name)
    dur = _get_media_duration(video_path)
    vol = max(0, min(100, volume)) / 100.0
    logger.info("Adding background music %s vol=%.2f", music_url, vol)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1",
        "-i", tmp.name,
        "-filter_complex",
        f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=end={dur}[bgm];"
        "[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest", output_path
    ]
    _run_ffmpeg(cmd, f"Error adding BGM to {output_path}")
    os.remove(tmp.name)


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, Any]],
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content_id: Optional[str] = None,
    advanced_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Pipeline completo:
    1) Download cenas
    2) Zoom / segment creation
    3) Concat (+ transições)
    4) Música
    5) Legendas
    6) Overlay global
    7) Upload S3 + webhook
    Duration of each scene/zoom == audio duration.
    """
    logger.info(f"Job {job_id}: start pipeline count={len(scenes)} scenes")
    
    # Initialize Airtable client for job logging
    airtable = AirtableClient()
    
    # Create initial job log entry
    log_entry = airtable.create_job_log(
        job_id=job_id,
        job_type="Video_Generation",
        service_name="create_final_video",
        related_content_id=content_id,
        metadata={
            "scene_count": len(scenes),
            "title": title,
            "options": advanced_options
        }
    )
    
    log_record_id = log_entry.get("id")
    start_time = time.time()
    
    opts = _merge_options(DEFAULT_VIDEO_OPTIONS, advanced_options)
    job_dir = os.path.join(
        LOCAL_STORAGE_PATH, f"{DEFAULT_STORAGE_PREFIX}{job_id}"
    )
    os.makedirs(job_dir, exist_ok=True)
    segment_files: List[str] = []

    try:
        # Update job to running status
        airtable.update_job_status(
            log_record_id=log_record_id,
            status="Running",
            log_message=f"Starting video generation with {len(scenes)} scenes"
        )
        
        # 1) processar cenas
        for idx, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: processing scene {idx+1}/{len(scenes)}")
            airtable.add_log_message(
                log_record_id=log_record_id,
                message=f"Processing scene {idx+1}/{len(scenes)}"
            )
            
            img, aud = _prepare_scene_files(job_dir, idx, scene)
            seg_out = os.path.join(
                job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}.mp4"
            )

            z = scene.get("options", {}).get("zoom", {})
            zt = z.get("type", opts["zoom"]["type"]) 
            zs = z.get("speed", opts["zoom"]["speed"]) 

            if zt != "Nenhum":
                tmpz = os.path.join(job_dir, f"zoom_{idx}.mp4")
                _apply_zoom_effect(img, tmpz, zt, zs, aud)
                _create_segment_with_audio(tmpz, aud, seg_out)
            else:
                _create_segment_from_image(img, aud, seg_out)

            logger.info(f"Job {job_id}: scene {idx} ready → {seg_out}")
            segment_files.append(seg_out)

        # 2) concat
        airtable.add_log_message(
            log_record_id=log_record_id,
            message="Concatenating video segments"
        )
        
        temp_vid = os.path.join(job_dir, f"{job_id}_temp.mp4")
        ttype = opts["transitions"]["type"]
        tdur = opts["transitions"]["duration"]
        
        if ttype == "Corte Seco":
            txt = os.path.join(job_dir, "concat.txt")
            with open(txt, "w") as f:
                for sf in segment_files:
                    f.write(f"file '{os.path.abspath(sf)}'\n")
            _run_ffmpeg(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", txt, 
                 "-c", "copy", temp_vid],
                f"Error simple concat {job_id}"
            )
        else:
            _concatenate_with_transitions(segment_files, temp_vid, ttype, tdur)
        logger.info(f"Job {job_id}: concat done → {temp_vid}")

        # 3) música
        bg_url = opts["background_music"]["url"]
        if bg_url:
            airtable.add_log_message(
                log_record_id=log_record_id,
                message="Adding background music"
            )
            
            vid_bgm = os.path.join(job_dir, f"{job_id}_bgm.mp4")
            _add_background_music(
                temp_vid, bg_url, vid_bgm, 
                opts["background_music"]["volume"]
            )
            shutil.move(vid_bgm, temp_vid)
            logger.info(f"Job {job_id}: background music added")

        # 4) legendas
        caps = opts["captions"]
        if caps.get("enabled"):
            airtable.add_log_message(
                log_record_id=log_record_id,
                message="Generating video captions"
            )
            
            text_all = "\n".join(
                s.get("text", "") for s in scenes if s.get("text")
            )
            if text_all:
                try:
                    capf = process_captioning(
                        temp_vid, text_all, caps.get("type", "srt"), [], job_id
                    )
                    if os.path.exists(capf):
                        shutil.move(capf, temp_vid)
                    logger.info(f"Job {job_id}: captions applied")
                except Exception as e:
                    err_msg = f"Caption error: {str(e)}"
                    logger.warning(f"Job {job_id}: caption error {e}")
                    airtable.add_log_message(
                        log_record_id=log_record_id,
                        message=err_msg
                    )

        # 5) overlay global
        ov = opts["overlay"]
        if ov.get("url"):
            airtable.add_log_message(
                log_record_id=log_record_id,
                message="Applying video overlay/watermark"
            )
            
            vid_ov = os.path.join(job_dir, f"{job_id}_ov.mp4")
            _apply_overlay(
                temp_vid, ov["url"], vid_ov, ov["position"], ov["opacity"]
            )
            shutil.move(vid_ov, temp_vid)
            logger.info(f"Job {job_id}: overlay applied")

        # 6) upload
        airtable.add_log_message(
            log_record_id=log_record_id,
            message="Uploading final video to S3"
        )
        
        s3_key = f"final_videos/{job_id}_final.mp4"
        s3_url = upload_to_s3(
            temp_vid, s3_key,
            S3_BUCKET_NAME, S3_ENDPOINT_URL,
            S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION
        )
        logger.info(f"Job {job_id}: uploaded → {s3_url}")

        # Calculate processing duration
        duration = time.time() - start_time
        
        # Update job to completed status
        airtable.update_job_status(
            log_record_id=log_record_id,
            status="Completed",
            log_message=f"Video generation completed successfully. URL: {s3_url}",
            duration_seconds=int(duration),
            metadata_updates={
                "results": {
                    "video_url": s3_url,
                    "title": title,
                    "processing_time": round(duration, 2)
                }
            }
        )
        
        shutil.rmtree(job_dir, ignore_errors=True)
        res = {
            "status": "completed",
            "video_url": s3_url,
            "title": title,
            "id": content_id
        }
        _send_webhook_notification(webhook_url, job_id, "completed", data=res)
        return res

    except Exception as e:
        logger.exception(f"Job {job_id}: pipeline failed: {e}")
        
        # Update job to failed status
        airtable.update_job_status(
            log_record_id=log_record_id,
            status="Failed",
            log_message=f"Video generation failed: {str(e)}",
            error_details=str(e),
            duration_seconds=int(time.time() - start_time)
        )
        
        _send_webhook_notification(webhook_url, job_id, "failed", error_message=str(e))
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"status": "failed", "error": str(e)}