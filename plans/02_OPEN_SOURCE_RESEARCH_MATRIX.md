# Open Source Research Matrix for Styling and Preview

## Goal
Identify efficient open-source tools for:
- Font management and previews
- Subtitle and speech cloud rendering
- Style presets and reusable assets
- Image style prompting and consistency helpers
- Character reuse metadata + embedding/index workflows

## Candidate Stack (Recommended)

### A. Fonts and Typography
1. fonttools
- Use: inspect font metadata, subsets, validation.
- Why: reliable for processing custom font packs.

2. HarfBuzz + Pango (or Pillow fallback)
- Use: robust multilingual text shaping and layout.
- Why: better than naive text rendering when adding language support.

3. Google Fonts (source catalog, not runtime dependency)
- Use: curated open-license font library ingestion pipeline.
- Why: high-quality legal font source with predictable metadata.

### B. Subtitle Rendering and Effects
1. FFmpeg + libass
- Use: subtitle overlays, style, positioning, transitions.
- Why: production-proven and fast for video composition.

2. pysubs2
- Use: manipulate ASS/SRT subtitle files programmatically.
- Why: easier style template generation than hand-authoring ASS.

3. whisperX (optional for alignment)
- Use: higher-quality word timestamps for narration sync.
- Why: improves subtitle pacing and readability.

### C. Speech/Thought Cloud Rendering
1. Pillow + OpenCV
- Use: draw cloud shapes, tails, borders, compositing.
- Why: already aligned with current stack and easy to customize.

2. svgwrite + CairoSVG
- Use: cloud templates authored as SVG and rasterized for overlays.
- Why: cleaner reusable cloud templates with scalable quality.

3. rembg / segmentation helpers (optional)
- Use: place clouds behind foreground subjects when needed.
- Why: improves visual quality for stylized manga compositions.

### D. Style/Prompt Libraries for Image Generation
1. Prompt registry JSON + tag taxonomy
- Use: store style prompt recipes (lighting, camera, palette).
- Why: deterministic style retrieval and updates.

2. CLIP-based similarity scoring (optional)
- Use: evaluate generated preview fit to target style examples.
- Why: objective quality check before style publication.

3. ComfyUI style workflows (optional integration)
- Use: experimental style preview generation via node workflows.
- Why: strong ecosystem for reusable visual style pipelines.

### E. Character Reuse and Retrieval
1. InsightFace or face embeddings (optional)
- Use: identity similarity checks across generated character portraits.
- Why: aids consistency and reusable character packs.

2. FAISS / lightweight vector index
- Use: nearest-style/character retrieval from preview library.
- Why: future search capability for "similar style" and "similar character".

## Competitive UX Signals to Borrow
- Canva/Figma-like preset card browsing with immediate previews.
- CapCut-like subtitle style panel with one-click apply.
- Midjourney/ComfyUI-style prompt style slots and reusable snippets.

## Legal and Licensing Rules
- Store license metadata for each font/style asset.
- Restrict ingestion to open-license assets (OFL, Apache, MIT, CC variants as allowed).
- Preserve attribution fields where required.

## Recommended MVP Tool Choices
- Subtitle effects: ffmpeg + libass + pysubs2.
- Cloud effects: SVG templates + Pillow/OpenCV compositing.
- Font library: Google Fonts ingestion + fonttools validation.
- Style preview clips: ffmpeg render templates.

## Research-to-Implementation Checklist
- Evaluate rendering speed on 3 target formats (9:16, 16:9, 1:1).
- Validate multilingual sample support in preview cards.
- Verify quality and legibility against 20 sample backgrounds.
- Confirm licensing metadata exists for every imported asset.
