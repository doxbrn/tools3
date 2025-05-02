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
    logger.info(f"Baixando {url} para {dest_path}")
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


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
        duration = float(val) if val.replace('.', '', 1).isdigit() else DEFAULT_DURATION_FALLBACK
        logger.info(f"Duração de {path}: {duration}s")
        return duration
    except Exception:
        logger.warning(f"Não foi possível obter duração de {path}, usando fallback {DEFAULT_DURATION_FALLBACK}s")
        return DEFAULT_DURATION_FALLBACK


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    logger.info(f"Executando FFmpeg: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("FFmpeg executado com sucesso")
    except subprocess.CalledProcessError as e:
        logger.error(f"{err_msg}: {e.stderr}")
        raise


def _merge_options(defaults: Dict[str, Dict[str, Any]], overrides: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result = {k: v.copy() for k, v in defaults.items()}
    if not overrides:
        return result
    for key, override in overrides.items():
        if key in result and isinstance(override, dict):
            result[key].update(override)
            logger.info(f"Opções '{key}' mescladas: {result[key]}")
    return result


def _prepare_scene_files(job_dir: str, idx: int, scene: Dict[str, Any]) -> (str, str):
    seg_dir = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)
    logger.info(f"Preparando arquivos da cena {idx}: criando pasta {seg_dir}")

    def _file_name_from_url(u: str) -> str:
        return os.path.basename(urllib.parse.urlparse(u).path)

    img_path = os.path.join(seg_dir, _file_name_from_url(scene["image_url"]))
    aud_path = os.path.join(seg_dir, _file_name_from_url(scene["audio_url"]))

    _download_file(scene["image_url"], img_path)
    _download_file(scene["audio_url"], aud_path)

    return img_path, aud_path


def _send_webhook_notification(
    webhook_url: Optional[str], job_id: str,
    status: str, data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> None:
    if not webhook_url:
        logger.debug(f"Job {job_id}: sem webhook, pulando notificação")
        return
    payload = {"job_id": job_id, "status": status}
    if data:
        payload["data"] = data
    if error_message:
        payload["error"] = error_message

    logger.info(f"Job {job_id}: enviando payload webhook: {payload}")
    try:
        resp = requests.post(webhook_url, json=payload)
        logger.info(f"Webhook retornou {resp.status_code}")
    except Exception as e:
        logger.error(f"Falha no webhook: {e}")


def _create_segment_from_image(image_path: str, audio_path: str, out_path: str) -> None:
    logger.info(f"Criando segmento de imagem estática: {out_path}")
    dur = _get_media_duration(audio_path)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", "-t", str(dur),
        out_path
    ]
    try:
        _run_ffmpeg(cmd, f"Erro criando segmento {out_path}")
    except Exception:
        logger.warning("Tentando fallback do segmento estático")
        fb = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            out_path
        ]
        _run_ffmpeg(fb, f"Fallback falhou para segmento {out_path}")


def _apply_zoom_effect(
    image_path: str,
    output_path: str,
    zoom_type: str,
    zoom_speed: int,
    audio_path: str
) -> None:
    logger.info(f"Aplicando zoom ({zoom_type}) em {image_path} → {output_path}")
    dur = _get_media_duration(audio_path)
    speed = max(1, min(20, zoom_speed)) / 10.0
    if zoom_type == "Nenhum":
        _create_segment_from_image(image_path, audio_path, output_path)
        return

    # ... montagem do filtro zoompan conforme antes ...
    filter_str = f"zoompan=z='min(max(zoom,pzoom)+{speed/100},1.5)':d={int(dur*25)}:s=1920x1080"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-filter_complex", filter_str,
        "-t", str(dur),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-shortest", output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Erro no zoom {output_path}")
    except Exception:
        logger.warning("Fallback: criando segmento estático após falha no zoom")
        _create_segment_from_image(image_path, audio_path, output_path)


def _create_segment_with_audio(video_path: str, audio_path: str, out_path: str) -> None:
    logger.info(f"Combinando vídeo+áudio: {video_path} + {audio_path} → {out_path}")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", out_path
    ]
    _run_ffmpeg(cmd, f"Erro combinando áudio {video_path}")


def _concatenate_with_transitions(
    segment_files: List[str],
    output_path: str,
    trans_type: str,
    trans_dur: float
) -> None:
    logger.info(f"Concatenando {len(segment_files)} segmentos com transição {trans_type}")
    # implementação completa conforme antes (xfade/acrossfade)
    ...  # omissão por brevidade


def _add_background_music(
    video_path: str,
    music_url: str,
    output_path: str,
    volume: int = 20
) -> None:
    logger.info(f"Adicionando música de fundo: {music_url} → {output_path}")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    _download_file(music_url, tmp.name)
    dur = _get_media_duration(video_path)
    vol = max(0, min(100, volume)) / 100.0
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", tmp.name,
        "-filter_complex",
        f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=end={dur}[bgm];"
        "[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-shortest", output_path
    ]
    _run_ffmpeg(cmd, f"Erro música de fundo {output_path}")
    os.remove(tmp.name)


def create_final_video(
    job_id: str,
    scenes: List[Dict[str, Any]],
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content_id: Optional[str] = None,
    advanced_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    logger.info(f"Job {job_id}: começando pipeline completo")
    opts = _merge_options(DEFAULT_VIDEO_OPTIONS, advanced_options)
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"{DEFAULT_STORAGE_PREFIX}{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    segment_files: List[str] = []

    try:
        for idx, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: processando cena {idx+1}/{len(scenes)}")
            img, aud = _prepare_scene_files(job_dir, idx, scene)
            seg_out = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}.mp4")

            zopt = scene.get("options", {}).get("zoom", opts["zoom"])
            if zopt["type"] != "Nenhum":
                tmp_zoom = os.path.join(job_dir, f"zoom_{idx}.mp4")
                _apply_zoom_effect(img, tmp_zoom, zopt["type"], zopt["speed"], aud)
                _create_segment_with_audio(tmp_zoom, aud, seg_out)
            else:
                _create_segment_from_image(img, aud, seg_out)

            segment_files.append(seg_out)

        logger.info(f"Job {job_id}: todas as cenas processadas, iniciando concatenação")
        final_temp = os.path.join(job_dir, f"{job_id}_temp.mp4")
        tconf = opts["transitions"]
        if tconf["type"] == "Corte Seco":
            # concat simples
            concat_txt = os.path.join(job_dir, "concat.txt")
            with open(concat_txt, "w") as f:
                for p in segment_files:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            _run_ffmpeg([
                "ffmpeg","-y","-f","concat","-safe","0","-i",concat_txt,"-c","copy",final_temp
            ], f"Concat simples falhou for job {job_id}")
        else:
            _concatenate_with_transitions(segment_files, final_temp, tconf["type"], tconf["duration"])

        if opts["background_music"]["url"]:
            logger.info(f"Job {job_id}: adicionando música de fundo")
            bgm_out = os.path.join(job_dir, f"{job_id}_bgm.mp4")
            _add_background_music(final_temp, opts["background_music"]["url"], bgm_out, opts["background_music"]["volume"])
            shutil.move(bgm_out, final_temp)

        if opts["captions"]["enabled"]:
            logger.info(f"Job {job_id}: adicionando legendas")
            text_all = "\n".join(s.get("text", "") for s in scenes if s.get("text"))
            if text_all:
                try:
                    cap_out = process_captioning(final_temp, text_all, "srt", [], job_id)
                    shutil.move(cap_out, final_temp)
                except Exception as e:
                    logger.warning(f"Falha em captions: {e}")

        if opts["overlay"]["url"]:
            logger.info(f"Job {job_id}: aplicando overlay global")
            ov_out = os.path.join(job_dir, f"{job_id}_ov.mp4")
            o = opts["overlay"]
            _apply_overlay(final_temp, o["url"], ov_out, o["position"], o["opacity"])
            shutil.move(ov_out, final_temp)

        logger.info(f"Job {job_id}: enviando para S3")
        s3_key = f"final_videos/{job_id}_final.mp4"
        s3_url = upload_to_s3(final_temp, s3_key,
                              S3_BUCKET_NAME, S3_ENDPOINT_URL,
                              S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION)

        shutil.rmtree(job_dir)
        result = {"status": "completed", "video_url": s3_url, "title": title, "id": content_id}
        _send_webhook_notification(webhook_url, job_id, "completed", data=result)
        logger.info(f"Job {job_id}: pipeline concluído com sucesso")
        return result

    except Exception as e:
        logger.exception(f"Job {job_id}: erro fatal: {e}")
        _send_webhook_notification(webhook_url, job_id, "failed", error_message=str(e))
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"status": "failed", "error": str(e)}
