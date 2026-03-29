import json
import os
from pathlib import Path
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont

class TextCloudGen:
    def __init__(self, fps: int = 24):
        self.fps = fps

    def run(self, storyboard: Dict[str, Any], session_dir: Path):
        print("--- Pipeline: Text Cloud Generator ---")
        overlays_dir = session_dir / "overlays"
        overlays_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = session_dir / "audio"
        
        scenes = storyboard.get("scenes", [])
        char_descriptions = storyboard.get("character_descriptions", [])
        
        # Build character position map
        char_positions = {}
        for c in char_descriptions:
            char_positions[c.get("name")] = c.get("screen_position", "left").lower()
            
        # Attempt to load a nice font, fallback to standard if inaccessible
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, 28)
            else:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
            
        for i, scene in enumerate(scenes):
            timing_file = audio_dir / f"scene_{i}_timing.json"
            if not timing_file.exists():
                print(f"No timing file for scene {i}, skipping text clouds.")
                continue
                
            speaker = scene.get("character")
            position = char_positions.get(speaker, "left")
            
            with open(timing_file, "r") as f:
                timings = json.load(f)
                
            if not timings:
                continue
                
            # The edge-tts offset is in 100-nanosecond units.
            # 1 second = 10,000,000 units
            # duration is also in 100-nanoseconds
            last_timing = timings[-1]
            total_audio_time_sec = (last_timing["offset"] + last_timing["duration"]) / 10000000.0
            
            total_frames = int(total_audio_time_sec * self.fps) + 5 # 5 frame decay buffer
            
            scene_overlay_dir = overlays_dir / f"scene_{i}"
            scene_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"Generating {total_frames} text cloud frames for scene {i} ({speaker} on {position})")
            
            # Fine-tune sync: Subtract a small offset (in 100ns units) if the text feels late.
            # 500,000 units = 50ms.
            SYNC_OFFSET_UNITS = 200000 
            
            for frame_idx in range(total_frames):
                current_time_sec = frame_idx / self.fps
                current_time_units = (current_time_sec * 10000000) + SYNC_OFFSET_UNITS
                
                # Active spoken words up to this current time
                # Keep sliding window of words to fit in bubble nicely, e.g. last 15 words.
                spoken_words = []
                for t in timings:
                    if t["offset"] <= current_time_units:
                        spoken_words.append(t["text"])
                        
                # 1280x720 video size (transparent background)
                img = Image.new("RGBA", (1280, 720), (0,0,0,0))
                draw = ImageDraw.Draw(img)
                
                if spoken_words:
                    display_words = spoken_words[-15:] # maintain up to 15 chunks
                    textstr = " ".join(display_words)
                    
                    lines = self._wrap_text(textstr, font, draw, max_width=400)
                    
                    pad = 25
                    line_heights = []
                    for line in lines:
                        try:
                            # Pillow >= 9.2.0
                            bbox = font.getbbox(line)
                            line_heights.append(bbox[3] - bbox[1])
                        except AttributeError:
                            # Older pillow fallback
                            w, h = draw.textsize(line, font=font)
                            line_heights.append(h)
                            
                    total_text_h = sum(line_heights) + (len(lines) - 1) * 5
                    
                    try:
                        max_w = max([font.getbbox(line)[2] - font.getbbox(line)[0] for line in lines])
                    except AttributeError:
                        max_w = max([draw.textsize(line, font=font)[0] for line in lines])
                        
                    bw = max_w + (pad * 2)
                    bh = total_text_h + (pad * 2)
                    
                    # Dynamic constraints using image dimensions
                    width, height = img.width, img.height
                    safe_margin = 40
                    
                    # Target positioning
                    if position == "left":
                        # Character is on left, bubble offset from left edge
                        bx1 = safe_margin + 60
                        by1 = 50
                    else:
                        # Character is on right, bubble offset from right edge
                        bx1 = width - safe_margin - 60 - bw
                        by1 = 50
                    
                    # Strict Boundary Clamping (Ensure 40px margin from all sides)
                    if bx1 < safe_margin:
                        bx1 = safe_margin
                    
                    if bx1 + bw > width - safe_margin:
                        bx1 = width - safe_margin - bw
                    
                    if by1 + bh > height - safe_margin:
                        by1 = height - safe_margin - bh
                        
                    bx2, by2 = bx1 + bw, by1 + bh
                    
                    # Draw rounded bubble (white opaque)
                    try:
                        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=20, fill=(255,255,255, 240), outline=(0,0,0,255), width=4)
                    except AttributeError:
                        # Fallback for old pillow
                        draw.rectangle([bx1, by1, bx2, by2], fill=(255,255,255, 240), outline=(0,0,0,255), width=4)
                    
                    # Draw text lines
                    cy = by1 + pad
                    for i, line in enumerate(lines):
                        draw.text((bx1 + pad, cy), line, font=font, fill=(0,0,0,255))
                        cy += line_heights[i] + 5 # 5px spacing between lines
                
                frame_path = scene_overlay_dir / f"frame_{frame_idx:04d}.png"
                img.save(frame_path)

    def _wrap_text(self, text, font, draw, max_width):
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            test_line = " ".join(current_line)
            try:
                bbox = font.getbbox(test_line)
                w = bbox[2] - bbox[0]
            except AttributeError:
                w, _ = draw.textsize(test_line, font=font)
                
            if w > max_width:
                if len(current_line) == 1:
                    # Single word is too wide, force it onto its own line anyway
                    # but stop adding to it.
                    lines.append(current_line[0])
                    current_line = []
                else:
                    current_line.pop()
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    
        if current_line:
            lines.append(" ".join(current_line))
            
        return lines
