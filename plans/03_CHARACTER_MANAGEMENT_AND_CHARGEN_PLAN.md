# Character Management System + charGen Agent Plan

## Objective
Create a reusable character management workflow where users can:
- Generate characters independently (without full episode generation).
- Save and organize character packs.
- Reuse characters across sessions and across multiple agents.
- Preview and select characters from a central library.

## New Agent: charGen

## Scope
- Agent name: charGen
- Purpose: generate only character assets and character metadata.
- Output: reusable character pack stored in shared library and optional session snapshot.

## CLI/API contract
- Input:
  - prompt
  - style preset / render style
  - character count
  - archetype tags (hero, villain, mentor, comic relief)
  - gender/age/costume hints (optional)
- Output:
  - character portraits
  - variants
  - metadata JSON (identity + visual prompt + style tags)
  - embedding vectors (optional for similarity search)

## Directory Strategy

## Global reusable library (new)
- outputs/library/characters/{character_pack_id}/
  - manifest.json
  - cards/
  - turnarounds/
  - anchors/
  - previews/

## Session snapshot (current behavior compatibility)
- outputs/{session_id}/{agent_id}/chars/
  - links or copies to selected global character pack assets

## Character Data Schema
- character_id
- display_name
- archetype
- visual_prompt
- style_profile_id
- anchor_images[]
- color_palette
- voice_profile_default
- tags[]
- quality_score
- created_at
- source_agent (charGen|AutoAnimator|other)

## Character Reuse Workflow
1. Generate pack with charGen.
2. Publish pack to global character library.
3. In any agent run, choose:
  - generate fresh characters
  - import from character library
  - hybrid (reuse main cast + generate side characters)
4. During generation, inject selected character anchors and metadata.

## Studio UX Additions
1. Character Library screen
- Grid/list of character packs.
- Filters by style/archetype/tags.
- Preview card + expression variants.

2. Agent config section
- Character source selector:
  - New generation
  - Existing pack
  - Mixed mode

3. FilePreview integration
- Selecting character pack JSON shows manifest + thumbnails.
- Selecting image previews full character card.

## Backend/API Additions
- GET /api/characters/packs
- GET /api/characters/packs/:id
- POST /api/characters/packs (create from charGen run)
- POST /api/characters/packs/:id/publish
- POST /api/agents/run with character_pack_id

## Generation Quality Controls
- Multiple candidate portraits per character, choose best by consistency score.
- Optional expression set generation (neutral, happy, angry, shocked).
- Optional turnaround variants (front/3-4/profile).

## Migration Plan
1. Keep existing AutoAnimator chars output behavior.
2. Add charGen pipeline without breaking existing flow.
3. Add optional import path from library in AutoAnimator and podcasting.

## Definition of Done
- charGen runs standalone and creates reusable pack.
- Pack can be selected in other agents.
- Character consistency improves measurably across sessions.
