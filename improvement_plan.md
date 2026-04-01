# Improvement Plan: CMiner NarrativeManga + Studio

## 1. Executive Summary

Current codebase: an agentic pipeline (`agents/narrativeManga`) that plans story episodes, generates character/scene art via Gemini image model, synthesizes TTS lines, and stitches video with FFmpeg. Web UI (`web-studio`) currently has a run-only agent console.

Competitor reference: FacelessReels (https://www.facelessreels.com) offers: niche templates, preset visual styles, platform-specific resolutions, voice/music customization, auto-publish integrations, and analytics for viral performance.

Objective: enhance our studio and agents with better quality output, flexible style presets, multi-format video targets, improved continuity, and a more complete UX.

---

## 2. Current Implementation Snapshot

### NarrativeManga pipeline
- `agents/narrativeManga/config.json` contains a fixed `art_style`, 1280x720 resolution, FPS 8, voice pool and model names.
- `EpisodePlanner` produces structured JSON with characters + panels, uses prompt engineering with heavy “return strict JSON” enforcement.
- `CharGen` and `SceneGen` use Gemini image model, include fallback placeholder generation and static prompt constraints.
- `TTSGen` uses Edge-TTS, per-character assigned voice keys; no music or voice morphing.
- `MovieMaker` constructs panel segments using FFmpeg and concatenates; minimal transition strategies.

### Studio UI
- `web-studio/src/pages/Agents.jsx`: start/stop agents, log stream, no per-agent configuration or format/profile selection.

### Strengths
- Clear modular pipeline steps (plan, chars, scenes, audio, clouds, video).
- Logic for reuse/resume via existing files.
- Character consistency intent (same visual_prompt across episodes and anchor image usage).

### Limitations
- Single resolution/aspect ratio and low-quality defaults for social reels.
- No style/voice preset configuration in UI.
- No best-practice “viral hook” story templates or content analysis.
- No post-generation publishing workflow, analytics instrumentation, or user feedback loop.

---

## 3. Competitor Feature Insights

FacelessReels differentiators:
- Preset workflows (e.g., "Scary stories", "History", "Mythology")
- Multi-platform resolution presets with auto crop and thumbnail generation
- Voice, music, text-to-speech selection (clear personas)
- Autopost (TikTok, Instagram, YouTube) + analytics to track views
- UX focus on non-technical creator experience (simple 3-step flow)

---

## 4. Gap Analysis and Potential Moves

### 4.1. Presets & workflow templates

- Add `config.json` blocks:
  - `themes` (niche templates + seed prompts)
  - `art_styles` (styles + model instructions)
  - `output_presets` (TikTok, Reels, Shorts, Story) with `resolution`, `fps`, `duration_limit`.

- In `EpisodePlanner`, incorporate `theme` as prompt input and clamp plot archetype to well-performing rails (e.g., hook/anticipation/punchline).
- Provide end-user selection in UI: a dropdown for niche + style + aspect.

### 4.2. Image generation quality

- Add config param `image_model_mfa` (e.g., `models/gemini-2.5-...` plus optional Real-ESRGAN upscaling in post).
- In `CharGen` / `SceneGen`:
  - store and re-use prompt tokens / reference images to guarantee continuity.
  - switch from hardcoded 16:9 string to dynamic aspect in `prompt`.
  - implement “consistency prompt injection”: explicit `character_id`, `color palette`, `lighting references`.
  - consider using a separate validation stage: request 2-3 candidates and quality-select using CLIP score.

### 4.3. Audio / voice upgrade

- Expand `tts_voices_pool` in `config.json` with categories (narrator, hero, villain, etc.) and a “voice profile” metadata.
- Add optional background music + SFX: repo output can select from a folder or stock library and mix with FFmpeg in `MovieMaker`.
- Add advanced TTSD utilities: voice style descriptors, speed/pitch control, language auto-detect.

### 4.4. Output formats, media lifecycle

- Provide pipeline flags: `--format=tiktok|instagram|youtube|story` in `run.py`. Map to preset `resolution`, `fps`, `aspect`.
- `MovieMaker` to produce:
  - main MP4
  - stripped preview MP4 (lower weight)
  - thumbnails (auto capture frame)
  - metadata JSON for social post caption, hashtags, platform tags.

### 4.5. UX and controls

- In `web-studio`, add a form for narrative options:
  - `Theme`, `Style`, `Episode length`, `Panel density`, `Format`
  - `Character archetypes` + `voice profile`
  - `Music selection` + `transitions`
- Add campaign dashboard (sessions list + metrics): hooks in `api/models/routers/sessions.py` and `studio/screens/session_explorer.py`.

### 4.6. Data + feedback loop

- Instrument pipeline to record quality indicators in `session_state.json`: generation cost, model confidence, LLM usage, failure counts, prompt revisions.
- Add manual rating UI per episode; store in DB for “best performing” style templates.
- Experiment in `agents/narrativeManga/chains/episode_planner.py` with optional “rewriting prompt using previous episode performance” to provide iterative improvement.

---

## 5. Practical 90-Day Roadmap

### Phase 1 (week 1-2): foundational controls

1. Add `preset` + `format` config in `agents/narrativeManga/config.json`.
2. Extend `run.py` flags (`--preset`, `--format`, `--art_style`, `--tts_voice_pool`).
3. Update `CharGen`/`SceneGen` prompts for dynamic aspect and style.
4. Update UI `Agents.jsx` to pass body payload to `/api/agents/run`.

### Phase 2 (week 3-5): quality enforcement + style anchors

1. Add optional multi-candidate and quality scoring in image loops.
2. Add anchor store in session (e.g., `chars/anchor.json`) with face embedding or shot attributes.
3. Implement post-upscale using `Real-ESRGAN` or `waifu2x` and integrate into final manifest.
4. Add TTS voice category and background music layers in `MovieMaker`.

### Phase 3 (week 6-10): platform publishing and performance

1. Add output presets to `MovieMaker` (110 vertical crop, 1:1, etc.) and generate multi-size outputs per run.
2. Create DB schema for “style templates” + ratings + view counts (reuse `api/models` directory, maybe sqlite or Mongo in existing repo style).
3. Build session explorer with filtering by labels and best templates.

### Phase 4 (week 11-12): optimization and marketing differentiation

1. Compare generated output via test benchmarks (upload to local analytics and compute engagement proxies, maybe using simple heuristic: caption length, pacing, panel text density).
2. Add “viral hook” writer module in `EpisodePlanner` with a list of proven formulas.
3. Create a quick onboarding 3-step guided UI like FacelessReels.

---

## 6. Quick wins (low-effort, high-impact)

- Expose `art_style` and `preset` in UI and config.
- Add resolution presets for 9:16 + 1:1 in run script and FFmpeg generation path.
- Use “character color palette / face attributes” in prompts to reduce drift.
- Add fallback safe render with a style-laden image prompt and higher quality model (if available).
- Add `--no-txt-overlay` and `--enable-music` flags for quick audio quality difference.

---

## 7. Code pointers for immediate action

- `agents/narrativeManga/config.json` (add presets, voice categories, output_specs)
- `agents/narrativeManga/run.py` (parse new CLI flags, apply them to planners/generators)
- `agents/narrativeManga/chains/episode_planner.py` (theme template + viral hook prompt helper)
- `agents/narrativeManga/chains/char_gen.py` / `scene_gen.py` (dynamic aspect, style anchors, multi-candidates + selection)
- `agents/narrativeManga/chains/moviemaker.py` (multi-size outputs, music mixing, caption metadata)
- `web-studio/src/pages/Agents.jsx`, `studio/screens/session_explorer.py` (UI configuration & analytics)

---

## 8. Success Metrics

- Render quality: less “placeholder fallback” and fewer mismatched characters in scene.
- Consistency: same character identity across episodes using strict `visual_prompt` + anchor images.
- Format coverage: generated outputs in at least 3 platform specs (9:16, 1:1, 16:9).
- UX: user can choose and save 5 style presets in UI.
- Feedback: track user ratings, and on first month use at least one data-driven template improvement.

---

## 9. Risks + mitigations

- Model drift / non-deterministic outputs
  - Mitigation: use multi-shot prompt anchors + top-K candidate filtering + local embedding consistency checks.
- High cost for multistep generation
  - Mitigation: limit chars/panels, use adaptive resolution (draft vs final), and optionally cache generated assets.
- API cutoff / rate limit
  - Mitigation: introduce a token bucket queue and fallbacks for degraded mode.

