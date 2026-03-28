import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from tools.podcasting.utils import get_model

try:
    from google.cloud import texttospeech
    GCP_TTS_AVAILABLE = True
except ImportError:
    GCP_TTS_AVAILABLE = False


class TTSGen:
    def __init__(self, model_name: str = "models/gemini-flash-latest"):
        self.model_name = model_name
        self.client = None
        if GCP_TTS_AVAILABLE:
            try:
                self.client = texttospeech.TextToSpeechClient()
            except Exception as e:
                print(f"Failed to initialize Google Cloud TTS client (likely missing credentials): {e}")
                
    def run(self, storyboard: Dict[str, Any], session_dir: Path) -> List[str]:
        use_gcp = self.client is not None
        provider = "Google Cloud" if use_gcp else "Fallback (Edge-TTS)"
        print(f"--- Pipeline: TTS Gen ({provider}) ---")
        audio_dir = session_dir / "audio"

        scenes = storyboard.get("scenes", [])
        char_descriptions = storyboard.get("character_descriptions", [])
        
        # Extract assigned voice for Edge TTS from the planner
        char_assigned_voices = {}
        for char_info in char_descriptions:
            name = char_info.get("name")
            # If the LLM failed to assign, fallback to a neutral standard
            assigned = char_info.get("assigned_voice", "en-US-AriaNeural") 
            char_assigned_voices[name] = assigned

        audio_files = []
        for i, scene in enumerate(scenes):
            dialogue = scene.get("dialogue", "")
            char_name = scene.get("character")
            edge_voice_name = char_assigned_voices.get(char_name, "en-US-AriaNeural")
            
            # For GCP (If ever used), still map to standard journey temporarily
            gcp_voice_name = "en-US-Journey-F" if "female" in edge_voice_name.lower() else "en-US-Journey-D"
            
            active_voice = gcp_voice_name if use_gcp else edge_voice_name
            
            if not dialogue:
                continue
            
            print(f"Generating audio for {char_name} using {active_voice}: {dialogue[:30]}...")
            
            if use_gcp:
                audio_path = audio_dir / f"scene_{i}.wav"
            else:
                audio_path = audio_dir / f"scene_{i}.mp3"

            try:
                if use_gcp:
                    synthesis_input = texttospeech.SynthesisInput(text=dialogue)
                    
                    voice = texttospeech.VoiceSelectionParams(
                        language_code="en-US",
                        name=gcp_voice_name,
                    )
                    
                    audio_config = texttospeech.AudioConfig(
                        audio_encoding=texttospeech.AudioEncoding.LINEAR16
                    )
                    
                    response = self.client.synthesize_speech(
                        input=synthesis_input, voice=voice, audio_config=audio_config
                    )
                    
                    with open(audio_path, "wb") as out:
                        out.write(response.audio_content)
                else:
                    # Fallback to edge-tts (High quality Microsoft Neural voices via LLM assignment)
                    subprocess.run(["edge-tts", "--voice", edge_voice_name, "--text", dialogue, "--write-media", str(audio_path)], check=True)
                    
                audio_files.append(str(audio_path))
                
            except Exception as e:
                print(f"Error generating audio for scene {i}: {e}")

                
        return audio_files

