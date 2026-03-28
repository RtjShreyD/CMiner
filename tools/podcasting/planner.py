import json
from pathlib import Path
from typing import Dict, Any
from tools.podcasting.utils import get_model


class Planner:
    def __init__(self, model_name: str = "models/gemini-flash-latest"):
        self.model_name = model_name

    def run(self, user_prompt: str, session_dir: Path) -> Dict[str, Any]:
        print(f"--- Pipeline: Planner ---")
        prompt = (
            f"You are a master storyboard artist and podcast producer. Based on the user prompt: '{user_prompt}', "
            "create a cinematic and engaging storyboard.json for a text-to-video pipeline formatted as a podcast. "
            "Ensure the character designs are visually distinct and suitable for high-quality anime generation.\n\n"
            "The storyboard should include:\n"
            "1. title: A suitable title for the video.\n"
            "2. podcast_setup_prompt: A highly detailed prompt describing the overall podcast scene with characters, a table, and mics (e.g., 'An anime style radio studio, two characters sitting across a wooden table with professional microphones, soft neon lighting, studio monitors, high quality, highly detailed, vibrant colors').\n"
            "3. character_descriptions: List of characters. For each, provide:\n"
            "   - name: Character name.\n"
            "   - prompt: A highly detailed physical description prompt for anime-style image generation.\n"
            "   - voice_profile: Description of their voice.\n"
            "4. scenes: A sequence of scenes representing the podcast dialogue. For each scene, include:\n"
            "   - character: The character currently speaking.\n"
            "   - dialogue: The text for text-to-speech.\n"
            "   - alteration_prompt: A description of how the base `podcast_setup_prompt` changes for this specific scene, focusing primarily on the speaking character's expressions and gestures while keeping the core layout identical. (e.g., 'Same scene holding the same layout but <Character A> is now leaning forward with a concerned expression, hands clasped, while <Character B> is listening attentively').\n"
            "   - duration: Approximate duration in seconds (based on dialogue length, ~150 words per minute).\n"
            "5. frame_stitching_strategy: Instructions for transitions and overlays.\n\n"
            "Return ONLY strict JSON."
        )
        
        model = get_model(self.model_name)
        response = model.generate_content(prompt)
        
        # Robustly extract JSON
        text = response.text
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON found in response: {text}")
        
        storyboard = json.loads(text[start:end+1])
        
        storyboard_path = session_dir / "storyboard.json"
        with open(storyboard_path, "w") as f:
            json.dump(storyboard, f, indent=2)
            
        print(f"Storyboard saved to {storyboard_path}")
        return storyboard
