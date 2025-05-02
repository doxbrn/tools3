# services/v1/video/video_utils.py

import os
import requests
import subprocess
import logging

logger = logging.getLogger(__name__)

# === Webhook Utility ===
def _send_webhook(url: str, payload: dict):
    """Envia o resultado para a webhook URL."""
    try:
        # Add a specific identifier to the log message
        log_prefix = f"[Webhook {payload.get('content_id', 'N/A')}]"
        logger.info(f"{log_prefix} Sending to {url} with payload: {payload}")
        response = requests.post(url, json=payload, timeout=20)  # Increased timeout
        response.raise_for_status()  # Raise HTTPError for bad responses
        logger.info(
            f"{log_prefix} Sent successfully to {url}, "
            f"status code: {response.status_code}"
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"{log_prefix} Failed to send webhook to {url}: {e}")
    except Exception as e:
        logger.error(
            f"{log_prefix} Unexpected error sending webhook to {url}: {e}", 
            exc_info=True
        )

# === Download Utility ===
def _download_stream(url: str, dest: str):
    """
    Baixa de forma streaming da URL para o arquivo `dest`.
    """
    logger.debug(f"Downloading {url} to {dest}")
    try:
        resp = requests.get(url, stream=True, timeout=60) # Increased timeout
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
        logger.debug(f"Successfully downloaded {url} to {dest}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download {url}: {e}")
        raise IOError(f"Failed to download {url}: {e}") from e  # Reraise
    except Exception as e:
        logger.error(f"Unexpected error downloading {url}: {e}", exc_info=True)
        raise IOError(f"Unexpected error downloading {url}") from e  # Reraise

# === FFmpeg Runner ===
class FFmpegExecutionError(Exception):
    """Custom exception for FFmpeg errors."""
    pass

def _run_ffmpeg(cmd: list[str], err_msg: str):
    """
    Executa um comando ffmpeg e verifica saída.
    Raises FFmpegExecutionError on failure.
    """
    cmd_str = " ".join(cmd)
    logger.debug(f"Running ffmpeg: {cmd_str}")
    # Use shell=False for security and better argument handling
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if proc.returncode != 0:
        stderr_lines = proc.stderr.splitlines()
        last_line = stderr_lines[-1] if stderr_lines else "(no stderr output)"
        full_err_msg = f"ffmpeg command failed with code {proc.returncode}. CMD: {cmd_str}"
        logger.error(full_err_msg)
        logger.error(f"ffmpeg stderr:\n{proc.stderr}")
        if proc.stdout:  # Log stdout too, might contain clues
            logger.error(f"ffmpeg stdout:\n{proc.stdout}")
        # Include detailed error in exception
        raise FFmpegExecutionError(
            f"{err_msg}: {last_line}\nFull command: {cmd_str}\nStderr: {proc.stderr.strip()}"
        )
    else:
        # Log stdout/stderr even on success if debug level is enabled
        logger.debug(f"ffmpeg completed successfully. CMD: {cmd_str}")
        if proc.stdout:
            logger.debug(f"ffmpeg stdout:\n{proc.stdout}")
        if proc.stderr:  # Often contains useful info even on success
            logger.debug(f"ffmpeg stderr:\n{proc.stderr}")

# === FFprobe Utilities ===
class FFprobeError(Exception):
    """Custom exception for ffprobe errors."""
    pass

def _get_media_duration(path: str) -> float:
    """
    Gets media duration in seconds using ffprobe.
    Raises FFprobeError on failure.
    """
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ]
    logger.debug(f"Getting duration for {path}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        logger.error(f"ffprobe duration check failed for {path}. Code: {proc.returncode}")
        logger.error(f"ffprobe stderr: {stderr}")
        raise FFprobeError(f"ffprobe failed to get duration for {path}: {stderr}")
    try:
        duration_str = proc.stdout.strip()
        if not duration_str or duration_str.lower() == 'n/a':
             raise ValueError("No duration found in ffprobe output")
        logger.debug(f"Duration output for {path}: '{duration_str}'")
        return float(duration_str)
    except ValueError as e:
        logger.error(f"Could not parse duration '{duration_str}' for {path}: {e}")
        raise FFprobeError(
            f"Invalid duration value '{duration_str}' for {path}"
        ) from e

def _get_video_dimensions(path: str) -> tuple[int, int]:
    """Gets video width and height using ffprobe.
       Raises FFprobeError on failure.
    """
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',  # Select first video stream
        '-show_entries', 'stream=width,height',
        '-of', 'csv=s=x:p=0',  # Output format widthxheight
        path
    ]
    logger.debug(f"Getting dimensions for {path}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        logger.error(
            f"ffprobe dimension check failed for {path}. Code: {proc.returncode}"
        )
        logger.error(f"ffprobe stderr: {stderr}")
        raise FFprobeError(
            f"ffprobe failed to get dimensions for {path}: {stderr}"
        )
    try:
        dimensions_str = proc.stdout.strip()
        if not dimensions_str:
             raise ValueError("No dimensions found in ffprobe output")
        width, height = map(int, dimensions_str.split('x'))
        logger.debug(f"Dimensions for {path}: {width}x{height}")
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid dimensions {width}x{height}")
        return width, height
    except Exception as e:
        # Use dimensions_str in error message if available
        dim_val = dimensions_str if 'dimensions_str' in locals() else '[unavailable]'
        logger.error(
            f"Could not parse dimensions '{dim_val}' for {path}: {e}"
        )
        raise FFprobeError(
            f"Invalid dimensions '{dim_val}' for {path}"
        ) from e 