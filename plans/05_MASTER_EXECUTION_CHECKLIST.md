# Master Execution Checklist: Style + Character Reuse Program

## Program Goal
Upgrade CMiner into a preview-first reusable-assets studio with higher quality narration styling and character consistency.

## Track A: Foundation (Week 1-2)
- [ ] Define style profile schema and bundle schema.
- [ ] Define character pack schema and library directory.
- [ ] Add migration-safe storage under outputs/library.
- [ ] Add backend API skeletons for styles and characters.
- [ ] Add URL hierarchy support for style/character routes.

## Track B: Style Library MVP (Week 2-4)
- [ ] Build style registry service (read/write/list/version).
- [ ] Ingest initial font set with license metadata.
- [ ] Implement subtitle style templates (ASS presets).
- [ ] Implement cloud SVG template set (speech/thought/shout).
- [ ] Build static preview card generation job.
- [ ] Build style browser UI with filters and search.

## Track C: Narration UX Upgrade (Week 3-5)
- [ ] Add narration mode control in Agents UI.
- [ ] Add font/cloud/style selectors with sample previews.
- [ ] Add style compare drawer (A/B preview).
- [ ] Extend run payload with style bundle + narration mode.
- [ ] Persist style assignments per session.

## Track D: charGen and Character Library (Week 4-7)
- [ ] Create charGen agent skeleton and CLI/API entry.
- [ ] Generate character packs with manifest + previews.
- [ ] Publish character packs into global library.
- [ ] Add character library browsing UI.
- [ ] Add character pack picker in agent config.
- [ ] Inject selected pack into narrativeManga/podcasting pipelines.

## Track E: Preview Pipeline and Quality (Week 6-8)
- [ ] Generate short sample videos for style bundles.
- [ ] Add contrast/readability quality checks.
- [ ] Add fallback style safety rules for low-contrast scenes.
- [ ] Add session preview snapshots for QA comparison.

## Track F: Reuse and Governance (Week 8-10)
- [ ] Add style deprecation/version policy.
- [ ] Add character pack ownership and edit history.
- [ ] Add import/export for styles and character packs.
- [ ] Add tags and recommendation logic (popular/recent/high-rated).

## Track G: Performance and Reliability
- [ ] Cache preview assets and invalidate by profile version.
- [ ] Add async job queue for preview generation.
- [ ] Add health checks for rendering dependencies.
- [ ] Add API integration tests for registry operations.

## Product Acceptance Criteria
- [ ] User can browse and preview style presets before run.
- [ ] User can choose narration mode and subtitle/cloud style.
- [ ] User can generate and reuse character packs across sessions.
- [ ] Agent routes preserve session context in browser URLs.
- [ ] Generation quality measurably improves (readability and consistency).

## Metrics to Track
- Style preset adoption rate.
- Preview-to-run conversion rate.
- Character reuse rate across sessions.
- Subtitle readability pass rate.
- User-rated output quality.
