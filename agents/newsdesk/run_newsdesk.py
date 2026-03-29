#!/usr/bin/env python3
"""Run OpenClaw newsAligator and generate markdown + HTML newspaper outputs."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import random
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps


DEFAULT_SECTIONS = ["World", "War", "Business", "Tech", "Science", "Sports", "Culture"]
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/sport/rss",
    "https://www.reutersagency.com/feed/?best-topics=world&post_type=best",
]


@dataclass
class Article:
    rank: int
    section: str
    headline: str
    source: str
    url: str
    published_at: str
    summary: str
    why_it_matters: str
    image_url: str | None
    local_image_path: str | None = None


def build_prompt(hours: int, article_count: int) -> str:
    section_csv = ", ".join(DEFAULT_SECTIONS)
    return (
        "You are newsAligator, a research-intensive global news analyst. "
        f"Research the most important breaking stories from the last {hours} hours. "
        "Use deep reading from article texts, not headline-only summaries. "
        "Use multi-source corroboration and avoid duplicate/syndicated repeats. "
        "Prefer original reporting and trusted publishers. "
        "Return strict JSON only and no markdown. "
        "Schema: "
        "{"
        '\"issue_title\":\"string\",'
        '\"generated_at_utc\":\"ISO-8601\",'
        f'\"time_window_hours\":{hours},'
        '\"topline\":\"string\",'
        '\"articles\":[{' 
        '\"rank\":1,'
        f'\"section\":\"one of: {section_csv}\",'
        '\"headline\":\"string\",'
        '\"source\":\"string\",'
        '\"url\":\"https://...\",'
        '\"published_at\":\"string\",'
        '\"summary\":\"2-4 sentence summary\",'
        '\"why_it_matters\":\"string\",'
        '\"image_url\":\"https://... or empty\"'
        "}]"
        "}. "
        f"Return exactly {article_count} articles with unique URLs and ranked order."
    )


def build_fallback_prompt(hours: int, article_count: int) -> str:
    section_csv = ", ".join(DEFAULT_SECTIONS)
    return (
        "Do not use key-gated web_search functools. "
        "Perform deep reading by browsing/fetching directly from major news homepages and article pages. "
        "Use a diverse source mix and focus on breaking developments. "
        f"Time window: last {hours} hours. "
        "Return strict JSON only and no markdown. "
        "Schema: "
        "{"
        '\"issue_title\":\"string\",'
        '\"generated_at_utc\":\"ISO-8601\",'
        f'\"time_window_hours\":{hours},'
        '\"topline\":\"string\",'
        '\"articles\":[{' 
        '\"rank\":1,'
        f'\"section\":\"one of: {section_csv}\",'
        '\"headline\":\"string\",'
        '\"source\":\"string\",'
        '\"url\":\"https://...\",'
        '\"published_at\":\"string\",'
        '\"summary\":\"2-4 sentence summary\",'
        '\"why_it_matters\":\"string\",'
        '\"image_url\":\"https://... or empty\"'
        "}]"
        "}. "
        f"Return exactly {article_count} articles with unique URLs and ranked order."
    )


def build_seeded_prompt(hours: int, article_count: int, candidates: list[dict[str, str]]) -> str:
    lines = []
    for i, c in enumerate(candidates, start=1):
        lines.append(
            f"{i}. source={c.get('source','Unknown')} | "
            f"published={c.get('published_at','Unknown')} | "
            f"title={c.get('headline','')} | "
            f"url={c.get('url','')} | "
            f"snippet={c.get('snippet','')}"
        )
    candidate_blob = "\n".join(lines)
    section_csv = ", ".join(DEFAULT_SECTIONS)
    return (
        f"You are newsAligator. Using only the candidate stories below from the last {hours} hours, "
        "select the most important breaking developments and produce strict JSON only. "
        "No markdown. No prose outside JSON. "
        "Schema: "
        "{"
        '\"issue_title\":\"string\",'
        '\"generated_at_utc\":\"ISO-8601\",'
        f'\"time_window_hours\":{hours},'
        '\"topline\":\"string\",'
        '\"articles\":[{' 
        '\"rank\":1,'
        f'\"section\":\"one of: {section_csv}\",'
        '\"headline\":\"string\",'
        '\"source\":\"string\",'
        '\"url\":\"https://...\",'
        '\"published_at\":\"string\",'
        '\"summary\":\"2-4 sentence summary based on snippet and source context\",'
        '\"why_it_matters\":\"string\",'
        '\"image_url\":\"https://... or empty\"'
        "}]"
        "}. "
        f"Return exactly {article_count} unique-URL articles. "
        "Candidates:\n"
        f"{candidate_blob}"
    )


def load_openclaw_task_models(base_dir: Path) -> dict[str, str]:
    config_path = base_dir / "config.json"
    if not config_path.exists():
        return {}

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(cfg, dict):
        return {}

    openclaw_cfg = cfg.get("openclaw", {})
    if not isinstance(openclaw_cfg, dict):
        return {}

    models_cfg = openclaw_cfg.get("models", {})
    if not isinstance(models_cfg, dict):
        return {}

    task_models: dict[str, str] = {}
    default_model = models_cfg.get("default")
    if isinstance(default_model, str) and default_model.strip():
        task_models["default"] = default_model.strip()

    tasks_cfg = models_cfg.get("tasks", {})
    if isinstance(tasks_cfg, dict):
        for key, value in tasks_cfg.items():
            if isinstance(value, str) and value.strip():
                task_models[str(key)] = value.strip()

    return task_models


def resolve_task_model(task_models: dict[str, str], task_name: str) -> str | None:
    task_model = task_models.get(task_name)
    if task_model:
        return task_model
    return task_models.get("default")


def set_openclaw_model(openclaw_bin: str, model: str) -> None:
    cmd = [openclaw_bin, "models", "set", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Failed to apply OpenClaw model from config.json.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Exit: {proc.returncode}\n"
            f"STDERR:\n{proc.stderr}\n"
            f"STDOUT:\n{proc.stdout[:1000]}"
        )


def run_openclaw(
    openclaw_bin: str,
    agent: str,
    thinking: str,
    message: str,
    model: str | None = None,
    model_state: dict[str, str] | None = None,
) -> dict[str, Any]:
    if model:
        active_model = (model_state or {}).get("active_model", "")
        if active_model != model:
            set_openclaw_model(openclaw_bin, model)
            if model_state is not None:
                model_state["active_model"] = model

    cmd = [
        openclaw_bin,
        "agent",
        "--agent",
        agent,
        "--thinking",
        thinking,
        "--json",
        "--message",
        message,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "OpenClaw run failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Exit: {proc.returncode}\n"
            f"STDERR:\n{proc.stderr}\n"
            f"STDOUT:\n{proc.stdout[:1000]}"
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "OpenClaw did not return valid JSON. "
            "Try re-running with a stable network/gateway state."
        ) from exc


def extract_json_blob(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("Empty payload text from OpenClaw agent response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find JSON object in payload text")

    candidate = text[start : end + 1]
    return json.loads(candidate)


def should_retry_without_web_search(payload_text: str) -> bool:
    lower = payload_text.lower()
    markers = [
        "missing gemini api key",
        "missing api key",
        "unable to fetch current news",
        "web search",
    ]
    return any(m in lower for m in markers)


def fetch_text(url: str, max_bytes: int = 1_000_000) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as resp:
        if resp.status < 200 or resp.status >= 300:
            return ""
        data = resp.read(max_bytes)
    return data.decode("utf-8", errors="ignore")


def strip_html_to_text(raw_html: str, max_chars: int = 450) -> str:
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text[:max_chars]


def parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def collect_rss_candidates(hours: int, max_candidates: int = 40) -> list[dict[str, str]]:
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (hours * 3600)
    items: list[dict[str, str]] = []

    for feed_url in RSS_FEEDS:
        try:
            xml_text = fetch_text(feed_url, max_bytes=800_000)
            root = ET.fromstring(xml_text)
        except Exception:
            continue

        source = urlparse(feed_url).netloc
        for elem in root.findall(".//item"):
            title = (elem.findtext("title") or "").strip()
            link = (elem.findtext("link") or "").strip()
            pub_raw = (elem.findtext("pubDate") or elem.findtext("published") or "").strip()
            desc = (elem.findtext("description") or "").strip()

            if not title or not link.startswith("http"):
                continue

            pub_dt = parse_date(pub_raw)
            if pub_dt and pub_dt.timestamp() < cutoff:
                continue

            snippet = strip_html_to_text(desc, max_chars=260)
            if len(snippet) < 120:
                try:
                    page_text = fetch_text(link, max_bytes=900_000)
                    snippet = strip_html_to_text(page_text, max_chars=360)
                except Exception:
                    pass

            items.append(
                {
                    "source": source,
                    "headline": title,
                    "url": link,
                    "published_at": pub_dt.isoformat() if pub_dt else (pub_raw or "Unknown"),
                    "snippet": snippet,
                }
            )

    dedup: dict[str, dict[str, str]] = {}
    for item in items:
        dedup[item["url"]] = item

    merged = list(dedup.values())
    merged.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return merged[:max_candidates]


def normalize_articles(data: dict[str, Any], expected_count: int) -> list[Article]:
    raw_articles = data.get("articles")
    if not isinstance(raw_articles, list):
        raise ValueError("Missing or invalid 'articles' list in agent output")

    articles: list[Article] = []
    for idx, item in enumerate(raw_articles, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url.startswith("http"):
            continue

        image_url = str(item.get("image_url", "")).strip() or None
        articles.append(
            Article(
                rank=int(item.get("rank", idx)),
                section=str(item.get("section", "World")).strip() or "World",
                headline=str(item.get("headline", "Untitled")).strip() or "Untitled",
                source=str(item.get("source", "Unknown")).strip() or "Unknown",
                url=url,
                published_at=str(item.get("published_at", "Unknown")).strip() or "Unknown",
                summary=str(item.get("summary", "")).strip(),
                why_it_matters=str(item.get("why_it_matters", "")).strip(),
                image_url=image_url,
            )
        )

    articles.sort(key=lambda x: x.rank)
    if len(articles) < max(3, expected_count // 2):
        raise ValueError(
            "Too few valid articles in output; rerun with stronger prompt or model"
        )
    return articles[:expected_count]


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "image"


def download_image(url: str, destination: Path) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            if resp.status < 200 or resp.status >= 300:
                return False
            data = resp.read()
            if not data:
                return False
        destination.write_bytes(data)
        return True
    except Exception:
        return False


def discover_image_from_article(url: str) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            if resp.status < 200 or resp.status >= 300:
                return None
            html = resp.read(1_500_000).decode("utf-8", errors="ignore")
    except Exception:
        return None

    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith("http"):
                return candidate
    return None


def attach_local_images(articles: list[Article], images_dir: Path) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)
    for idx, article in enumerate(articles, start=1):
        image_url = article.image_url or discover_image_from_article(article.url)
        if not image_url:
            continue
        parsed = urlparse(image_url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        base = sanitize_filename(Path(parsed.path).stem or f"article_{idx}")
        out = images_dir / f"{idx:02d}_{base}{suffix}"
        if download_image(image_url, out):
            article.image_url = image_url
            article.local_image_path = str(out)


def render_markdown(issue_title: str, topline: str, articles: list[Article]) -> str:
    lines: list[str] = []
    lines.append(f"# {issue_title}")
    lines.append("")
    lines.append(f"{topline}")
    lines.append("")
    for a in articles:
        lines.append(f"## {a.rank}. {a.headline}")
        lines.append("")
        lines.append(f"- Section: {a.section}")
        lines.append(f"- Source: {a.source}")
        lines.append(f"- Published: {a.published_at}")
        lines.append(f"- URL: {a.url}")
        lines.append("")
        if a.summary:
            lines.append(a.summary)
            lines.append("")
        if a.why_it_matters:
            lines.append(f"Why it matters: {a.why_it_matters}")
            lines.append("")
        if a.local_image_path:
            local_name = Path(a.local_image_path).name
            lines.append(f"Image: images/{local_name}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_html(issue_title: str, generated_at_utc: str, topline: str, articles: list[Article]) -> str:
    cards: list[str] = []
    for a in articles:
        if a.local_image_path:
            # Keep image paths relative to each session's newspaper.html.
            image_src = f"images/{Path(a.local_image_path).name}"
        else:
            image_src = a.image_url or ""
        image_html = (
            f'<img class="thumb" src="{image_src}" alt="{a.headline}">' if image_src else ""
        )
        card = (
            '<article class="card">'
            f'<div class="meta">{a.section} | {a.source} | {a.published_at}</div>'
            f'<h2><a href="{a.url}" target="_blank" rel="noopener noreferrer">{a.headline}</a></h2>'
            f"{image_html}"
            f"<p>{a.summary}</p>"
            f'<p class="matters"><strong>Why it matters:</strong> {a.why_it_matters}</p>'
            "</article>"
        )
        cards.append(card)

    style = """
body { margin: 0; font-family: Georgia, 'Times New Roman', serif; background: #f3efe3; color: #171717; }
header { background: #111; color: #fefefe; padding: 24px 28px; border-bottom: 6px solid #b8860b; }
header h1 { margin: 0; font-size: 40px; letter-spacing: 1px; text-transform: uppercase; }
header .sub { margin-top: 8px; opacity: 0.9; font-size: 15px; }
main { max-width: 1200px; margin: 24px auto; padding: 0 18px 24px; }
.topline { font-size: 20px; line-height: 1.45; margin: 0 0 22px; border-left: 5px solid #b8860b; padding-left: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.card { background: #fffdf7; border: 1px solid #d9c9a7; box-shadow: 0 1px 0 rgba(0,0,0,0.06); padding: 14px; }
.meta { font-size: 12px; color: #6a5f4a; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.card h2 { font-size: 22px; line-height: 1.2; margin: 0 0 10px; }
.card h2 a { color: #111; text-decoration: none; }
.card h2 a:hover { text-decoration: underline; }
.thumb { width: 100%; height: auto; max-height: 220px; object-fit: cover; border: 1px solid #d9c9a7; margin: 8px 0 10px; }
.card p { margin: 0 0 10px; line-height: 1.45; }
.matters { border-top: 1px dashed #c7b791; padding-top: 10px; margin-top: 12px; }
footer { max-width: 1200px; margin: 0 auto 20px; padding: 0 18px; color: #5c5343; font-size: 13px; }
"""

    return (
        "<!doctype html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{issue_title}</title>"
        f"<style>{style}</style>"
        "</head>"
        "<body>"
        "<header>"
        f"<h1>{issue_title}</h1>"
        f"<div class=\"sub\">Generated at {generated_at_utc}</div>"
        "</header>"
        "<main>"
        f"<p class=\"topline\">{topline}</p>"
        f"<section class=\"grid\">{''.join(cards)}</section>"
        "</main>"
        "<footer>Built by OpenClaw newsAligator runner.</footer>"
        "</body>"
        "</html>"
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _fit_background(image_path: str | None, width: int, height: int) -> Image.Image:
    if image_path and Path(image_path).exists():
        img = Image.open(image_path).convert("RGB")
        return ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
    return Image.new("RGB", (width, height), color=(24, 29, 38))


def _meme_lines(article: Article) -> tuple[str, str]:
    top = article.headline
    if len(top) > 90:
        top = top[:87].rstrip() + "..."
    bottom = f"Fact check: {article.source} | {article.published_at}"
    return top.upper(), bottom


def generate_instaposts(
    session_dir: Path,
    issue_title: str,
    topline: str,
    articles: list[Article],
    generated_at_utc: str,
    insta_count: int,
) -> tuple[Path, list[dict[str, Any]]]:
    insta_dir = session_dir / "InstaPosts"
    insta_dir.mkdir(parents=True, exist_ok=True)

    width, height = 1080, 1350  # Instagram portrait post (4:5)
    title_font = _load_font(58)
    body_font = _load_font(42)
    meta_font = _load_font(28)
    small_font = _load_font(24)

    count = max(4, min(5, insta_count))
    selected = articles[:count] if len(articles) >= count else articles

    manifest: list[dict[str, Any]] = []
    for idx, article in enumerate(selected, start=1):
        canvas = _fit_background(article.local_image_path, width, height)
        overlay = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        # Top and bottom dark bands for readability.
        draw_overlay.rectangle([(0, 0), (width, 250)], fill=(0, 0, 0, 160))
        draw_overlay.rectangle([(0, 840), (width, height)], fill=(0, 0, 0, 180))

        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
        draw = ImageDraw.Draw(canvas)

        meme_top, meme_bottom = _meme_lines(article)
        wrapped_top = _wrap_text(draw, meme_top, title_font, max_width=width - 80)
        wrapped_headline = _wrap_text(draw, article.headline, body_font, max_width=width - 100)
        wrapped_why = _wrap_text(draw, article.why_it_matters, meta_font, max_width=width - 100)

        draw.text((40, 36), wrapped_top, fill=(255, 255, 255), font=title_font, spacing=6)
        draw.text((50, 900), wrapped_headline, fill=(255, 255, 255), font=body_font, spacing=6)

        draw.text((50, 1085), "Why this matters:", fill=(255, 230, 130), font=meta_font)
        draw.text((50, 1125), wrapped_why, fill=(245, 245, 245), font=meta_font, spacing=4)

        meta_line = f"{article.source} | {article.published_at} | Slide {idx}/{len(selected)}"
        draw.text((50, 1298), meta_line[:95], fill=(220, 220, 220), font=small_font)

        draw.text((40, 294), meme_bottom, fill=(255, 255, 255), font=small_font)

        output_name = f"post_{idx:02d}.png"
        output_path = insta_dir / output_name
        canvas.convert("RGB").save(output_path, format="PNG")

        credits_line = (
            f"Image credit: {article.source} ({article.url})"
            if article.url
            else f"Image credit: {article.source}"
        )
        description = (
            f"{article.headline}. {article.summary} "
            f"Source: {article.source}. Published: {article.published_at}."
        )

        manifest.append(
            {
                "slide": idx,
                "image_file": f"InstaPosts/{output_name}",
                "headline": article.headline,
                "source": article.source,
                "source_url": article.url,
                "published_at": article.published_at,
                "summary": article.summary,
                "why_it_matters": article.why_it_matters,
                "meme_text_top": meme_top,
                "meme_text_bottom": meme_bottom,
                "caption": f"{article.headline}\\n\\n{article.why_it_matters}",
                "description": description,
                "credits": credits_line,
            }
        )

    # Include a post-level card with reusable copy blocks.
    bundle = {
        "issue_title": issue_title,
        "generated_at_utc": generated_at_utc,
        "topline": topline,
        "slides": manifest,
        "post_copy": {
            "caption": (
                f"{issue_title}\\n\\n{topline}\\n\\n"
                "Fact-first news memes. No altered facts. Swipe for details."
            ),
            "description": "Carousel generated from current news evidence and source links.",
            "credits": [m["credits"] for m in manifest],
            "hashtags": ["#News", "#BreakingNews", "#WorldNews", "#FactCheck", "#InstaNews"],
        },
    }
    json_path = insta_dir / "posts.json"
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return json_path, manifest


def _new_session_id() -> str:
    rng = random.SystemRandom()
    return str(rng.randint(1_000_000, 9_999_999))


def ensure_session_outputs(base_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path, str]:
    outputs_dir = base_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    session_id = _new_session_id()
    session_dir = outputs_dir / session_id
    while session_dir.exists():
        session_id = _new_session_id()
        session_dir = outputs_dir / session_id

    images_dir = session_dir / "images"
    session_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    raw_path = session_dir / "raw_openclaw_response.json"
    report_path = session_dir / "report_data.json"
    final_md = session_dir / "final.md"
    final_html = session_dir / "newspaper.html"
    return session_dir, raw_path, report_path, final_md, final_html, images_dir, session_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deep-news files using OpenClaw")
    parser.add_argument("--workspace", default=".", help="Workspace root (default: current directory)")
    parser.add_argument("--agent", default="newsaligator", help="OpenClaw agent id")
    parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours")
    parser.add_argument("--articles", type=int, default=12, help="Number of articles")
    parser.add_argument(
        "--thinking",
        choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        default="high",
        help="OpenClaw thinking level",
    )
    parser.add_argument(
        "--insta-count",
        type=int,
        default=5,
        help="Number of Instagram carousel slides to generate (clamped to 4-5)",
    )
    args = parser.parse_args()

    base_dir = Path(args.workspace).resolve()
    task_models = load_openclaw_task_models(base_dir)
    model_state: dict[str, str] = {}
    session_dir, raw_path, report_path, final_md_path, final_html_path, images_dir, session_id = ensure_session_outputs(base_dir)

    prompt = build_prompt(hours=args.hours, article_count=args.articles)
    run = run_openclaw(
        args.openclaw_bin,
        args.agent,
        args.thinking,
        prompt,
        model=resolve_task_model(task_models, "news_primary"),
        model_state=model_state,
    )
    payload_text = run.get("result", {}).get("payloads", [{}])[0].get("text", "")

    report_data: dict[str, Any] | None = None
    try:
        report_data = extract_json_blob(payload_text)
        _ = normalize_articles(report_data, expected_count=args.articles)
    except Exception:
        retry_prompt = build_fallback_prompt(hours=args.hours, article_count=args.articles)
        run = run_openclaw(
            args.openclaw_bin,
            args.agent,
            args.thinking,
            retry_prompt,
            model=resolve_task_model(task_models, "news_fallback"),
            model_state=model_state,
        )
        payload_text = run.get("result", {}).get("payloads", [{}])[0].get("text", "")
        try:
            report_data = extract_json_blob(payload_text)
            _ = normalize_articles(report_data, expected_count=args.articles)
        except Exception:
            candidates = collect_rss_candidates(args.hours, max_candidates=max(30, args.articles * 4))
            if not candidates:
                raise RuntimeError("No RSS candidates collected for fallback synthesis")
            seeded_prompt = build_seeded_prompt(args.hours, args.articles, candidates)
            run = run_openclaw(
                args.openclaw_bin,
                args.agent,
                args.thinking,
                seeded_prompt,
                model=resolve_task_model(task_models, "news_seeded"),
                model_state=model_state,
            )
            payload_text = run.get("result", {}).get("payloads", [{}])[0].get("text", "")
            report_data = extract_json_blob(payload_text)

    raw_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    if report_data is None:
        raise RuntimeError("Failed to produce structured report data")

    issue_title = str(report_data.get("issue_title") or "Deep News Aligator")
    generated_at = str(report_data.get("generated_at_utc") or datetime.now(timezone.utc).isoformat())
    topline = str(report_data.get("topline") or "Global breaking stories and deep context.")

    articles = normalize_articles(report_data, expected_count=args.articles)
    attach_local_images(articles, images_dir)

    report_for_disk = {
        "issue_title": issue_title,
        "generated_at_utc": generated_at,
        "time_window_hours": int(report_data.get("time_window_hours", args.hours)),
        "topline": topline,
        "articles": [a.__dict__ for a in articles],
    }
    report_path.write_text(json.dumps(report_for_disk, indent=2), encoding="utf-8")

    final_md_path.write_text(render_markdown(issue_title, topline, articles), encoding="utf-8")
    final_html_path.write_text(render_html(issue_title, generated_at, topline, articles), encoding="utf-8")
    insta_json_path, insta_slides = generate_instaposts(
        session_dir=session_dir,
        issue_title=issue_title,
        topline=topline,
        articles=articles,
        generated_at_utc=generated_at,
        insta_count=args.insta_count,
    )

    print(f"Session: {session_id}")
    print(f"Wrote {final_md_path}")
    print(f"Wrote {final_html_path}")
    print(f"Wrote {insta_json_path} ({len(insta_slides)} slides)")
    print(f"Wrote {report_path}")
    print(f"Wrote {raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
