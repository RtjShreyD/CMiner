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
        
        # Map characters to distinct Journey voices
        # e.g., en-US-Journey-D (Male), en-US-Journey-F (Female), en-US-Journey-O (Female)
        available_male_voices = ["en-US-Journey-D"]
        available_female_voices = ["en-US-Journey-F", "en-US-Journey-O"]
        
        char_voices = {}
        for i, char_info in enumerate(char_descriptions):
            name = char_info.get("name")
            if "female" in char_info.get("voice_profile", "").lower():
                char_voices[name] = available_female_voices[i % len(available_female_voices)]
            else:
                char_voices[name] = available_male_voices[i % len(available_male_voices)]
        
        audio_files = []
        for i, scene in enumerate(scenes):
            dialogue = scene.get("dialogue", "")
            char_name = scene.get("character")
            voice_name = char_voices.get(char_name, "en-US-Journey-D")
            
            if not dialogue:
                continue
            
            print(f"Generating audio for {char_name} using {voice_name}: {dialogue[:30]}...")
            
            if use_gcp:
                audio_path = audio_dir / f"scene_{i}.wav"
            else:
                audio_path = audio_dir / f"scene_{i}.mp3"

            try:
                if use_gcp:
                    synthesis_input = texttospeech.SynthesisInput(text=dialogue)
                    
                    voice = texttospeech.VoiceSelectionParams(
                        language_code="en-US",
                        name=voice_name,
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
                    # Fallback to edge-tts (High quality Microsoft Neural voices)
                    edge_males = ["en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural", "en-US-RogerNeural"]
                    edge_females = ["en-US-AriaNeural", "en-US-JennyNeural", "en-US-AnaNeural", "en-US-MichelleNeural"]
                    
                    if "female" in voice_name.lower():
                        voice_variant = edge_females[i % len(edge_females)]
                    else:
                        voice_variant = edge_males[i % len(edge_males)]
                        
                    subprocess.run(["edge-tts", "--voice", voice_variant, "--text", dialogue, "--write-media", str(audio_path)], check=True)
                    
                audio_files.append(str(audio_path))
                
            except Exception as e:
                print(f"Error generating audio for scene {i}: {e}")

                
        return audio_files

