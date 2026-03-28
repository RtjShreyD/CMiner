# Developer Instructions (Copilot + LLM Workflow)

These instructions are for contributors and coding agents working in this repository.
They define how to build and evolve features safely and consistently.

## 1) Environment and Execution

	- `/home/rtj/Krsna/CMiner/.venv/bin/python`
	- `/home/rtj/Krsna/CMiner/.venv/bin/pip`
# Developer Instructions (CMiner)

These instructions define how contributors and coding agents should build features in this workspace.

## 1) Environment

- Always use `/home/rtj/Krsna/CMiner/.venv/bin/python`.
- Always use `/home/rtj/Krsna/CMiner/.venv/bin/pip`.
- Do not rely on global Python packages.

## 2) Workspace Architecture

- Treat CMiner as the AI Studio root that manages all agents via root CLI.
- Root entrypoint must be `main.py` and should route to specific agents.
- Keep architecture strict:
	- `claws/` = shared external integrations (browser, APIs, etc.)
	- `tools/` = generic reusable tools only (filesystem, serialization, common helpers)
	- `agents/<agent-name>/src/` = agent runtime code (flattened, no repeated nested name directory)
	- `agents/<agent-name>/src/tools/` = agent-local tools (domain-specific only)
	- `agents/<agent-name>/src/chains/` = chain modules used by that agent
	- `agents/<agent-name>/config/` = agent-local configs such as source registries
	- `agents/<agent-name>/prompts/` = reusable prompt templates

## 3) Naming and Layout Rules

- Do not create multiple directory levels with the same name (for example `src/news_aligator`).
- Keep each module focused and avoid very large files.
- Use clear names aligned with responsibility.

## 4) Agent-Orchestration Pattern

- Use LangGraph/LangChain as orchestration standards.
- Prefer a robust iterative loop design with explicit stop conditions:
	1. research
	2. execute tool actions
	3. validate policy and store artifacts
	4. summarize progress
	5. continue or finalize
- Ground all progress on tool outputs and persisted artifacts.
- Include iteration limits and guardrails to avoid uncontrolled loops.

## 5) Prompt and Model Guidance

- Store system prompts in `prompts/` files; do not hardcode long prompts in runtime modules.
- Use `.env` model credentials through config loading.
- If model calls fail, provide deterministic fallback behavior.

## 6) Browser Claw Expectations

- Browser actions must be explicit and auditable:
	- web search
	- open URL/new tab
	- list/switch tabs
	- scroll/click
	- extract content
	- download assets
- Respect terms, robots, and source restrictions.
- Do not implement paywall bypassing or unauthorized access.

## 7) Tools Separation

- Root `tools/` must remain generic and reusable across all agents.
- News-specific source logic belongs only in `agents/newsAligator/src/tools/`.

## 8) Testing Requirements

- Always add and run tests.
- For agent graphs, include:
	- planning/chain behavior tests
	- one end-to-end run with fake claw/tool adapters
	- policy block path tests
	- artifact persistence checks

## 9) Cleanup and Delivery

- Remove unused files and stale artifacts (like old egg-info) when no longer needed.
- Keep changes incremental, verifiable, and logged via tests/runtime checks.
	- `claws/`: external integrations agents can operate (browser, APIs, etc.)
	- `tools/`: shared pure utilities, source registries, policy helpers, storage helpers
	- `agents/`: LLM workflows/orchestration that compose claws and tools
- New features must include:
	- Domain models
	- Service/tool layer
	- Orchestration layer (if applicable)
	- Tests

## 3) Agent Development Conventions

- Keep each agent isolated in its own directory under `agents/`.
- Do not modify unrelated agent directories when implementing a feature.
- Do not hardcode long system prompts directly in agent implementation files.
- Store reusable prompts in a dedicated `prompts/` directory and load them from code.
- Design agent workflows to support deterministic fallback when LLM output is unavailable.
- Agents must import integrations from top-level `claws/` and shared helpers from top-level `tools/`.
- Do not duplicate integration logic inside an individual agent if a shared claw/tool already exists.

## 4) LangChain and LangGraph Guidance

- Treat LangGraph/LangChain as workspace-level standards for orchestration and LLM interaction.
- Prefer explicit state models and typed node inputs/outputs.
- Use LangGraph for orchestration, routing, and loop control.
- Keep node logic small and testable.
- Add policy/compliance checks as first-class nodes or guard functions.
- Capture execution logs and persist run artifacts for observability.
- Keep side effects (network, browser, filesystem) inside claws or tool functions, not in graph-routing code.

## 5) Browser Automation Claw Guidelines

- Browser actions must be explicit and auditable:
	- open page
	- search web
	- scroll
	- click
	- open new tab
	- switch/list tabs
	- extract content
	- download assets
- Use allowlists and policy guards before fetching remote content.
- For media downloads, validate reusable license metadata before writing files.
- Preserve provenance (source URL, timestamp, attribution, license) with artifacts.
- Browser claw implementations should be placed under `claws/browser/` and exposed through a narrow protocol/interface.

## 6) Quality Standards

- Add docstrings for public functions, classes, and complex helpers.
- Write concise comments only where logic is non-obvious.
- Run formatting/linting when configured by the feature scope.

## 7) Testing Requirements

- Always add unit tests for new behavior.
- Test both success paths and policy/error paths.
- Prefer fast tests with mocks/fakes for external systems (browser, APIs, network).
- Basic local validation is required before marking work complete.
- For graph-based agents, test at least:
	- planning node output shape
	- one end-to-end graph run with fake claws/tools
	- policy block paths (disallowed source/license)
	- artifact persistence under `outputs/` or configured output directory

## 8) Dependency Management

- Install only legitimate, necessary packages.
- Keep dependencies minimal and relevant to the feature.
- Configure workspace-shared dependencies in root `pyproject.toml`.
- Agent-specific dependencies belong in that agent's own metadata only when truly isolated.

## 9) Safety and Compliance

- Respect robots, terms of service, and source restrictions.
- Never implement paywall bypassing or unauthorized access patterns.
- Treat "free to view" and "free to reuse" as different; require explicit reuse license for asset downloads.

## 10) Delivery Expectations

- Provide small, incremental, verifiable changes.
- Include a short run/test note in feature documentation when adding new modules.
- Keep implementation reusable for future agents and workflows.
- Never move fast by bypassing policy nodes; preserve compliance first, then optimize speed.