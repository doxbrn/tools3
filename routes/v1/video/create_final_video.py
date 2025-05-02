import os
import shutil
import logging
import subprocess
import requests
import tempfile
import urllib.parse
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

logger = logging.getLogger(__name__)

# ====== Configurações Padrão ======
DEFAULT_STORAGE_PREFIX    = "final_video_"
DEFAULT_SEGMENT_PREFIX    = "segment_"
DEFAULT_DURATION_FALLBACK = 10.0
DEFAULT_VIDEO_OPTIONS: Dict[str, Dict[str, Any]] = {
    "overlay":          {"url": None, "position": "Topo", "opacity": 100},
    "zoom":             {"type": "Nenhum", "speed": 5},
    "background_music": {"url": None, "volume": 20},
    "captions":         {"enabled": False, "style": "Padrão"},
    "transitions":      {"type": "Fade", "duration": 1.0},
}
# ===================================


def _download_file(url: str, dest_path: str) -> None:
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Downloaded {url} -> {dest_path}")


def _get_media_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = result.stdout.strip()
        if val.replace('.', '', 1).isdigit():
            return float(val)
    except Exception:
        logger.warning(f"Could not get duration for {path}; using fallback {DEFAULT_DURATION_FALLBACK}s")
    return DEFAULT_DURATION_FALLBACK


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    logger.debug("FFmpeg cmd: " + ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"{err_msg}: {e.stderr}")
        raise


def _merge_options(defaults: Dict[str, Dict[str, Any]], overrides: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result = {k: v.copy() for k, v in defaults.items()}
    if not overrides:
        return result
    for k, v in overrides.items():
        if k in result and isinstance(v, dict):
            result[k].update(v)
    logger.info("Merged advanced options")
    return result


def _prepare_scene_files(job_dir: str, idx: int, scene: Dict[str, Any]) -> (str, str):
    seg_dir = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)

    def fn(u): return os.path.basename(urllib.parse.urlparse(u).path)
    img_path = os.path.join(seg_dir, fn(scene['image_url']))
    aud_path = os.path.join(seg_dir, fn(scene['audio_url']))

    _download_file(scene['image_url'], img_path)
    _download_file(scene['audio_url'], aud_path)

    return img_path, aud_path


def _send_webhook_notification(
    webhook_url: Optional[str], job_id: str,
    status: str, data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> None:
    if not webhook_url:
        logger.debug(f"Job {job_id}: no webhook URL, skipping notification")
        return
    payload = {"job_id": job_id, "status": status}
    if data:
        payload['data'] = data
    if error_message:
        payload['error'] = error_message
    try:
        resp = requests.post(webhook_url, json=payload)
        logger.info(f"Job {job_id}: webhook status {resp.status_code}")
    except Exception as e:
        logger.error(f"Job {job_id}: webhook error {e}")


def _create_segment_from_image(image_path: str, audio_path: str, out_path: str) -> None:
    dur = _get_media_duration(audio_path)
    logger.info(f"Creating static segment {out_path} (duration={dur}s)")
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", "-t", str(dur), out_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error creating segment from {image_path}")
    except Exception:
        logger.info(f"Fallback static segment {out_path}")
        fb = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path
        ]
        _run_ffmpeg(fb, f"Error fallback static for {out_path}")


def _apply_zoom_effect(
    image_path: str, output_path: str,
    zoom_type: str, zoom_speed: int, audio_path: str
) -> None:
    dur = _get_media_duration(audio_path)
    speed = max(1, min(20, zoom_speed)) / 10.0
    logger.info(f"Applying zoom '{zoom_type}' speed {zoom_speed} to {image_path}")

    if zoom_type == "Nenhum":
        _create_segment_from_image(image_path, audio_path, output_path)
        return

    if zoom_type == "Zoom In":
        filt = f"zoompan=z='min(zoom+{speed/100},1.5)':d={int(dur*25)}:s=1920x1080"
    elif zoom_type == "Zoom Out":
        filt = f"zoompan=z='if(eq(on,1),1.5,max(1.5-{speed/100}*on/d,1))':d={int(dur*25)}:s=1920x1080"
    else:
        filt = f"zoompan=z='min(max(zoom,pzoom)+{speed/100},1.5)':d={int(dur*25)}:s=1920x1080"

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-filter_complex", filt,
        "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Error zoom {image_path}")
    except Exception:
        logger.info(f"Fallback no-zoom for {output_path}")
        _create_segment_from_image(image_path, audio_path, output_path)


def _create_segment_with_audio(video_path: str, audio_path: str, out_path: str) -> None:
    logger.info(f"Combining {video_path} + {audio_path} -> {out_path}")
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest", out_path
    ]
    _run_ffmpeg(cmd, f"Error combining audio in {video_path}")


def _concatenate_with_transitions(
    files: List[str], out_path: str, trans_type: str, trans_dur: float
) -> None:
    logger.info(f"Concatenating {len(files)} segments with transition '{trans_type}' ({trans_dur}s)")
    inputs = []
    fc = []
    for i, fpath in enumerate(files):
        inputs += ["-i", fpath]
        fc.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}];")

    for i in range(len(files)-1):
        dur = _get_media_duration(files[i])
        off = max(0, dur-trans_dur)
        tfilter = f"xfade=transition=fade:duration={trans_dur}:offset={off}"
        fc.append(f"[v{i}][v{i+1}]{tfilter}[vt{i}];")
        fc.append(f"[a{i}][a{i+1}]acrossfade=d={trans_dur}[at{i}];")

    last = len(files)-2
    filter_complex = "".join(fc)+f"[vt{last}][at{last}]"
    cmd = ["ffmpeg","-y"]+inputs+["-filter_complex",filter_complex,"-c:v","libx264","-c:a","aac",out_path]
    try:
        _run_ffmpeg(cmd, f"Error concatenating to {out_path}")
    except Exception:
        logger.info(f"Fallback simple concat to {out_path}")
        txt = tempfile.NamedTemporaryFile(mode="w",delete=False,suffix=".txt")
        for p in files:
            txt.write(f"file '{os.path.abspath(p)}'\n")
        txt.close()
        fb = ["ffmpeg","-y","-f","concat","-safe","0","-i",txt.name,"-c","copy",out_path]
        _run_ffmpeg(fb, f"Error fallback concat {out_path}")
        os.unlink(txt.name)


def _add_background_music(
    video_path: str, music_url: str, out_path: str, volume: int
) -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3",delete=False)
    tmp.close()
    _download_file(music_url, tmp.name)
    dur = _get_media_duration(video_path)
    vol = max(0,min(100,volume))/100.0
    logger.info(f"Adding background music ({volume}%) -> {out_path}")
    cmd = [
        "ffmpeg","-y","-i",video_path,"-stream_loop","-1","-i",tmp.name,
        "-filter_complex",
        f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=end={dur}[bgm];"+
        "[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map","0:v","-map","[aout]","-c:v","copy","-c:a","aac","-shortest",out_path
    ]
    _run_ffmpeg(cmd, f"Error adding BGM to {out_path}")
    os.remove(tmp.name)


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, Any]],
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content_id: Optional[str] = None,
    advanced_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    logger.info(f"Job {job_id}: iniciando pipeline com {len(scenes)} cenas (title={title})")
    opts = _merge_options(DEFAULT_VIDEO_OPTIONS, advanced_options)
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"{DEFAULT_STORAGE_PREFIX}{job_id}")
    os.makedirs(job_dir, exist_ok=True)

    segment_files: List[str] = []
    try:
        # Processar cenas
        for idx, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: processando cena {idx+1}/{len(scenes)}")
            img, aud = _prepare_scene_files(job_dir, idx, scene)
            seg_out = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}.mp4")

            zopt = scene.get("options", {}).get("zoom", {})
            zt, zs = zopt.get("type", opts["zoom"]["type"]), zopt.get("speed", opts["zoom"]["speed"])
            logger.info(f"Job {job_id}: zoom={zt}, speed={zs}")

            if zt != "Nenhum":
                tmpz = os.path.join(job_dir, f"zoom_{idx}.mp4")
                _apply_zoom_effect(img, tmpz, zt, zs, aud)
                _create_segment_with_audio(tmpz, aud, seg_out)
            else:
                _create_segment_from_image(img, aud, seg_out)

            logger.info(f"Job {job_id}: segmento pronto {seg_out}")
            segment_files.append(seg_out)

        # Concatenação
        final_temp = os.path.join(job_dir, f"{job_id}_temp.mp4")
        ttype, tdur = opts["transitions"]["type"], opts["transitions"]["duration"]
        logger.info(f"Job {job_id}: concatenando com transição {ttype} ({tdur}s)")
        if ttype == "Corte Seco":
            txt = os.path.join(job_dir, "concat.txt")
            with open(txt, "w") as f:
                for p in segment_files:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            _run_ffmpeg(
                ["ffmpeg","-y","-f","concat","-safe","0","-i",txt,"-c","copy",final_temp],
                f"Erro concat simples job {job_id}"
            )
        else:
            _concatenate_with_transitions(segment_files, final_temp, ttype, tdur)
        logger.info(f"Job {job_id}: concat concluído -> {final_temp}")

        # Música de fundo
        bg = opts["background_music"]["url"]
        if bg:
            outbg = os.path.join(job_dir, f"{job_id}_bgm.mp4")
            _add_background_music(final_temp, bg, outbg, opts["background_music"]["volume"])
            shutil.move(outbg, final_temp)
            logger.info(f"Job {job_id}: música de fundo aplicada")

        # Legendas
        caps = opts["captions"]
        if caps.get("enabled"):
            logger.info(f"Job {job_id}: adicionando legendas (style={caps['style']})")
            text_all = "\n".join(s.get("text","") for s in scenes if s.get("text"))
            if text_all:
                try:
                    cap_file = process_captioning(final_temp, text_all, caps.get("type","srt"), [], job_id)
                    if os.path.exists(cap_file):
                        shutil.move(cap_file, final_temp)
                    logger.info(f"Job {job_id}: legendas aplicadas")
                except Exception as e:
                    logger.warning(f"Job {job_id}: erro em legendas: {e}")

        # Overlay global
        ov = opts["overlay"]
        if ov.get("url"):
            outov = os.path.join(job_dir, f"{job_id}_ov.mp4")
            logger.info(f"Job {job_id}: aplicando overlay global")
            _apply_overlay(final_temp, ov["url"], outov, ov["position"], ov["opacity"])
            shutil.move(outov, final_temp)
            logger.info(f"Job {job_id}: overlay aplicado")

        # Upload
        key = f"final_videos/{job_id}_final.mp4"
        logger.info(f"Job {job_id}: enviando {final_temp} para S3 as {key}")
        s3url = upload_to_s3(final_temp, key,
                              S3_BUCKET_NAME, S3_ENDPOINT_URL,
                              S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION)
        logger.info(f"Job {job_id}: upload concluído -> {s3url}")

        shutil.rmtree(job_dir, ignore_errors=True)
        res = {"status":"completed","video_url":s3url,"title":title,"id":content_id}
        _send_webhook_notification(webhook_url, job_id, "completed", data=res)
        return res

    except Exception as e:
        logger.exception(f"Job {job_id}: falha geral: {e}")
        _send_webhook_notification(webhook_url, job_id, "failed", error_message=str(e))
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"status":"failed","error":str(e)}
