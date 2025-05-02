import os
import shutil
import logging
import subprocess
import requests
import tempfile
from typing import List, Dict, Optional, Tuple, Any

from config import (
    LOCAL_STORAGE_PATH,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_REGION
)
from services.file_management import download_file
from services.s3_toolkit import upload_to_s3
from services.caption_video import process_captioning

# ====== Configurações Padrão ======
DEFAULT_STORAGE_PREFIX = "final_video_"
DEFAULT_SEGMENT_PREFIX = "segment_"
DEFAULT_DURATION_FALLBACK = 10.0
DEFAULT_VIDEO_OPTIONS: Dict[str, Dict[str, Any]] = {
    "overlay":          {"url": None, "position": "Topo", "opacity": 100},
    "zoom":             {"type": "Nenhum", "speed": 5},
    "background_music": {"url": None, "volume": 20},
    "captions":         {"enabled": False, "style": "Padrão"},
    "transitions":      {"type": "Fade", "duration": 1.0},
}
# ===================================

logger = logging.getLogger(__name__)


def _get_media_duration(path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if output and output.replace('.', '', 1).isdigit():
            return float(output)
    except Exception:
        logger.warning(f"Could not get duration for {path}, using fallback {DEFAULT_DURATION_FALLBACK}s")
    return DEFAULT_DURATION_FALLBACK


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"{err_msg}: {e.stderr}")
        raise


def _merge_options(defaults: Dict[str, Dict[str, Any]],
                   overrides: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Dict[str, Any]]:
    result = {k: v.copy() for k, v in defaults.items()}
    if not overrides:
        return result
    for key, override in overrides.items():
        if key in result and isinstance(override, dict):
            result[key].update(override)
    return result


def _prepare_scene_files(job_dir: str, idx: int, scene: Dict[str, Any]) -> Tuple[str, str, str]:
    seg_dir = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)
    img_path = os.path.join(seg_dir, f"image_{idx}.jpg")
    aud_path = os.path.join(seg_dir, f"audio_{idx}.mp3")
    download_file(scene.get("image_url"), img_path)
    download_file(scene.get("audio_url"), aud_path)
    return img_path, aud_path, seg_dir


def _send_webhook_notification(
    webhook_url: Optional[str],
    job_id: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> None:
    if not webhook_url:
        logger.info(f"Job {job_id}: No webhook URL provided, skipping notification.")
        return
    payload: Dict[str, Any] = {"job_id": job_id, "status": status}
    if data:
        payload["data"] = data
    if error_message:
        payload["error"] = error_message
    try:
        resp = requests.post(webhook_url, json=payload)
        if 200 <= resp.status_code < 300:
            logger.info(f"Job {job_id}: Webhook notification sent successfully.")
        else:
            logger.warning(f"Job {job_id}: Webhook failed with status {resp.status_code}.")
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to send webhook: {e}")


def _create_segment_from_image(
    image_path: str,
    audio_path: str,
    output_path: str
) -> None:
    duration = _get_media_duration(audio_path)
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', image_path,
        '-i', audio_path,
        '-c:v', 'libx264', '-tune', 'stillimage',
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest', '-t', str(duration),
        output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error creating segment from image {output_path}")
    except Exception:
        fallback = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', image_path,
            '-t', str(duration),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
        _run_ffmpeg(fallback, f"Fallback error creating static segment {output_path}")


def _apply_zoom_effect(
    image_path: str,
    output_path: str,
    zoom_type: str,
    zoom_speed: int,
    audio_path: str
) -> None:
    duration = _get_media_duration(audio_path)
    speed = max(1, min(20, zoom_speed)) / 10.0
    if zoom_type == "Zoom In":
        filter_str = f"zoompan=z='min(zoom+{speed/100},1.5)':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Zoom Out":
        filter_str = f"zoompan=z='if(eq(on,1),1.5,max(1.5-{speed/100}*on/d,1))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Pan Horizontal":
        filter_str = f"zoompan=z=1.2:x='min(in_w*(1-1/zoom)*(on/{int(duration*25)}),in_w*(1-1/zoom))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Pan Vertical":
        filter_str = f"zoompan=z=1.2:y='min(in_h*(1-1/zoom)*(on/{int(duration*25)}),in_h*(1-1/zoom))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Ken Burns":
        filter_str = f"zoompan=z='min(max(zoom,pzoom)+{speed/100},1.5)':d={int(duration*25)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080"
    else:
        filter_str = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', image_path,
        '-filter_complex', filter_str,
        '-t', str(duration),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-shortest', output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error applying zoom effect to {output_path}")
    except Exception:
        _run_ffmpeg([
            'ffmpeg', '-y',
            '-loop', '1', '-i', image_path,
            '-t', str(duration),
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            output_path
        ], f"Fallback static zoom for {output_path}")


def _create_segment_with_audio(
    video_path: str,
    audio_path: str,
    output_path: str
) -> None:
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac',
        '-map', '0:v:0', '-map', '1:a:0',
        '-shortest', output_path
    ]
    _run_ffmpeg(cmd, f"Error combining audio with {video_path}")


def _apply_overlay(
    video_path: str,
    overlay_url: str,
    output_path: str,
    position: str = "Topo",
    opacity: int = 100
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        download_file(overlay_url, tmp.name)
        overlay_path = tmp.name
    pos_map = {
        "Topo":   "x=(main_w-overlay_w)/2:y=10",
        "Centro": "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2",
        "Base":   "x=(main_w-overlay_w)/2:y=main_h-overlay_h-10"
    }
    pos_str = pos_map.get(position, pos_map["Topo"])
    alpha = max(0, min(100, opacity)) / 100.0
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', overlay_path,
        '-filter_complex', f"[1:v]format=rgba,colorchannelmixer=a={alpha}[ovl];[0:v][ovl]overlay={pos_str}",
        '-c:a', 'copy', output_path
    ]
    _run_ffmpeg(cmd, f"Error applying overlay on {video_path}")
    os.remove(overlay_path)


def _concatenate_with_transitions(
    segment_files: List[str],
    output_path: str,
    trans_type: str,
    trans_dur: float
) -> None:
    inputs = []
    filter_parts = []
    for idx, seg in enumerate(segment_files):
        inputs += ['-i', seg]
        filter_parts.append(f"[{idx}:v]setpts=PTS-STARTPTS[v{idx}];[{idx}:a]asetpts=PTS-STARTPTS[a{idx}];")
    for i in range(len(segment_files)-1):
        dur = _get_media_duration(segment_files[i])
        out_time = max(0, dur - trans_dur)
        transition = f"xfade=transition=fade:duration={trans_dur}:offset={out_time}"
        filter_parts.append(f"[v{i}][v{i+1}]{transition}[v_t{i}];")
        filter_parts.append(f"[a{i}][a{i+1}]acrossfade=d={trans_dur}[a_t{i}];")
    last = len(segment_files) - 2
    filter_complex = ''.join(filter_parts) + f"[v_t{last}][a_t{last}]"
    cmd = ['ffmpeg', '-y'] + inputs + [
        '-filter_complex', filter_complex,
        '-c:v', 'libx264', '-c:a', 'aac', output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error concatenating with transitions to {output_path}")
    except Exception:
        list_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        for seg in segment_files:
            list_file.write(f"file '{os.path.abspath(seg)}'\n")
        list_file.close()
        fallback = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file.name, '-c', 'copy', output_path
        ]
        _run_ffmpeg(fallback, f"Fallback concat to {output_path}")
        os.unlink(list_file.name)


def _add_background_music(
    video_path: str,
    music_url: str,
    output_path: str,
    volume: int = 20
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        download_file(music_url, tmp.name)
        music_path = tmp.name
    vid_dur = _get_media_duration(video_path)
    vol = max(0, min(100, volume)) / 100.0
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-stream_loop', '-1', '-i', music_path,
        '-filter_complex', f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=end={vid_dur}[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
        '-map', '0:v', '-map', '[aout]',
        '-c:v', 'copy', '-c:a', 'aac', '-shortest', output_path
    ]
    _run_ffmpeg(cmd, f"Error adding background music to {video_path}")
    os.remove(music_path)


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, Any]],
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content_id: Optional[str] = None,
    advanced_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    video_opts = _merge_options(DEFAULT_VIDEO_OPTIONS, advanced_options)
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"{DEFAULT_STORAGE_PREFIX}{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    segment_paths: List[str] = []
    try:
        logger.info(f"Job {job_id}: Iniciando com {len(scenes)} cenas. Title={title}")
        for idx, scene in enumerate(scenes):
            img_path, aud_path, seg_dir = _prepare_scene_files(job_dir, idx, scene)
            opts = scene.get("options", {})
            zoom_type = opts.get("zoom", {}).get("type", video_opts["zoom"]["type"])
            zoom_speed = opts.get("zoom", {}).get("speed", video_opts["zoom"]["speed"])
            segment_raw = os.path.join(seg_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}.mp4")
            if zoom_type != "Nenhum":
                zoomed = os.path.join(seg_dir, f"zoomed_{idx}.mp4")
                _apply_zoom_effect(img_path, zoomed, zoom_type, zoom_speed, aud_path)
                _create_segment_with_audio(zoomed, aud_path, segment_raw)
            else:
                _create_segment_from_image(img_path, aud_path, segment_raw)
            segment_paths.append(segment_raw)
        final_temp = os.path.join(job_dir, f"{job_id}_temp.mp4")
        trans = video_opts["transitions"]["type"]
        dur = video_opts["transitions"]["duration"]
        if trans == "Corte Seco":
            concat_list = os.path.join(job_dir, "concat_list.txt")
            with open(concat_list, 'w') as f:
                for sp in segment_paths:
                    f.write(f"file '{os.path.abspath(sp)}'\n")
            _run_ffmpeg([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', final_temp
            ], f"Error simple concat for {job_id}")
        else:
            _concatenate_with_transitions(segment_paths, final_temp, trans, dur)
        bg_url = video_opts["background_music"]["url"]
        if bg_url:
            with_music = os.path.join(job_dir, f"{job_id}_with_bgm.mp4")
            vol = video_opts["background_music"]["volume"]
            _add_background_music(final_temp, bg_url, with_music, vol)
            shutil.move(with_music, final_temp)
        caps = video_opts.get("captions", {})
        if caps.get("enabled"):
            text_all = "\n".join(s.get("text", "") for s in scenes if s.get("text"))
            if text_all:
                try:
                    captioned = process_captioning(final_temp, text_all, caps.get("type", "srt"), [], job_id)
                    if os.path.exists(captioned):
                        shutil.move(captioned, final_temp)
                except Exception as e:
                    logger.warning(f"Job {job_id}: Captioning falhou: {e}")
        # Overlay global (aplicado no vídeo completo)
        global_overlay_url = video_opts["overlay"]["url"]
        if global_overlay_url:
            overlaid_final = os.path.join(job_dir, f"{job_id}_overlay.mp4")
            pos_global = video_opts["overlay"]["position"]
            opac_global = video_opts["overlay"]["opacity"]
            _apply_overlay(final_temp, global_overlay_url, overlaid_final, pos_global, opac_global)
            shutil.move(overlaid_final, final_temp)
        s3_key = f"final_videos/{job_id}_final.mp4"
        s3_url = upload_to_s3(final_temp, s3_key,
                              S3_BUCKET_NAME, S3_ENDPOINT_URL,
                              S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION)
        shutil.rmtree(job_dir)
        result = {"status": "completed", "video_url": s3_url, "title": title, "id": content_id}
        _send_webhook_notification(webhook_url, job_id, "completed", data=result)
        return result
    except Exception as e:
        logger.exception(f"Job {job_id}: Falha geral: {e}")
        _send_webhook_notification(webhook_url, job_id, "failed", error_message=str(e))
        try:
            shutil.rmtree(job_dir)
        except Exception:
            pass
        return {"status": "failed", "error": str(e)}
