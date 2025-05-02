# Copyright (c) 2025 Stephen G. Pope
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import shutil
import logging
import subprocess
import requests
import tempfile
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

logger = logging.getLogger(__name__)


def _send_webhook_notification(webhook_url, job_id, status, data=None,
                               error_message=None):
    """Helper function to send webhook notification."""
    if not webhook_url:
        logger.info(
            f"Job {job_id}: No webhook URL provided, skipping notification.")
        return

    payload = {
        "job_id": job_id,
        "status": status,
    }

    if data:
        payload["data"] = data

    if error_message:
        payload["error"] = error_message

    try:
        response = requests.post(webhook_url, json=payload)
        if response.status_code >= 200 and response.status_code < 300:
            logger.info(
                f"Job {job_id}: Webhook notification sent successfully.")
        else:
            logger.warning(
                f"Job {job_id}: Webhook notification failed with status code {response.status_code}.")
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to send webhook notification: {str(e)}")


def create_final_video(job_id, scenes, title=None, webhook_url=None, 
                      content_id=None, advanced_options=None):
    """
    Create a final video by combining scenes.

    Args:
        job_id (str): Unique job identifier
        scenes (list): List of scenes, each with image_url and audio_url
        title (str, optional): Title of the video
        webhook_url (str, optional): URL to send status updates
        content_id (str, optional): Content identifier
        advanced_options (dict, optional): Advanced video options including:
            - overlay: {url, position, opacity}
            - zoom: {type, speed}
            - background_music: {url, volume}
            - captions: {enabled, style}
            - transitions: {type, duration}

    Returns:
        dict: Result with status and video URL
    """
    try:
        # Prepare default advanced options
        default_options = {
            "overlay": {
                "url": None,
                "position": "Topo",  # Topo, Centro, Base, Personalizado
                "opacity": 100  # 0-100%
            },
            "zoom": {
                "type": "Zoom In",  # Zoom In, Zoom Out, Pan Horizontal, Pan Vertical, Ken Burns, Nenhum
                "speed": 5  # percentage
            },
            "background_music": {
                "url": None,
                "volume": 20  # 0-100%
            },
            "captions": {
                "enabled": False,
                "style": "Padrão"  # Padrão, Contrastado, Minimalista, Grande
            },
            "transitions": {
                "type": "Fade",  # Corte Seco, Fade, Dissolver, Deslizar, Zoom
                "duration": 1.0  # seconds
            }
        }
        
        # Merge provided options with defaults
        if advanced_options:
            # Merge nested dictionaries
            for category in default_options:
                if category in advanced_options:
                    default_options[category].update(advanced_options[category])
        
        video_options = default_options
        
        # Log start of job with scene count
        logger.info(
            f"Job {job_id}: Starting final video creation with {len(scenes)} scenes. Title: {title}")

        # Create a temporary directory for processing
        job_dir = os.path.join(LOCAL_STORAGE_PATH, f"final_video_{job_id}")
        os.makedirs(job_dir, exist_ok=True)

        # Keep track of processed segment files
        segment_files = []

        # Process each scene
        for i, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: Processing scene {i+1}/{len(scenes)}")

            # Extract scene data
            image_url = scene.get("image_url")
            audio_url = scene.get("audio_url")
            
            # Get scene-specific options if available
            scene_options = scene.get("options", {})
            
            # Create segment folder
            segment_dir = os.path.join(job_dir, f"segment_{i}")
            os.makedirs(segment_dir, exist_ok=True)

            # Download image and audio files
            image_path = os.path.join(segment_dir, f"image_{i}.jpg")
            audio_path = os.path.join(segment_dir, f"audio_{i}.mp3")

            download_file(image_url, image_path)
            download_file(audio_url, audio_path)

            # Apply zoom effect based on settings
            zoom_type = scene_options.get("zoom", {}).get("type", video_options["zoom"]["type"])
            zoom_speed = scene_options.get("zoom", {}).get("speed", video_options["zoom"]["speed"])
            
            # Process image with zoom effect (if not "Nenhum")
            processed_image = image_path
            if zoom_type != "Nenhum":
                processed_image = os.path.join(segment_dir, f"processed_image_{i}.mp4")
                _apply_zoom_effect(image_path, processed_image, zoom_type, zoom_speed, audio_path)
            
            # Create video segment from image and audio
            segment_path = os.path.join(segment_dir, f"segment_{i}.mp4")
            
            if zoom_type != "Nenhum" and os.path.exists(processed_image):
                # Use the already processed image video
                _create_segment_with_audio(processed_image, audio_path, segment_path)
            else:
                # Create a static image video
                _create_segment_from_image(image_path, audio_path, segment_path)
            
            # Apply overlay if specified
            overlay_url = scene_options.get("overlay", {}).get("url", video_options["overlay"]["url"])
            if overlay_url:
                overlay_position = scene_options.get("overlay", {}).get("position", video_options["overlay"]["position"])
                overlay_opacity = scene_options.get("overlay", {}).get("opacity", video_options["overlay"]["opacity"])
                
                overlaid_segment = os.path.join(segment_dir, f"overlaid_segment_{i}.mp4")
                _apply_overlay(segment_path, overlay_url, overlaid_segment, overlay_position, overlay_opacity)
                segment_path = overlaid_segment
            
            segment_files.append(segment_path)

        # Create a file with all segments for concatenation
        concat_file_path = os.path.join(job_dir, "concat_list.txt")
        with open(concat_file_path, 'w') as f:
            for segment in segment_files:
                f.write(f"file '{os.path.abspath(segment)}'\n")

        # Combine all segments into a final video
        final_video_path = os.path.join(LOCAL_STORAGE_PATH, f"{job_id}_final.mp4")
        
        # Determine which concatenation method to use based on transitions
        transition_type = video_options["transitions"]["type"]
        transition_duration = video_options["transitions"]["duration"]
        
        if transition_type == "Corte Seco":
            # Simple concatenation for cut transitions
            ffmpeg_command = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file_path,
                '-c', 'copy',
                final_video_path
            ]
        else:
            # Complex concatenation with transitions
            _concatenate_with_transitions(segment_files, final_video_path, transition_type, transition_duration)
            
        # Add background music if specified
        bg_music_url = video_options["background_music"]["url"]
        if bg_music_url:
            bg_music_volume = video_options["background_music"]["volume"]
            temp_video_path = os.path.join(job_dir, f"temp_with_music.mp4")
            _add_background_music(final_video_path, bg_music_url, temp_video_path, bg_music_volume)
            shutil.move(temp_video_path, final_video_path)
            
        # Add captions if enabled
        if advanced_options and "captions" in advanced_options:
            captions_config = advanced_options.get("captions", {})
            # Only process captions if configuration exists
            if captions_config:
                captions_enabled = captions_config.get("enabled", False)
                captions_style = captions_config.get("style", "Padrão")
                temp_video_path = os.path.join(job_dir, f"temp_with_captions.mp4")
                
                # Extract text from all scenes if available
                all_text = ""
                for i, scene in enumerate(scenes):
                    scene_text = scene.get("text", "")
                    if scene_text:
                        all_text += f"{scene_text}\n"
                
                # Only process if we have text content
                if all_text and captions_enabled:
                    try:
                        caption_type = captions_config.get("caption_type", "srt")
                        caption_style_options = captions_config.get("caption_style", {})
                        # Convert the style to the format expected by process_captioning
                        options = [{"option": k, "value": v} for k, v in caption_style_options.items()] if caption_style_options else []
                        
                        temp_video_path = process_captioning(
                            final_video_path,
                            all_text,
                            caption_type,
                            options,
                            job_id
                        )
                        # Only move if the captioning was successful
                        if os.path.exists(temp_video_path):
                            shutil.move(temp_video_path, final_video_path)
                    except Exception as e:
                        logger.warning(f"Job {job_id}: Caption processing failed, continuing without captions: {str(e)}")

        # Execute the command to combine videos
        try:
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Job {job_id}: FFmpeg command failed: {ffmpeg_command}\nError: {e.stdout}\n{e.stderr}")
            _send_webhook_notification(
                webhook_url, job_id, "failed", error_message=f"FFmpeg error: {e.stderr}")
            # Clean up
            shutil.rmtree(job_dir)
            return {"status": "failed", "error": f"FFmpeg error: {e.stderr}"}

        # Upload to S3
        s3_key = f"final_videos/{job_id}_final.mp4"
        s3_url = upload_to_s3(final_video_path, s3_key, S3_BUCKET_NAME, 
                              S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION)

        # Clean up temporary files
        shutil.rmtree(job_dir)
        os.remove(final_video_path)

        # Send success notification
        _send_webhook_notification(webhook_url, job_id, "completed", {
            "video_url": s3_url,
            "title": title,
            "id": content_id
        })

        return {
            "status": "completed",
            "video_url": s3_url,
            "title": title,
            "id": content_id
        }

    except Exception as e:
        logger.exception(f"Job {job_id}: Error creating final video: {str(e)}")
        _send_webhook_notification(
            webhook_url, job_id, "failed", error_message=str(e))
        return {"status": "failed", "error": str(e)}


def _create_segment_from_image(image_path, audio_path, output_path):
    """Create a video segment from an image and audio file."""
    # Get audio duration
    audio_duration_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path
    ]
    
    process = subprocess.run(audio_duration_cmd, capture_output=True, text=True)
    duration = float(process.stdout.strip())
    
    # Create video from image with the same duration as audio
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1',
        '-i', image_path,
        '-i', audio_path,
        '-c:v', 'libx264',
        '-tune', 'stillimage',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        '-t', str(duration),
        output_path
    ]
    
    subprocess.run(cmd, check=True)


def _apply_zoom_effect(image_path, output_path, zoom_type, zoom_speed, audio_path):
    """Apply zoom effect to an image."""
    # Get audio duration for the zoom effect
    audio_duration_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path
    ]
    
    process = subprocess.run(audio_duration_cmd, capture_output=True, text=True)
    duration = float(process.stdout.strip())
    
    # Calculate zoom parameters based on zoom_type and zoom_speed
    zoom_speed = max(1, min(20, zoom_speed)) / 10.0  # Normalize between 0.1 and 2.0
    
    if zoom_type == "Zoom In":
        # Start wide, end close
        filter_complex = f"zoompan=z='min(zoom+{zoom_speed/100},1.5)':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Zoom Out":
        # Start close, end wide
        filter_complex = f"zoompan=z='if(eq(on,1),1.5,max(1.5-{zoom_speed/100}*on/d,1))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Pan Horizontal":
        # Pan from left to right
        filter_complex = f"zoompan=z=1.2:x='min(in_w*(1-1/zoom)*(on/{int(duration*25)}),in_w*(1-1/zoom))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Pan Vertical":
        # Pan from top to bottom
        filter_complex = f"zoompan=z=1.2:y='min(in_h*(1-1/zoom)*(on/{int(duration*25)}),in_h*(1-1/zoom))':d={int(duration*25)}:s=1920x1080"
    elif zoom_type == "Ken Burns":
        # Random pan and zoom
        filter_complex = f"zoompan=z='min(max(zoom,pzoom)+{zoom_speed/100},1.5)':d={int(duration*25)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080"
    else:
        # Default static image if type is not recognized
        filter_complex = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    
    # Apply the effect
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1',
        '-i', image_path,
        '-filter_complex', filter_complex,
        '-t', str(duration),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        output_path
    ]
    
    subprocess.run(cmd, check=True)


def _create_segment_with_audio(video_path, audio_path, output_path):
    """Combine a video with an audio track, replacing original audio."""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',
        output_path
    ]
    
    subprocess.run(cmd, check=True)


def _apply_overlay(video_path, overlay_url, output_path, position="Topo", opacity=100):
    """Apply overlay to a video segment."""
    # Download overlay
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
        overlay_path = temp_file.name
    
    download_file(overlay_url, overlay_path)
    
    # Calculate position
    position_str = ""
    if position == "Topo":
        position_str = "x=(main_w-overlay_w)/2:y=10"
    elif position == "Centro":
        position_str = "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2"
    elif position == "Base":
        position_str = "x=(main_w-overlay_w)/2:y=main_h-overlay_h-10"
    else:  # Personalizado or default
        position_str = "x=(main_w-overlay_w)/2:y=10"  # Default to top
    
    # Apply overlay with opacity
    opacity = max(0, min(100, opacity)) / 100.0  # Normalize to 0.0-1.0
    
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', overlay_path,
        '-filter_complex', f"[1:v]format=rgba,colorchannelmixer=a={opacity}[overlay];[0:v][overlay]overlay={position_str}",
        '-c:a', 'copy',
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    
    # Clean up temporary overlay file
    os.remove(overlay_path)


def _concatenate_with_transitions(segment_files, output_path, transition_type, transition_duration):
    """Concatenate video segments with transitions."""
    filter_complex = ""
    inputs = ""
    
    # Add each input file
    for i, segment in enumerate(segment_files):
        inputs += f"-i {segment} "
        filter_complex += f"[{i}:v]setpts=PTS-STARTPTS[v{i}];"
        filter_complex += f"[{i}:a]asetpts=PTS-STARTPTS[a{i}];"
    
    # Define transition effect
    transition_filter = ""
    if transition_type == "Fade":
        transition_filter = "fade=t=in:st=0:d={duration},fade=t=out:st={out_time}:d={duration}"
    elif transition_type == "Dissolver":
        transition_filter = "dissolve=duration={duration}:overlap={duration}"
    elif transition_type == "Deslizar":
        transition_filter = "xfade=transition=slideleft:duration={duration}"
    elif transition_type == "Zoom":
        transition_filter = "xfade=transition=fadeblack:duration={duration}"
    else:
        # Default to crossfade if not recognized
        transition_filter = "xfade=transition=fade:duration={duration}"
    
    # Add transitions between segments
    for i in range(len(segment_files)-1):
        out_time = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
             '-of', 'default=noprint_wrappers=1:nokey=1', segment_files[i]],
            capture_output=True, text=True
        ).stdout.strip()
        
        out_time = float(out_time) - transition_duration
        
        transition = transition_filter.format(
            duration=transition_duration,
            out_time=out_time
        )
        
        filter_complex += f"[v{i}][v{i+1}]{transition}[vt{i}];"
        filter_complex += f"[a{i}][a{i+1}]acrossfade=d={transition_duration}[at{i}];"
    
    # Final video and audio streams
    filter_complex += f"[vt{len(segment_files)-2}][at{len(segment_files)-2}]"
    
    # Execute ffmpeg command
    cmd = f"ffmpeg -y {inputs} -filter_complex \"{filter_complex}\" -c:v libx264 -c:a aac {output_path}"
    subprocess.run(cmd, shell=True, check=True)


def _add_background_music(video_path, music_url, output_path, volume=20):
    """Add background music to a video."""
    # Download music
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
        music_path = temp_file.name
    
    download_file(music_url, music_path)
    
    # Get video duration
    video_duration = float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True
    ).stdout.strip())
    
    # Normalize volume (0-100 to 0.0-1.0)
    volume = max(0, min(100, volume)) / 100.0
    
    # Add background music, loop if needed and adjust volume
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-stream_loop', '-1',  # Loop music if shorter than video
        '-i', music_path,
        '-filter_complex', 
        f"[1:a]volume={volume},aloop=loop=-1:size=2e+09,atrim=end={video_duration}[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
        '-map', '0:v',
        '-map', '[aout]',
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-shortest',
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    
    # Clean up temporary music file
    os.remove(music_path)

# Example usage (for testing purposes,
# not called by the route directly usually)
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.INFO)
#     test_scenes = [
#         {'image_url': 'URL_TO_IMAGE_1', 'audio_url': 'URL_TO_AUDIO_1'},
#         {'image_url': 'URL_TO_IMAGE_2', 'audio_url': 'URL_TO_AUDIO_2'}
#     ]
#     test_job_id = 'test-123'
#     test_webhook = 'YOUR_TEST_WEBHOOK_URL'
#     try:
#         final_url = process_create_final_video(
#               test_scenes, test_job_id, title="Test Video",
#               webhook_url=test_webhook
#         )
#         print(f"Process completed. Final URL: {final_url}")
#     except Exception as e:
#         print(f"Process failed: {e}")