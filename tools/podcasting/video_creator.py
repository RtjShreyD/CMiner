import subprocess
from pathlib import Path
from typing import Dict, Any, List
from PIL import Image, ImageDraw, ImageFont

class VideoCreator:
    def __init__(self):
        pass

    def run(self, storyboard: Dict[str, Any], char_map: Dict[str, str], audio_files: List[str], session_dir: Path) -> Path:
        print(f"--- Pipeline: Video Creator ---")
        frames_dir = session_dir / "frames"
        scenes = storyboard.get("scenes", [])
        
        # Create frames for each scene
        for i, (scene, audio_path) in enumerate(zip(scenes, audio_files)):
            alt_prompt = scene.get("alteration_prompt", "")
            
            # Map the scene's alteration prompt to the generated image, fallback to base scene
            img_path = char_map.get(alt_prompt, char_map.get("base_scene"))
            
            if not img_path:
                continue
            
            # Use the full scene image as the frame directly
            frame_path = frames_dir / f"frame_{i:04d}.png"
            img = Image.open(img_path)
            img.save(frame_path)

            
            # Get duration from audio file using ffprobe
            try:
                res = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                    capture_output=True, text=True
                )
                duration = float(res.stdout.strip())
            except:
                duration = 2.0
            
            # Segment video for this scene
            seg_path = session_dir / f"seg_{i}.mp4"
            overlay_dir = session_dir / "overlays" / f"scene_{i}"
            
            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                # We have a sequence of text cloud frames
                subprocess.run([
                    "ffmpeg", "-y", 
                    "-loop", "1", "-i", str(frame_path), 
                    "-framerate", "24", "-i", f"{overlay_dir}/frame_%04d.png",
                    "-i", audio_path,
                    "-filter_complex", "[0:v][1:v]overlay=shortest=1,format=yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(seg_path)
                ], check=True, capture_output=True)
            else:
                subprocess.run([
                    "ffmpeg", "-y", "-loop", "1", "-i", str(frame_path), "-i", audio_path,
                    "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(seg_path)
                ], check=True, capture_output=True)

        # Concatenate segments
        concat_file = session_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for i in range(len(audio_files)):
                f.write(f"file 'seg_{i}.mp4'\n")
        
        final_video_name = storyboard.get("title", "final_podcast").replace(" ", "_") + ".mp4"
        final_video_path = session_dir / final_video_name
        
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", str(final_video_path)
        ], check=True, capture_output=True)
        
        print(f"Final video rendered at: {final_video_path}")
        return final_video_path

def random_randint(a, b):
    import random
    return random.randint(a, b)
