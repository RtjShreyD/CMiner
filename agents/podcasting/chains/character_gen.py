import json
import random
import os
from pathlib import Path
from typing import Dict, Any, List
from PIL import Image
from agents.podcasting.utils import get_model

class CharacterGen:
    def __init__(self, image_model_name: str = "models/gemini-2.5-flash-image", text_model_name: str = "models/gemini-flash-latest", max_generations: int = 15, attached_chars: list = None, attached_scene: str = None):
        self.image_model_name = image_model_name
        self.text_model_name = text_model_name
        self.max_generations = max_generations
        self.attached_chars = attached_chars or []
        self.attached_scene = attached_scene

    def run(self, storyboard: Dict[str, Any], session_dir: Path) -> Dict[str, Any]:
        print(f"--- Pipeline: Scene & Character Generation ---")
        out_dir = session_dir / "chars"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        char_prompts = storyboard.get("character_descriptions", [])
        setup_prompt = storyboard.get("podcast_setup_prompt", "A generic anime podcast scene.")
        scenes = storyboard.get("scenes", [])
        
        # 1. Generate Base Scene
        chars_desc_str = ", ".join([f"{c['name']} ({c['prompt']})" for c in char_prompts])
        base_scene_prompt = (
            f"Anime podcast setup. {setup_prompt}. "
            f"Characters present: {chars_desc_str}. "
            "Studio ghibli or ufotable aesthetic, professional lighting, cinematic composition."
        )
        
        # 1. Generate Base Scene (or use attached)
        base_scene_path = out_dir / "base_scene.png"
        if self.attached_scene:
            try:
                import shutil
                shutil.copy(self.attached_scene, base_scene_path)
                print(f"Using attached scene image: {self.attached_scene}")
            except Exception as e:
                print(f"Error copying attached scene: {e}, falling back to generation.")
                self._generate_image(base_scene_prompt, base_scene_path)
        else:
            print("Generating base scene...")
            self._generate_image(base_scene_prompt, base_scene_path)
        
        # 2. Extract unique alteration prompts
        unique_alterations = []
        for scene in scenes:
            alt = scene.get("alteration_prompt", "")
            if alt not in unique_alterations:
                unique_alterations.append(alt)
                
        # Limit to configured maximum alterations max to avoid excessive API calls
        unique_alterations = unique_alterations[:self.max_generations]
        
        alterations_map = {"base_scene": str(base_scene_path)}
        
        # 3. Generate Alterations
        # Since I cannot reliably pass image as context for image generation editing with gemini-2.5-flash-image
        # I will generate variations using highly detailed prompts referencing the base setup.
        for i, alt_prompt in enumerate(unique_alterations):
            alt_name = f"alteration_{i:02d}"
            print(f"Generating alteration: {alt_name}")
            
            alt_path = out_dir / f"{alt_name}.png"
            # PRO-TIP: We provide the base scene as the first part of the message to ensure subject consistency
            # Gemini 1.5/2.5 Flash Image models can anchor to this reference.
            model = get_model(self.image_model_name)
            
            try:
                # Load base image as bytes
                with open(base_scene_path, 'rb') as f:
                    image_bytes = f.read()
                
                # Construct multimodal request: [Image, Prompt]
                # This ensures the model 'sees' the base characters/layout before generating the variation.
                response = model.generate_content([
                    {
                        "mime_type": "image/png",
                        "data": image_bytes
                    },
                    f"Refining the attached scene. {setup_prompt}. Character consistency is CRITICAL. {alt_prompt}. Maintain identical art style and character faces."
                ])
                
                image_data = None
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        image_data = part.inline_data.data
                        break
                
                if image_data:
                    alt_path.write_bytes(image_data)
                    print(f"Successfully generated alteration: {alt_path.name}")
                else:
                    raise ValueError("No image returned from multimodal prompt.")
                
            except Exception as e:
                print(f"Consistency generation failed for alteration {i}, falling back to text-only: {e}")
                self._generate_image(full_alt_prompt, alt_path)

            alterations_map[alt_prompt] = str(alt_path)
        
        # Save map
        chars_json_path = session_dir / "chars.json"
        with open(chars_json_path, "w") as f:
            json.dump(alterations_map, f, indent=2)
        
        return alterations_map

    def _generate_image(self, prompt: str, out_path: Path):
        try:
            model = get_model(self.image_model_name)
            response = model.generate_content(prompt)
            
            image_data = None
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_data = part.inline_data.data
                    break
            
            if image_data:
                out_path.write_bytes(image_data)
                print(f"Successfully generated: {out_path.name}")
            else:
                raise ValueError("No inline_data found.")
                
        except Exception as e:
            print(f"Error generating image. Fallback placeholder used. Error: {e}")
            color = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
            Image.new("RGB", (1280, 720), color=color).save(out_path)

