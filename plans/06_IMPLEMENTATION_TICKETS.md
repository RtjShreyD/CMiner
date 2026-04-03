# Implementation Tickets (Autonomous Execution)

Status legend: TODO | IN_PROGRESS | DONE | BLOCKED

## TKT-001: Style Registry Backend (MVP)
- Status: DONE
- Goal: provide persistent style profile and bundle endpoints for Studio.
- Scope:
  - Add JSON-backed storage under `outputs/library/styles`.
  - Add endpoints: list/get/create profiles, list/create bundles.
  - Validation: required fields and uniqueness.
- Acceptance:
  - API returns deterministic shape.
  - Created records are persisted to disk.

## TKT-002: Character Registry Backend (MVP)
- Status: DONE
- Goal: reusable character pack catalog across sessions.
- Scope:
  - JSON-backed storage under `outputs/library/characters`.
  - Endpoints: list/get/create packs.
- Acceptance:
  - packs persist and are queryable by id.

## TKT-003: API Wiring
- Status: DONE
- Goal: mount new routers and ensure lifespan creates library directories.
- Scope: update `api/main.py` router includes and startup path setup.

## TKT-004: Backend Tests
- Status: DONE
- Goal: validate create/list/get flows for styles and characters.
- Scope: add lightweight unittest suite against pure functions or API TestClient.

## TKT-005: Styles Page (Read-only MVP)
- Status: DONE
- Goal: show style profiles and bundles in web studio.
- Scope: new route/page with API fetch and preview metadata list.

## TKT-006: Characters Page (Read-only MVP)
- Status: DONE
- Goal: show reusable character packs in web studio.
- Scope: new route/page with API fetch and card list.

## TKT-007: Navigation + URL Hierarchy Extension
- Status: DONE
- Goal: add nav links/routes for styles and characters.

## TKT-008: Validation Run
- Status: DONE
- Goal: run lint and unit tests; fix regressions.

## Notes
- This ticket file is updated as each ticket completes.
- Resource optimization focus:
  - JSON-backed storage first (low overhead, no migrations).
  - Versioned schema fields for forward compatibility.

## TKT-009: Agents UI Style/Narration/Character Integration
- Status: DONE
- Goal: move from static dropdowns to registry-backed style and character controls.
- Scope:
  - Add narration mode, style bundle id, character pack id in run payload.
  - Fetch style profiles, style bundles, and character packs from API.
  - Use fetched font/cloud profiles in selectors with fallback options.

## TKT-010: charGen Agent Skeleton and CLI Wiring
- Status: DONE
- Goal: ship first reusable character pack generator agent.
- Scope:
  - Add `agents/charGen/run.py` pack generator.
  - Wire `main.py charGen` command.
  - Smoke-test output in `outputs/library/characters/packs`.
