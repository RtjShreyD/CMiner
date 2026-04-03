# Style Preview Library Architecture Plan

## Objective
Build a reusable style library system that supports preview + selection for:
- Text narration style: subtitle, speech cloud, thought cloud.
- Typography style: fonts, stroke/shadow, spacing, animation behavior.
- Image/render style: art presets and generation prompt presets.
- Future reuse assets: character style packs and scene motifs.

This system must be:
- Session-independent (global library + versioned presets).
- Discoverable in Studio UI with sample previews.
- Extendable from backend pipelines with new style entries.

## Core Product Features
1. Style catalog browser in Studio
- Filter by category: font, cloud, subtitle, render, character style.
- Filter by tags: manga, noir, horror, sci-fi, minimal, kids, cinematic.
- Search by name and tag.

2. Preview-first selection
- Font preview cards with pangram + multilingual sample.
- Text cloud preview cards (speech/thought/shout variants).
- Mini composition preview in FilePreview area.
- Side-by-side compare mode (A/B).

3. Narration mode control
- Narration mode enum:
  - subtitles_only
  - speech_clouds_only
  - thought_clouds_only
  - hybrid_subtitles_clouds
- Per-character override (optional) for voice + cloud style.

4. Preset bundles
- One-click style bundles (e.g., "Cinematic Anime", "Noir Investigator", "Lo-fi Slice").
- Bundle contains font family, cloud template, color palette, subtitle behavior, and render prompt style.

5. Reuse across sessions
- Selected style profile stored in:
  - session metadata (snapshot)
  - global profile registry (source of truth)

## Proposed Data Model

## style_profiles table (or JSON registry)
- id
- name
- category (font|cloud|subtitle|render|character_style|bundle)
- version
- tags[]
- status (active|deprecated|experimental)
- preview_assets
  - thumbnail
  - sample_video
  - sample_json
- config_json
- created_by
- created_at
- updated_at

## style_bundles table
- id
- name
- font_profile_id
- cloud_profile_id
- subtitle_profile_id
- render_profile_id
- character_style_profile_id (optional)
- preview_asset
- notes

## session_style_assignment
- session_id
- agent_id
- style_bundle_id
- narration_mode
- overrides_json

## Architecture Components
1. Backend services
- style_registry_service
  - CRUD style entries
  - versioning + validation
- preview_generation_service
  - create style previews from templates
  - generate thumbnail/video snippets
- style_assignment_service
  - apply selected profile into run payload

2. API endpoints
- GET /api/styles
- GET /api/styles/:id
- GET /api/styles/categories
- GET /api/styles/bundles
- POST /api/styles (admin or pipeline)
- POST /api/styles/preview/regenerate
- POST /api/sessions/:id/style-assignment

3. Frontend components
- StyleLibraryPage
- StyleCard
- StyleCompareDrawer
- NarrationModeSelector
- StylePreviewPane integration with FilePreview

## Preview Generation Pipeline
1. Static preview generation
- Produce PNG/JPG cards for each style with fixed template text.

2. Dynamic preview generation
- Generate 5-10 second sample clip overlaying subtitles/clouds on sample frame.
- Render representative cloud geometry and animation.

3. Validation
- Ensure text legibility score via contrast checks.
- Verify subtitle safe-area constraints for 9:16, 16:9, 1:1.

## Integration into Agents UX
1. Agent form sections
- Narration Mode
- Font Style
- Cloud Style
- Preset Bundle
- Preview selected style button

2. FilePreview behavior
- If style asset selected -> show sample media.
- If style config selected -> show formatted JSON + preview links.

3. Run payload extension
- narration_mode
- style_bundle_id
- style_overrides

## Incremental Delivery Phases
Phase 1: Registry + static preview cards
Phase 2: Dynamic sample clips + bundle assignment
Phase 3: Compare mode + quality scoring + recommendation

## Risks and Mitigation
- Too many styles -> decision paralysis:
  - Mitigate with curated featured bundles and default recommendations.
- Inconsistent readability across backgrounds:
  - Mitigate with automated contrast lint + fallback style rules.
- Slow preview generation:
  - Mitigate with cached previews and async background jobs.

## Definition of Done
- User can browse styles with visual samples.
- User can pick narration mode + preset bundle in Agents UI.
- Selection persists and is reusable in different sessions.
- Previews are generated and visible without manual file handling.
