import os

# Ensure execution from project root
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root_dir)

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Testing Gemini 2.0 Audio Output...")
try:
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Hello, this is a test of the Gemini audio output capabilities.',
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            )
        )
    )
    
    for part in response.candidates[0].content.parts:
        if getattr(part, 'inline_data', None) or hasattr(part, 'inline_data'):
            # The SDK might return it slightly differently, let's just dump the dict mostly
            print("Found audio data in part!")
            with open("test_audio_gemini.wav", "wb") as f:
                f.write(part.inline_data.data)
            print("Saved to test_audio_gemini.wav")
            break
except Exception as e:
    print(f"Error: {e}")
