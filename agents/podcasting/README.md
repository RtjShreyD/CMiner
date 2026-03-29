# Podcasting Agent

A modular, AI-powered pipeline for generating cinematic podcast videos with real-time text clouds and character consistency.

## Overview

The podcasting agent transforms a text script into a full video featuring two characters debating or discussing a topic. It uses Gemini for planning and vision, Edge-TTS for high-quality audio, and FFmpeg for cinematic compositing.

## Usage

### End-to-End Run
To run the entire pipeline automatically from the project root:

```bash
python3 main.py podcasting --prompt "A debate between a surfer and a physicist about the perfect wave."
```

### Modular Step-by-Step Run
For more control, you can execute individual phases of the pipeline. State is persisted in the session directory.

#### 1. Planning Phase
Generates the `storyboard.json`.
```bash
python3 main.py podcasting --prompt "Your prompt" --step planner
```

#### 2. Visual Generation
Generates the base scene and all character alterations based on the storyboard.
```bash
python3 main.py podcasting --step images --session outputs/XXXXXXX/podCasting
```

#### 3. Audio & Timing
Generates TTS audio and precise word-boundary timing metadata.
```bash
python3 main.py podcasting --step audio --session outputs/XXXXXXX/podCasting
```

#### 4. Text Overlays
Generates the transparent PNG frames for the speech bubbles and real-time text.
```bash
python3 main.py podcasting --step clouds --session outputs/XXXXXXX/podCasting
```

#### 5. Final Video Render
Composits all assets into the final `.mp4`.
```bash
python3 main.py podcasting --step video --session outputs/XXXXXXX/podCasting
```

## Advanced Features

### Character & Scene Consistency
The agent now supports uploading your own assets to anchor the generation:
- **Character Images:** Use `--char path/to/char.png` (up to 3).
- **Scene Background:** Use `--scene path/to/background.png`.

When anchored, the planner will derive descriptions from these images, and the generator will use them as a **multimodal reference frame** to maintain perfect consistency in all alterations.

### Script Files
Instead of long command-line prompts, use a script file:
```bash
python3 main.py podcasting --script agents/podcasting/prompt.txt
```

## Configuration

Edit `agents/podcasting/config.json` to switch between models:
- `planner_model`: Model used for storyboarding.
- `character_image_model`: Model used for scene and character generation.
- `character_text_model`: Model used for descriptive text tasks.
- `max_image_generations`: Default set to 15.
