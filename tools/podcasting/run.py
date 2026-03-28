#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Fix path to allow importing from local directory if needed
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))


from tools.podcasting.utils import ensure_session_outputs
from tools.podcasting.planner import Planner
from tools.podcasting.character_gen import CharacterGen
from tools.podcasting.tts_gen import TTSGen
from tools.podcasting.video_creator import VideoCreator


def main():
    parser = argparse.ArgumentParser(description="Podcasting Text-to-Video Pipeline Runner")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--agent", default="podcaster", help="Agent ID")
    parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary")
    parser.add_argument("--prompt", required=True, help="User prompt")
    parser.add_argument("--thinking", default="high", help="Thinking level")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    session_dir = ensure_session_outputs(workspace)
    
    print(f"Session directory: {session_dir}")

    # 1. Planner
    planner = Planner()
    storyboard = planner.run(args.prompt, session_dir)
    
    # 2. Character Generation
    char_gen = CharacterGen()
    char_map = char_gen.run(storyboard, session_dir)
    
    # 3. TTS Generation
    tts_gen = TTSGen()
    audio_files = tts_gen.run(storyboard, session_dir)
    
    # 4. Video Creation
    video_creator = VideoCreator()
    final_video = video_creator.run(storyboard, char_map, audio_files, session_dir)
    
    print(f"Task Complete. Final Output: {final_video}")

if __name__ == "__main__":
    main()
