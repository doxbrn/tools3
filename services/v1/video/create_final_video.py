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
from config import LOCAL_STORAGE_PATH
from services.file_management import download_file

logger = logging.getLogger(__name__)


def process_create_final_video(scenes, job_id, title=None, webhook_url=None):
    """
    Create a final video from a list of scenes, each containing image 
    and audio.
    
    Args:
        scenes (list): List of scenes, each with image_url and audio_url
        job_id (str): Unique job identifier
        title (str, optional): Title of the video
        webhook_url (str, optional): Webhook URL for notifications
        
    Returns:
        str: Path to the final video file
    """
    # Create a temporary working directory
    temp_dir = os.path.join(LOCAL_STORAGE_PATH, f"final_video_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)
    
    segment_files = []
    final_video_path = os.path.join(LOCAL_STORAGE_PATH, f"{job_id}_final.mp4")
    concat_file_path = os.path.join(temp_dir, "concat_list.txt")
    
    try:
        logger.info(
            f"Job {job_id}: Starting final video creation with "
            f"{len(scenes)} scenes"
        )
        
        # Process each scene by creating a video segment from image and audio
        for i, scene in enumerate(scenes):
            logger.info(f"Job {job_id}: Processing scene {i+1}/{len(scenes)}")
            
            # Download image and audio files
            image_url = scene.get('image_url')
            audio_url = scene.get('audio_url')
            
            if not image_url or not audio_url:
                logger.warning(
                    f"Job {job_id}: Scene {i+1} missing image/audio url, "
                    f"skipping"
                )
                continue
                
            image_path = download_file(
                image_url, os.path.join(temp_dir, f"image_{i}")
            )
            audio_path = download_file(
                audio_url, os.path.join(temp_dir, f"audio_{i}")
            )
            
            # Create segment video (image + audio)
            segment_path = os.path.join(temp_dir, f"segment_{i}.mp4")
            
            # Use ffmpeg to create a video segment with the image and audio
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
                segment_path
            ]
            
            subprocess.run(cmd, check=True)
            segment_files.append(segment_path)
            
            # Clean up the downloaded files
            os.remove(image_path)
            os.remove(audio_path)
        
        # Create concat file for ffmpeg
        with open(concat_file_path, 'w') as f:
            for segment in segment_files:
                f.write(f"file '{os.path.abspath(segment)}'\n")
        
        # Concatenate all segments into the final video
        concat_cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file_path,
            '-c', 'copy',
            final_video_path
        ]
        
        subprocess.run(concat_cmd, check=True)
        logger.info(
            f"Job {job_id}: Final video created: {final_video_path}"
        )
        
        return final_video_path
        
    except Exception as e:
        logger.error(f"Job {job_id}: Error creating final video: {str(e)}")
        raise
    
    finally:
        # Clean up temporary files
        try:
            shutil.rmtree(temp_dir)
            logger.info(
                f"Job {job_id}: Cleaned up temporary directory {temp_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Job {job_id}: Error cleaning up temp dir: {str(e)}"
            ) 