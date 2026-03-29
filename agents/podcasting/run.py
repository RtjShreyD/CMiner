#!/usr/bin/env python3
import argparse
import sys
import json
from pathlib import Path

# Fix path to allow importing from local directory if needed
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))


from agents.podcasting.utils import ensure_session_outputs
from agents.podcasting.chains.planner import Planner
from agents.podcasting.chains.character_gen import CharacterGen
from agents.podcasting.chains.tts_gen import TTSGen
from agents.podcasting.chains.text_cloud_gen import TextCloudGen
from agents.podcasting.chains.video_creator import VideoCreator


def main():
    parser = argparse.ArgumentParser(description="Podcasting Text-to-Video Pipeline Runner")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--agent", default="podcaster", help="OpenClaw agent id")
    parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    parser.add_argument("--prompt", help="User prompt (optional if --script or --session is used)")
    parser.add_argument("--script", help="Path to a script text file")
    parser.add_argument("--char", action="append", default=[], help="Path to a character image (up to 3 allowed)")
    parser.add_argument("--scene", help="Path to a scene background image (up to 1 allowed)")
    parser.add_argument("--thinking", default="high", help="Thinking level")
    parser.add_argument("--step", choices=["all", "planner", "images", "audio", "clouds", "video"], default="all", help="Execute specific pipeline step")
    parser.add_argument("--session", help="Continue work in an existing session directory")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    
    # 0. Session Handling
    if args.session:
        session_dir = Path(args.session).resolve()
        if not session_dir.exists():
            print(f"Error: Session directory {args.session} not found.")
            sys.exit(1)
        print(f"Continuing in session: {session_dir}")
    else:
        session_dir = ensure_session_outputs(workspace)
        print(f"New session directory: {session_dir}")

    # Determine prompt (only needed if planner or all is selected and no storyboard exists)
    user_prompt = args.prompt
    storyboard_path = session_dir / "storyboard.json"
    
    if args.step in ["all", "planner"] and not storyboard_path.exists():
        if args.script:
            script_path = Path(args.script).resolve()
            if script_path.exists():
                with open(script_path, "r") as f:
                    user_prompt = f.read().strip()
                    print(f"Loaded prompt from script: {args.script}")
            else:
                print(f"Error: Script file {args.script} not found.")
                sys.exit(1)

        if not user_prompt:
            print("Error: No prompt provided for planner step. Use --prompt or --script.")
            sys.exit(1)

    # Validate limits
    attached_chars = args.char[:3]
    if len(args.char) > 3:
        print("Warning: Only 3 character images are supported. Using the first 3.")

    attached_scene = args.scene
    # No fallback needed unless explicitly asked

    # Load Configuration
    config_path = Path(__file__).resolve().parent / "config.json"
    config = {}
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Failed to load config.json: {e}")
            
    models_config = config.get("models", {})
    planner_model = models_config.get("planner_model", "models/gemini-flash-latest")
    char_image_model = models_config.get("character_image_model", "models/gemini-2.5-flash-image")
    char_text_model = models_config.get("character_text_model", "models/gemini-flash-latest")
    tts_model_name = models_config.get("tts_gen_model", "models/gemini-flash-latest")
    max_image_gens = models_config.get("max_image_generations", 15)
    
    tts_voices_pool = config.get("tts_voices_pool", {})
    
    print(f"Session directory: {session_dir}")

    # 1. Planner
    if args.step in ["all", "planner"]:
        planner = Planner(model_name=planner_model, tts_voices_pool=tts_voices_pool)
        storyboard = planner.run(user_prompt, session_dir, attached_chars=attached_chars, attached_scene=attached_scene)
    else:
        if storyboard_path.exists():
            with open(storyboard_path, "r") as f:
                storyboard = json.load(f)
        else:
            print(f"Error: storyboard.json not found in {session_dir}. Run 'planner' step first.")
            sys.exit(1)
    
    # 2. Character Generation
    chars_json_path = session_dir / "chars.json"
    if args.step in ["all", "images"]:
        char_gen = CharacterGen(
            image_model_name=char_image_model, 
            text_model_name=char_text_model, 
            max_generations=max_image_gens,
            attached_chars=attached_chars,
            attached_scene=attached_scene
        )
        char_map = char_gen.run(storyboard, session_dir)
    else:
        if chars_json_path.exists():
            with open(chars_json_path, "r") as f:
                char_map = json.load(f)
        else:
            char_map = {} # May not be needed for all future steps
    
    # 3. TTS Generation
    audio_dir = session_dir / "audio"
    if args.step in ["all", "audio"]:
        tts_gen = TTSGen(model_name=tts_model_name)
        audio_files = tts_gen.run(storyboard, session_dir)
    else:
        audio_files = [str(p) for p in audio_dir.glob("scene_*.mp3")] + [str(p) for p in audio_dir.glob("scene_*.wav")]
        audio_files.sort()
    
    # 4. Text Cloud / Speech Bubble Generation
    if args.step in ["all", "clouds"]:
        cloud_gen = TextCloudGen(fps=24)
        cloud_gen.run(storyboard, session_dir)
    
    # 5. Video Creation
    if args.step in ["all", "video"]:
        # Ensure we have required maps
        if not char_map and chars_json_path.exists():
            with open(chars_json_path, "r") as f:
                char_map = json.load(f)
        
        video_creator = VideoCreator()
        final_video = video_creator.run(storyboard, char_map, audio_files, session_dir)
        print(f"Task Complete. Final Output: {final_video}")
    else:
        print(f"Step '{args.step}' complete in {session_dir}")

if __name__ == "__main__":
    main()
