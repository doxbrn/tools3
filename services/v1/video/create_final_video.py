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
    """Baixa conteúdo de URL em arquivo local."""
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def _get_media_duration(path: str) -> float:
    """Retorna duração em segundos ou fallback."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = result.stdout.strip()
        return float(val) if val.replace(".", "", 1).isdigit() else DEFAULT_DURATION_FALLBACK
    except Exception:
        logger.warning(f"Could not get duration for {path}; using fallback {DEFAULT_DURATION_FALLBACK}s")
        return DEFAULT_DURATION_FALLBACK


def _run_ffmpeg(cmd: List[str], err_msg: str) -> None:
    """Executa comando FFmpeg e lança CalledProcessError em falha."""
    logger.debug("FFmpeg → " + " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _merge_options(defaults: Dict[str, Dict[str, Any]],
                   overrides: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Mescla opções avançadas com valores padrão."""
    opts = {k: v.copy() for k, v in defaults.items()}
    if not overrides:
        return opts
    for k, v in overrides.items():
        if k in opts and isinstance(v, dict):
            opts[k].update(v)
    return opts


def _prepare_scene_files(job_dir: str, idx: int, scene: Dict[str, Any]) -> (str, str):
    """
    Cria subpasta de segmento e baixa image & audio.
    Retorna: (image_path, audio_path)
    """
    seg_dir = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}")
    os.makedirs(seg_dir, exist_ok=True)

    # Deriva nome do arquivo da URL
    def _file_name_from_url(u):
        return os.path.basename(urllib.parse.urlparse(u).path)

    img_path = os.path.join(seg_dir, _file_name_from_url(scene["image_url"]))
    aud_path = os.path.join(seg_dir, _file_name_from_url(scene["audio_url"]))

    _download_file(scene["image_url"], img_path)
    _download_file(scene["audio_url"], aud_path)

    return img_path, aud_path


def _send_webhook_notification(
    webhook_url: Optional[str],
    job_id: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> None:
    """Envia POST JSON ao webhook configurado."""
    if not webhook_url:
        logger.debug(f"Job {job_id}: nenhum webhook configurado, pulando.")
        return
    payload = {"job_id": job_id, "status": status}
    if data:
        payload["data"] = data
    if error_message:
        payload["error"] = error_message

    try:
        resp = requests.post(webhook_url, json=payload)
        if 200 <= resp.status_code < 300:
            logger.info(f"Job {job_id}: webhook enviado.")
        else:
            logger.warning(f"Job {job_id}: webhook retornou {resp.status_code}.")
    except Exception as e:
        logger.error(f"Job {job_id}: falha ao enviar webhook: {e}")


def _create_segment_from_image(image_path: str, audio_path: str, out_path: str) -> None:
    """Gera vídeo estático a partir de imagem com áudio como trilha."""
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
        _run_ffmpeg(cmd, f"Erro criando segmento de imagem {out_path}")
    except Exception:
        # fallback sem áudio
        fb = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            out_path
        ]
        _run_ffmpeg(fb, f"Fallback segmento estático {out_path}")


def _apply_zoom_effect(
    image_path: str,
    output_path: str,
    zoom_type: str,
    zoom_speed: int,
    audio_path: str
) -> None:
    """Aplica efeito de zoom/ken burns sobre a imagem ao longo do áudio."""
    dur = _get_media_duration(audio_path)
    speed = max(1, min(20, zoom_speed)) / 10.0

    if zoom_type == "Nenhum":
        _create_segment_from_image(image_path, audio_path, output_path)
        return

    # Define filter_complex
    if zoom_type == "Zoom In":
        filt = f"zoompan=z='min(zoom+{speed/100},1.5)':d={int(dur*25)}:s=1920x1080"
    elif zoom_type == "Zoom Out":
        filt = f"zoompan=z='if(eq(on,1),1.5,max(1.5-{speed/100}*on/d,1))':d={int(dur*25)}:s=1920x1080"
    elif zoom_type == "Pan Horizontal":
        filt = (
            f"zoompan=z=1.2:x='min(in_w*(1-1/zoom)*(on/{int(dur*25)}),"
            f"in_w*(1-1/zoom))':d={int(dur*25)}:s=1920x1080"
        )
    elif zoom_type == "Pan Vertical":
        filt = (
            f"zoompan=z=1.2:y='min(in_h*(1-1/zoom)*(on/{int(dur*25)}),"
            f"in_h*(1-1/zoom))':d={int(dur*25)}:s=1920x1080"
        )
    else:  # Ken Burns ou default
        filt = f"zoompan=z='min(max(zoom,pzoom)+{speed/100},1.5)':d={int(dur*25)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-filter_complex", filt,
        "-t", str(dur),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-shortest", output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Erro aplicando zoom {output_path}")
    except Exception:
        # se falhar, gera segmento estático
        _create_segment_from_image(image_path, audio_path, output_path)


def _create_segment_with_audio(video_path: str, audio_path: str, out_path: str) -> None:
    """Substitui áudio de um vídeo pela trilha fornecida."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", out_path
    ]
    _run_ffmpeg(cmd, f"Erro combinando áudio em {video_path}")


def _concatenate_with_transitions(
    segment_files: List[str],
    output_path: str,
    trans_type: str,
    trans_dur: float
) -> None:
    """
    Concatena segmentos com transições complexas (xfade, acrossfade).
    Em falha, faz concat simples via lista de arquivos.
    """
    inputs = []
    fc = []
    for i, seg in enumerate(segment_files):
        inputs += ["-i", seg]
        fc.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}];")

    for i in range(len(segment_files) - 1):
        dur = _get_media_duration(segment_files[i])
        off = max(0, dur - trans_dur)
        tfilter = f"xfade=transition=fade:duration={trans_dur}:offset={off}"
        fc.append(f"[v{i}][v{i+1}]{tfilter}[vt{i}];")
        fc.append(f"[a{i}][a{i+1}]acrossfade=d={trans_dur}[at{i}];")

    last = len(segment_files) - 2
    filter_complex = "".join(fc) + f"[vt{last}][at{last}]"

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-c:a", "aac", output_path
    ]
    try:
        _run_ffmpeg(cmd, f"Erro concatenando com transições em {output_path}")
    except Exception:
        # fallback concat simples
        list_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt")
        for seg in segment_files:
            list_file.write(f"file '{os.path.abspath(seg)}'\n")
        list_file.close()
        fb = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file.name, "-c", "copy", output_path
        ]
        _run_ffmpeg(fb, f"Fallback concat {output_path}")
        os.unlink(list_file.name)


def _add_background_music(
    video_path: str,
    music_url: str,
    output_path: str,
    volume: int = 20
) -> None:
    """Adiciona música de fundo com loop e mixagem de volumes."""
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
    _run_ffmpeg(cmd, f"Erro adicionando música em {output_path}")
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
    Orquestra pipeline completo de geração de vídeo:
    - download de cenas
    - zoom, overlays, transições, música, legendas
    - upload para S3
    - notifica webhook
    """
    opts = _merge_options(DEFAULT_VIDEO_OPTIONS, advanced_options)
    job_dir = os.path.join(LOCAL_STORAGE_PATH, f"{DEFAULT_STORAGE_PREFIX}{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    segment_files: List[str] = []

    try:
        logger.info(f"Job {job_id}: iniciando {len(scenes)} cenas (title={title})")

        # 1) Processa cada cena
        for idx, scene in enumerate(scenes):
            img, aud = _prepare_scene_files(job_dir, idx, scene)
            seg_path = os.path.join(job_dir, f"{DEFAULT_SEGMENT_PREFIX}{idx}.mp4")

            zt = scene.get("options", {}).get("zoom", {}).get("type", opts["zoom"]["type"])
            zs = scene.get("options", {}).get("zoom", {}).get("speed", opts["zoom"]["speed"])

            # zoom ou estático
            if zt != "Nenhum":
                tmp_zoom = os.path.join(job_dir, f"zoom_{idx}.mp4")
                _apply_zoom_effect(img, tmp_zoom, zt, zs, aud)
                _create_segment_with_audio(tmp_zoom, aud, seg_path)
            else:
                _create_segment_from_image(img, aud, seg_path)

            segment_files.append(seg_path)

        # 2) Concatena com ou sem transições
        final_temp = os.path.join(job_dir, f"{job_id}_temp.mp4")
        ttype = opts["transitions"]["type"]
        tdur  = opts["transitions"]["duration"]

        if ttype == "Corte Seco":
            concat_txt = os.path.join(job_dir, "concat.txt")
            with open(concat_txt, "w") as f:
                for p in segment_files:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            _run_ffmpeg(
                ["ffmpeg","-y","-f","concat","-safe","0","-i",concat_txt,"-c","copy",final_temp],
                f"concat simples falhou para job {job_id}"
            )
        else:
            _concatenate_with_transitions(segment_files, final_temp, ttype, tdur)

        # 3) Música de fundo
        if opts["background_music"]["url"]:
            tmp_bgm = os.path.join(job_dir, f"{job_id}_bgm.mp4")
            _add_background_music(final_temp, opts["background_music"]["url"], tmp_bgm, opts["background_music"]["volume"])
            shutil.move(tmp_bgm, final_temp)

        # 4) Legendas
        caps = opts["captions"]
        if caps.get("enabled"):
            text_all = "\n".join(s.get("text","") for s in scenes if s.get("text"))
            if text_all:
                try:
                    captioned = process_captioning(final_temp, text_all, caps.get("type","srt"), [], job_id)
                    if os.path.exists(captioned):
                        shutil.move(captioned, final_temp)
                except Exception as e:
                    logger.warning(f"Job {job_id}: falha em legendas: {e}")

        # 5) Overlay global
        ov = opts["overlay"]
        if ov.get("url"):
            tmp_ov = os.path.join(job_dir, f"{job_id}_ov.mp4")
            _apply_overlay(final_temp, ov["url"], tmp_ov, ov["position"], ov["opacity"])
            shutil.move(tmp_ov, final_temp)

        # 6) Upload S3
        key = f"final_videos/{job_id}_final.mp4"
        s3_url = upload_to_s3(final_temp, key,
                              S3_BUCKET_NAME, S3_ENDPOINT_URL,
                              S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION)

        # limpeza
        shutil.rmtree(job_dir)

        result = {"status": "completed", "video_url": s3_url, "title": title, "id": content_id}
        _send_webhook_notification(webhook_url, job_id, "completed", data=result)
        return result

    except Exception as e:
        logger.exception(f"Job {job_id}: falha geral: {e}")
        _send_webhook_notification(webhook_url, job_id, "failed", error_message=str(e))
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"status": "failed", "error": str(e)}