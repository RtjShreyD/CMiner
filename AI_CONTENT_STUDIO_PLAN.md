# CMiner: AI Terminal-Based Content Studio (Roadmap)

This document outlines the architecture, tooling, and development phases required to evolve CMiner from a command-line script framework into a fully-fledged **Terminal User Interface (TUI) Content Creation Studio**, akin to Claude-Code or Open-Code, but specialized for multimodal AI asset generation.

## 1. Core Vision & Requirements
- **Unified TUI**: A beautiful, responsive terminal interface to replace standard terminal outputs.
- **Multimodal Media Viewing**: Ability to preview images, listen to generated TTS, and watch final MP4 renders directly inside or launched from the terminal.
- **Agent & Session Management**: A dashboard to switch between agents (NarrativeManga, Newsdesk, Podcasting), view historical sessions, and resume interrupted pipelines.
- **Asynchronous & Scheduled Execution**: Run pipelines in the background, run multiple agents in parallel, and schedule tasks (e.g., "Run Newsdesk every morning at 6 AM").
- **Basic A/V Editing**: Trim, concatenate, or mute clips directly from the TUI before finalizing the stitch.

---

## 2. Technology Stack Recommendations

### A. Terminal User Interface (TUI) Framework
**Recommendation:** **[Textual](https://github.com/Textualize/textual)** (Python)
- *Why:* It is the modern standard for Python TUIs (built by the creator of `Rich`). It natively supports CSS-like styling, reactive layouts, async event loops, and is capable of building complex layouts (sidebars, tabs, modals) that feel like a web app.
- *Alternative:* `prompt_toolkit` (great for REPLs, but less structured for complex application layouts).

### B. Media Viewing in the Terminal
Rendering media in a terminal is technically constrained, but achievable with modern tools:
- **Images:** Use **`rich-pixels`** or **`textual-imageview`** to convert image arrays into half-block characters (ANSI colors). Alternatively, integrate **`chafa`** (a highly optimized terminal graphics tool) as a subprocess.
- **Audio:** Textual doesn't do audio natively. Bind TUI keys (e.g., `<Space>`) to spawn **`ffplay -nodisp`** or use **`pygame.mixer`** / **`simpleaudio`** run in a non-blocking asyncio thread.
- **Video:** 
  - *Option 1 (True TUI):* Decode frames with `OpenCV` and render them using `chafa` / `rich-pixels` inside a Textual widget. This is computationally expensive but very "hacker aesthetic".
  - *Option 2 (Practical):* TUI acts as the orchestrator; pressing `[Enter]` on a video file spawns an overlayless **`mpv`** window synced to the TUI.

### C. Background Jobs & Scheduling
- **Parallel Execution:** Use Python's native `asyncio` combined with Textual's `Worker` API to run lengthy generation pipelines (like Gemini API calls) without freezing the UI.
- **Job Queues (Cron/Scheduling):** 
  - For standalone execution: **`APScheduler`** (Advanced Python Scheduler). It integrates perfectly with `asyncio` and can handle cron-style jobs (e.g., `CronTrigger(hour=6, minute=0)` for the Newsdesk agent).
  - *If scaling up:* Switch to `Celery` with a local Redis/RabbitMQ instance, though this may violate the "local terminal app" feel. `APScheduler` backed by a SQLite database is preferred for a standalone CLI tool.

### D. Generic Audio/Video Editing
- **Engine:** **`ffmpeg-python`** (a wrapper for FFmpeg).
- **TUI Implementation:** Create a Textual `Screen` that acts as a basic timeline or form. 
  - Fields for: `Trim Start`, `Trim End`, `Crop`, `Volume Boost`.
  - When the user hits "Apply", the TUI spawns an async FFmpeg subprocess with progress bars mapped to Textual's `<ProgressBar>` widget.

---

## 3. Architecture & Layout Design

The application will launch via `cminer` or `python3 main.py --tui`.

### Proposed Layout
```text
┌─────────────────────────────────────────────────────────────────────────┐
│ CMINER STUDIO ⚡ 1 Active Job    [Dashboard] [Agents] [Media] [Config]    │
├───────────────┬─────────────────────────────────────────────────────────┤
│ 📂 SESSIONS   │ 🎬 AGENT: NarrativeManga                                │
│ ▼ manga_001   │                                                         │
│   ├─ chars    │  Status: [|||||||||||||||||||      ] 70% Scene Gen      │
│   ├─ scenes   │  Budget: 12/50 Images Used                              │
│   └─ output   │                                                         │
│ ▶ news_daily  │  [Pause]  [Cancel]  [View Logs]                         │
│ ▶ pod_tech    │                                                         │
├───────────────┼─────────────────────────────────────────────────────────┤
│ 🛠️ TOOLS     │ 🖼️ MEDIA PREVIEW (textual-imageview / chafa)            │
│  [New Agent]  │                                                         │
│  [Scheduler]  │      ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿      │
│  [A/V Editor] │      ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿      │
│               │                                                         │
└───────────────┴─────────────────────────────────────────────────────────┘
```

## 4. Phased Implementation Plan

### Phase 1: Core TUI & Session Explorer (Foundation)
- Install `textual`.
- Wrap the existing CMiner runner logic in a Textual App.
- Build a dual-pane layout: A file tree on the left (reading `outputs/`) and a console/log view on the right.
- Move print statements to a Textual `RichLog` widget.

### Phase 2: Agent Orchestration & Async Workers
- Refactor the `run.py` executions to yield progress updates (e.g., `yield {"step": "chars", "progress": 2/4}`).
- Implement Textual Workers to consume these yields and update a UI `<ProgressBar>`.
- Add play/pause functionality using task cancellation.

### Phase 3: Media Previews & A/V Editing
- Integrate `rich-pixels` to allow clicking on an image in the session tree and displaying it in the right pane.
- Build a generic FFmpeg wrapper form screen. Let users right-click a `.mp4` or `.mp3` and select "Edit", opening a form to input trim timestamps, which then spawns an FFmpeg trim command.

### Phase 4: Schedulers & Daemons (Cron)
- Integrate `APScheduler`.
- Create a "Scheduler" tab in the TUI.
- Let users configure cron syntax for specific agents (e.g., "Run NewsAligator --hours 24 every day at 08:00").
- Have the APScheduler run in a background thread of the main TUI loop.

---

## 5. Next Steps

When you are ready to begin, we will:
1. `pip install textual rich-pixels apscheduler ffmpeg-python`
2. Create a new entry point, e.g., `studio.py`, to keep the standard CLI (`main.py`) intact while we build the TUI.
3. Begin Phase 1 by bootstrapping the Textual App shell.
