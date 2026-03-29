import json
from pathlib import Path
from typing import Dict, Any
from agents.podcasting.utils import get_model


class Planner:
    def __init__(self, model_name: str = "models/gemini-flash-latest", tts_voices_pool: Dict[str, str] = None):
        self.model_name = model_name
        self.tts_voices_pool = tts_voices_pool or {}

    def run(self, user_prompt: str, session_dir: Path, attached_chars: list = None, attached_scene: str = None) -> Dict[str, Any]:
        print(f"--- Pipeline: Planner ---")
        attached_chars = attached_chars or []
        
        # Build context about attached images
        image_context = ""
        if attached_scene:
            image_context += f"- Attached Scene Image: {attached_scene}\n"
        if attached_chars:
            image_context += f"- Attached Character Images: {', '.join(attached_chars)}\n"

        prompt = (
            f"You are a master storyboard artist and podcast producer. Based on the user prompt: '{user_prompt}', "
            "create a cinematic and engaging storyboard.json for a text-to-video pipeline formatted as a podcast.\n\n"
            f"CONTEXT: The user has attached the following visual assets via CLI:\n{image_context}\n"
            "INSTRUCTIONS:\n"
            "1. If an 'Attached Scene Image' is provided, your 'podcast_setup_prompt' MUST describe this specific scene as the 'Base Anchor'. Do not invent a new environment; base all scene alterations on this provided background.\n"
            "2. If 'Attached Character Images' are provided, you MUST map them to the characters in your storyboard (e.g. Character 1 uses the first attached image). Your 'prompt' for these characters should be a concise description derived from what you imagine those images contain, or simply refer to them as 'Attached Char X'.\n"
            "3. Ensure the character designs are visually distinct and suitable for high-quality anime generation.\n\n"
            "The storyboard should include:\n"
            "1. title: A suitable title for the video.\n"
            "2. podcast_setup_prompt: A highly detailed prompt describing the overall podcast scene with characters, a table, and mics (e.g., 'An anime style radio studio, two characters sitting across a wooden table with professional microphones, soft neon lighting, studio monitors, high quality, highly detailed, vibrant colors').\n"
            "3. character_descriptions: List of characters. For each, provide:\n"
            "   - name: Character name.\n"
            "   - prompt: A highly detailed physical description prompt for anime-style image generation.\n"
            "   - voice_profile: Description of their voice.\n"
            "   - screen_position: MUST be exactly 'left' or 'right' depending on where they sit at the table. This dictates where their speech bubble will appear.\n"
            f"   - assigned_voice: Analyze the character's demographic and tone, and MUST assign an EXACT string key from this available voice pool: {json.dumps(self.tts_voices_pool)}. ONLY output the exact key string (e.g. 'en-US-AriaNeural').\n"
            "4. scenes: A sequence of scenes representing the podcast dialogue. For each scene, include:\n"
            "   - character: The character currently speaking.\n"
            "   - dialogue: The text for text-to-speech.\n"
            "   - alteration_prompt: A description of how the base `podcast_setup_prompt` changes for this specific scene, focusing primarily on the speaking character's expressions and gestures while keeping the core layout identical. (e.g., 'Same scene holding the same layout but <Character A> is now leaning forward with a concerned expression, hands clasped, while <Character B> is listening attentively').\n"
            "   - duration: Approximate duration in seconds (based on dialogue length, ~150 words per minute).\n"
            "5. text_cloud_strategy: Instructions on styling the text cloud (e.g., comic book style, neon, sci-fi HUD) to match the scene.\n"
            "6. frame_stitching_strategy: Instructions for transitions and overlays.\n\n"
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
