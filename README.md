# CMiner: Multi-Agent Podcast & Analysis Suite

CMiner is a powerful multi-agent framework designed for high-quality automated content generation. It currently features specialized agents for cinematic podcasting and automated news analysis.

## 🚀 Quick Start

### 1. Prerequisites
- **Python:** 3.10+
- **FFmpeg:** Required for video compositing and audio processing.
  ```bash
  # Linux
  sudo apt update && sudo apt install ffmpeg
  ```

### 2. Setup Environment
Clone the repository and initialize the virtual environment:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. API Configuration
Create a `.env` file in the root directory and add your Google Gemini API key:

```env
GOOGLE_API_KEY=your_gemini_api_key_here
```

## 🤖 Agents

All functionality is accessible via the root `main.py` entry point.

### Podcasting Agent
Generates cinematic text-to-video podcasts with character consistency and real-time text clouds.

#### 🏁 End-to-End
```bash
python3 main.py podcasting --prompt "A debate about AI ethics"
```

#### 🏗️ Step-by-Step
Execute individual phases to review or refine intermediate outputs. State is persisted in your session directory (found in `outputs/`).

1. **Plan:** `python3 main.py podcasting --prompt "Your topic" --step planner`
2. **Images:** `python3 main.py podcasting --step images --session outputs/XXXXXXX/podCasting`
3. **Audio:** `python3 main.py podcasting --step audio --session outputs/XXXXXXX/podCasting`
4. **Overlays:** `python3 main.py podcasting --step clouds --session outputs/XXXXXXX/podCasting`
5. **Render:** `python3 main.py podcasting --step video --session outputs/XXXXXXX/podCasting`

> [!TIP]
> Use the **`--session`** flag (e.g., `--session outputs/1234567/podCasting`) to continue or re-run specific steps on an existing generation without starting over.

*See [agents/podcasting/README.md](agents/podcasting/README.md) for advanced modular usage and asset injection.*

### Newsdesk Agent
Automates news gathering and analysis reports.

```bash
python3 main.py newsdesk --agent newsaligator --hours 24
```

## 📂 Project Structure

- `agents/`: Contains specialized autonomous agents.
  - `podcasting/`: Cinematic video generation pipeline.
  - `newsdesk/`: News analysis and reporting.
- `main.py`: The unified CLI entry point for all agents.
- `outputs/`: Default directory for session-based generation results.
- `config.json`: Global configuration for the framework.

## 🛠️ Development

To add a new agent:
1. Create a directory in `agents/`.
2. Implement your logic with standard input/output patterns.
3. Register the agent in `main.py`.

---
*Built with ❤️ using Google Gemini & Advanced Agentic Coding.*
