OpenClaw Deep newsAligator

What this provides
- A dedicated OpenClaw agent workspace profile for deep news research.
- A local runner that produces:
  - outputs/<7-digit-session-id>/final.md
  - outputs/<7-digit-session-id>/newspaper.html
  - outputs/<7-digit-session-id>/report_data.json
  - outputs/<7-digit-session-id>/raw_openclaw_response.json
  - outputs/<7-digit-session-id>/images/*
  - outputs/<7-digit-session-id>/InstaPosts/post_*.png (4-5 carousel images)
  - outputs/<7-digit-session-id>/InstaPosts/posts.json (caption/description/credits metadata)

Why this is useful
- Isolates news research behavior in a dedicated agent id.
- Forces structured output so you can reliably post-process it.
- Builds an HTML newspaper view for fast visual scan.
- Includes resilient fallback paths when key-gated web search is unavailable.

One-time setup done in this workspace
- Agent id: newsaligator
- Agent workspace: openclaw/newsAligator
- Models: defined in config.json under openclaw.models (task-specific)
- Web search configured: tools.web.search.enabled=true, provider=gemini, maxResults=8

Model routing from config.json
- The runner reads model mapping from config.json and applies models by task stage.
- Keys used by this pipeline:
  - openclaw.models.default
  - openclaw.models.tasks.news_primary
  - openclaw.models.tasks.news_fallback
  - openclaw.models.tasks.news_seeded
- Example:
  {
    "openclaw": {
      "models": {
        "default": "github-copilot/gpt-4.1",
        "tasks": {
          "news_primary": "github-copilot/gpt-4.1",
          "news_fallback": "openrouter/openai/gpt-4o-mini",
          "news_seeded": "github-copilot/gpt-4.1"
        }
      }
    }
  }

Run
0) Ensure OpenClaw binary is on PATH (this environment uses nvm Node):
  export PATH="$HOME/.nvm/versions/node/v22.16.0/bin:$HOME/.local/bin:$PATH"

1) Ensure OpenClaw gateway is running:
   openclaw status

  If gateway is unreachable, restart service cleanly:
  openclaw gateway restart

  If service is not configured in another machine/profile, start directly:
  openclaw gateway --allow-unconfigured

2) Run the generator from repository root:
  python3 tools/newsdesk/run_newsdesk.py --workspace . --agent newsaligator --hours 24 --articles 12 --thinking high --insta-count 5

  or from root CLI:
  python3 main.py newsdesk --workspace . --agent newsaligator --hours 24 --articles 12 --thinking high --insta-count 5

3) Open outputs:
- Markdown report: outputs/<7-digit-session-id>/final.md
- HTML newspaper: outputs/<7-digit-session-id>/newspaper.html
- Instagram carousel images: outputs/<7-digit-session-id>/InstaPosts/post_01.png ...
- Instagram metadata JSON: outputs/<7-digit-session-id>/InstaPosts/posts.json

Instagram post generation details
- Images are rendered at 1080x1350 (4:5) for feed/carousel compatibility.
- The tool keeps facts unchanged and creates meme-style overlays from article facts.
- It does not upload anywhere; it only writes local files.

Fallback behavior (important)
- First attempt: autonomous OpenClaw research with strict JSON contract.
- Second attempt: no-web-search deep browsing prompt.
- Third attempt: script collects RSS + article snippets, then asks OpenClaw to synthesize the final structured report.

Tips for deeper research quality
- Increase article count:
  --articles 16
- Increase reasoning:
  --thinking xhigh
- Expand time window:
  --hours 48

Agent behavior customization
- Edit openclaw/newsAligator/AGENTS.md to tune:
  - source diversity requirements
  - dedup policy
  - output schema fields
  - quality criteria

Troubleshooting
- If `openclaw` is not found in shell:
  export PATH="$HOME/.nvm/versions/node/v22.16.0/bin:$HOME/.local/bin:$PATH"
  command -v openclaw

- If the run fails with auth errors, copy auth profiles from main agent:
  mkdir -p ~/.openclaw/agents/newsAligator/agent
  cp ~/.openclaw/agents/main/agent/auth-profiles.json ~/.openclaw/agents/newsAligator/agent/auth-profiles.json

- If model/provider errors mention missing API keys:
  - Keep this pipeline key-light by relying on fallback stages already built in.
  - If you intentionally use provider web search, configure keys and verify with:
    openclaw models status
    openclaw config get tools.web.search

- If web search changes do not apply immediately:
  openclaw gateway restart

- If final.md/newspaper.html generation fails, inspect:
  - outputs/<7-digit-session-id>/raw_openclaw_response.json
  - outputs/<7-digit-session-id>/report_data.json
