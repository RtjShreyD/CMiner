# Studio UX Workflow Plan (with URL Hierarchy)

## Objective
Design a predictable, high-speed UX where page state is represented in URL and reusable assets are easy to discover.

## URL Hierarchy Standard

## Existing pages
- /sessions
- /agents

## Extended hierarchy (proposed)
- /agents/{agentId}/{sessionMode}
- /agents/{agentId}/{sessionMode}/{sessionId}
- /styles
- /styles/{category}
- /styles/{category}/{styleId}
- /characters
- /characters/{packId}

## Why this matters
- Deep links for collaboration and QA.
- Browser back/forward consistency.
- Better multi-session tracking and debugging.

## Agents Workflow UX
1. Select agent -> URL updates.
2. Choose new/existing mode -> URL updates.
3. Choose existing session -> URL updates with session id.
4. Session file tree panel follows selected URL context.

## Style Workflow UX
1. Open style library page.
2. Filter and compare style presets.
3. Open style detail route.
4. Apply style to current agent route and persist selection.

## Character Workflow UX
1. Open character library page.
2. Preview pack and character cards.
3. Attach selected pack to current agent route.

## Cross-page state persistence
- Keep selected style bundle and character pack in query params when useful:
  - ?styleBundle=cinematic-anime-v2
  - ?characterPack=pack_kaelen_core
- Save authoritative assignment in session metadata on run.

## UX Quality Principles
- Preview-first decisions (small card -> larger preview -> apply).
- 2-click maximum to select style or character pack from lists.
- No hidden state: always visible current session, style bundle, narration mode.

## Suggested New UI Components
- BreadcrumbRouteBar
- SessionContextChip
- StyleBundlePicker
- NarrationModePicker
- CharacterPackPicker
- ApplyToRunSummary card

## Definition of Done
- Every major user decision is reflected in URL.
- Reloading browser preserves agent/session context.
- Users can move across Sessions, Agents, Styles, and Characters without losing selection state.
