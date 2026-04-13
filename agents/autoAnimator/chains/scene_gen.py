"""
Scene Generator – Generates panel scenes with character consistency.

Produces: episodes/episodeN/scenes/panel_XX.png + episodes/episodeN/scenes/scenes_manifest.json
Uses character portraits as multimodal anchors for consistency.
Resume: skips existing. Budget-aware: respects max_generations.
"""

import json
import hashlib
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging

from PIL import Image, ImageDraw, ImageFont

from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate

logger = logging.getLogger(__name__)


def _expand_at_mentions(text: str, char_visuals: dict) -> str:
    """Replace @Name tokens with @Name[visual_prompt snippet] for scene prompt clarity.

    This lets both LLM-generated and user-written scene_descriptions reference
    characters and objects by @Name and have them automatically expanded to
    carry their visual anchor inline, improving image generation consistency.
    """
    def _replacer(m):
        name = m.group(1)
        vis = next((v for k, v in char_visuals.items() if k.lower() == name.lower()), None)
        if vis:
            snippet = str(vis)[:120].rstrip()
            return f"@{name}[{snippet}]"
        return m.group(0)
    return re.sub(r'@([A-Za-z0-9_\-]+)', _replacer, text)


class _SharedAnchor:
    """Thread-safe holder for the most recently completed scene's bytes (continuity anchor)."""

    def __init__(self, initial: Optional[bytes] = None) -> None:
        self._bytes = initial
        self._lock = threading.Lock()

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._bytes

    def update(self, new_bytes: Optional[bytes]) -> None:
        with self._lock:
            if new_bytes is not None:
                self._bytes = new_bytes


class _BudgetCounter:
    """Thread-safe generation budget counter."""

    def __init__(self, max_count: int) -> None:
        self._count = 0
        self._max = max_count
        self._lock = threading.Lock()

    def try_claim(self) -> bool:
        with self._lock:
            if self._count < self._max:
                self._count += 1
                return True
            return False

    @property
    def count(self) -> int:
        return self._count


class SceneGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 45,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        aesthetic_guidance: str = "",
        project_name: str = "AutoAnimator",
        tracker: Optional[LLMTracker] = None,
        scene_concurrency: int = 1,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.aesthetic_guidance = aesthetic_guidance or ""
        self.project_name = project_name or "AutoAnimator"
        self.tracker = tracker
        self.scene_concurrency = max(1, int(scene_concurrency or 1))

    def _panel_signature(self, panel: Dict[str, Any], char_visuals: Dict[str, str]) -> str:
        payload = {
            "scene_description": str(panel.get("scene_description", "") or ""),
            "render_method": str(panel.get("render_method", "llm_image") or "llm_image"),
            "characters_present": [str(c) for c in (panel.get("characters_present", []) if isinstance(panel.get("characters_present", []), list) else [])],
            "camera_angle": str(panel.get("camera_angle", "") or ""),
            "mood": str(panel.get("mood", "") or ""),
            "reuse_from_previous_episode_panel": panel.get("reuse_from_previous_episode_panel"),
            "static_frame_spec": panel.get("static_frame_spec") if isinstance(panel.get("static_frame_spec"), dict) else None,
            "art_style": self.art_style,
            "aesthetic_guidance": self.aesthetic_guidance,
            "resolution": [int(self.resolution[0]), int(self.resolution[1])],
            "char_visuals": {k: char_visuals.get(k, "") for k in sorted(char_visuals.keys())},
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _render_static_frame(self, panel: Dict[str, Any], panel_key: str, out_path: Path) -> bool:
        spec = panel.get("static_frame_spec") if isinstance(panel.get("static_frame_spec"), dict) else {}
        renderer = str(spec.get("renderer", "solid") or "solid").strip().lower()
        width, height = self.resolution
        bg = str(spec.get("bg_color", "#111111") or "#111111")

        img = Image.new("RGB", self.resolution, color=bg)
        if renderer == "gradient":
            gradient = spec.get("gradient") if isinstance(spec.get("gradient"), list) else []
            c1 = str(gradient[0] if len(gradient) > 0 else "#090909")
            c2 = str(gradient[1] if len(gradient) > 1 else "#1a1a1a")
            try:
                from PIL import ImageColor

                r1, g1, b1 = ImageColor.getrgb(c1)
                r2, g2, b2 = ImageColor.getrgb(c2)
                for y in range(height):
                    t = y / max(1, height - 1)
                    color = (
                        int(r1 + (r2 - r1) * t),
                        int(g1 + (g2 - g1) * t),
                        int(b1 + (b2 - b1) * t),
                    )
                    for x in range(width):
                        img.putpixel((x, y), color)
            except Exception:
                pass

        draw = ImageDraw.Draw(img)

        if renderer in {"title_card", "solid", "gradient"}:
            show_text = bool(spec.get("show_text", renderer == "title_card"))
            title = str(spec.get("title_text") or "")
            if show_text:
                font = ImageFont.load_default()
                max_chars = 42
                lines = []
                words = title.split()
                cur = []
                for w in words:
                    cur.append(w)
                    if len(" ".join(cur)) > max_chars:
                        cur.pop()
                        lines.append(" ".join(cur))
                        cur = [w]
                if cur:
                    lines.append(" ".join(cur))
                lines = lines[:4] if lines else [f"{self.project_name} - {panel_key}"]

                y = int(height * 0.32)
                for line in lines:
                    bbox = font.getbbox(line)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    x = max(24, (width - tw) // 2)
                    draw.text((x, y), line, fill=(240, 240, 240), font=font)
                    y += th + 12

        img.save(out_path)
        return True

    @staticmethod
    def _parse_reuse_panel_index(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value - 1 if value > 0 else None
        try:
            raw = str(value).strip().lower()
            if raw.startswith("panel_"):
                return int(raw.split("_", 1)[1])
            num = int(raw)
            return num - 1 if num > 0 else None
        except Exception:
            return None

    @staticmethod
    def _extract_inline_image_bytes(response: Any) -> bytes | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            if data:
                return data
        return None

    @staticmethod
    def _is_valid_generated_image(path: Path) -> bool:
        try:
            if not path.exists() or path.stat().st_size < 1024:
                return False
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                extrema = rgb.getextrema()
                if all((mx - mn) < 8 for mn, mx in extrema):
                    return False
                # Reject near-empty dark outputs (common API failure mode):
                # overwhelmingly black pixels with negligible highlight detail.
                gray = rgb.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
                hist = gray.histogram()
                total = float(sum(hist) or 1)
                dark_ratio = float(sum(hist[:12])) / total
                bright_ratio = float(sum(hist[245:])) / total
                mean_luma = sum(i * c for i, c in enumerate(hist)) / total
                if dark_ratio > 0.995 and bright_ratio < 0.0005:
                    return False
                if mean_luma < 8 and dark_ratio > 0.98:
                    return False
            return True
        except Exception:
            return False

    def run(
        self,
        manga_board: Dict[str, Any],
        char_manifest: Dict[str, str],
        session_dir: Path,
    ) -> Dict[str, str]:
        print("--- Pipeline: Scene Generation ---")
        logger.info("SceneGen.run() started | session=%s", session_dir)
        current_episode = max(1, int(manga_board.get("episode_number", 1) or 1))
        episode_scenes_dir = session_dir / "episodes" / f"episode{current_episode}" / "scenes"
        episode_scenes_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = episode_scenes_dir
        prior_episode_scenes_dir = session_dir / "episodes" / f"episode{current_episode - 1}" / "scenes"
        signatures_path = scenes_dir / "scene_signatures.json"
        scene_signatures: Dict[str, str] = {}
        if signatures_path.exists():
            try:
                parsed = json.loads(signatures_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    scene_signatures = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                scene_signatures = {}

        panels = manga_board.get("panels", [])
        render_strategy = manga_board.get("render_strategy", {}) if isinstance(manga_board.get("render_strategy", {}), dict) else {}
        planner_skill_directives = str(render_strategy.get("planner_skill_directives", "") or "").strip()
        characters = manga_board.get("characters", [])
        char_visuals = {c["name"]: c.get("visual_prompt", c.get("description", "")) for c in characters}
        # Include object visual descriptions so they're part of the consistency lock block
        objects = manga_board.get("objects", []) if isinstance(manga_board.get("objects"), list) else []
        for obj in objects:
            oname = str(obj.get("name", "") or "").strip()
            if oname:
                char_visuals[oname] = obj.get("visual_prompt", obj.get("description", ""))

        def _load_ref_bytes(ref_path: str | None) -> bytes | None:
            if not ref_path:
                return None
            try:
                p = Path(ref_path)
                if not p.is_absolute():
                    p = session_dir / ref_path
                if p.exists() and p.is_file():
                    return p.read_bytes()
            except Exception:
                return None
            return None

        start_frame_bytes = _load_ref_bytes(str(render_strategy.get("start_frame_path", "") or ""))
        end_frame_bytes = _load_ref_bytes(str(render_strategy.get("end_frame_path", "") or ""))

        # Load anchor-based descriptions when available
        char_anchors_path = session_dir / "chars" / "char_anchors.json"
        if char_anchors_path.exists():
            try:
                with open(char_anchors_path, "r") as f:
                    char_anchors = json.load(f)
                for name, data in char_anchors.items():
                    prompt_text = data.get("visual_prompt") or char_visuals.get(name)
                    if prompt_text:
                        char_visuals[name] = prompt_text
            except Exception as e:
                print(f"  ⚠️ Warning: failed to load char anchors: {e}")

        manifest: Dict[str, str] = {}
        gen_count = 0
        model = get_model(self.image_model_name)

        char_anchor_bytes: Dict[str, bytes] = {}
        for cname, char_img_path in (char_manifest or {}).items():
            try:
                p = Path(char_img_path)
                if p.exists():
                    char_anchor_bytes[cname] = p.read_bytes()
            except Exception:
                continue

        # ── Phase 1 (sequential): cache hits, static frames, episode-reuse panels.
        # Collect LLM-image panels into pending_llm_jobs for parallel Phase 2.
        pending_llm_jobs: list[tuple[int, Dict[str, Any], Path, str]] = []
        last_available_bytes: Optional[bytes] = None
        budget_fallback_announced = False

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            scene_path = scenes_dir / f"{panel_key}.png"
            panel_sig = self._panel_signature(panel, char_visuals)

            # Cache hit: valid existing file with matching signature.
            if scene_path.exists():
                if self._is_valid_generated_image(scene_path) and scene_signatures.get(panel_key) == panel_sig:
                    print(f"Found existing {panel_key}, skipping.")
                    manifest[panel_key] = str(scene_path)
                    try:
                        last_available_bytes = scene_path.read_bytes()
                    except Exception:
                        pass
                    continue
                print(f"Found invalid {panel_key}, regenerating.")
                scene_path.unlink(missing_ok=True)

            # Budget exhausted in Phase 1: static fallback.
            if gen_count >= self.max_generations:
                if not budget_fallback_announced:
                    print(f"Hit budget ({self.max_generations}), switching remaining panels to local static fallback.")
                    budget_fallback_announced = True
                scene_desc = str(panel.get("scene_description", "")).strip()
                title_text = scene_desc[:90] if scene_desc else f"{self.project_name} - {panel_key}"
                fallback_panel = {
                    "scene_description": scene_desc,
                    "static_frame_spec": {
                        "renderer": "gradient",
                        "gradient": ["#0f1228", "#1e2450"],
                        "show_text": False,
                        "title_text": title_text,
                    },
                }
                ok = self._render_static_frame(fallback_panel, panel_key, scene_path)
                if not ok or (not scene_path.exists()) or scene_path.stat().st_size < 256:
                    raise RuntimeError(f"Static fallback generation failed for '{panel_key}'")
                manifest[panel_key] = str(scene_path)
                scene_signatures[panel_key] = panel_sig
                ep_copy = episode_scenes_dir / f"{panel_key}.png"
                self._mirror_to_episode(scene_path, ep_copy)
                continue

            # Episode-reuse: copy from prior episode, no API call.
            reuse_idx = self._parse_reuse_panel_index(panel.get("reuse_from_previous_episode_panel"))
            if current_episode > 1 and reuse_idx is not None and prior_episode_scenes_dir.exists():
                reuse_src = prior_episode_scenes_dir / f"panel_{reuse_idx:02d}.png"
                if reuse_src.exists() and self._is_valid_generated_image(reuse_src):
                    shutil.copy2(reuse_src, scene_path)
                    manifest[panel_key] = str(scene_path)
                    scene_signatures[panel_key] = panel_sig
                    ep_copy = episode_scenes_dir / f"{panel_key}.png"
                    self._mirror_to_episode(scene_path, ep_copy)
                    try:
                        last_available_bytes = scene_path.read_bytes()
                    except Exception:
                        pass
                    print(f"Reused previous-episode scene for {panel_key} from panel_{reuse_idx:02d}.")
                    continue

            # Static frame (director-directed method, no LLM call).
            render_method = str(panel.get("render_method", "llm_image") or "llm_image").strip().lower()
            if render_method == "static_frame":
                print(f"Generating static frame: {panel_key}")
                ok = self._render_static_frame(panel, panel_key, scene_path)
                if not ok or (not scene_path.exists()) or scene_path.stat().st_size < 256:
                    raise RuntimeError(f"Static frame generation failed for '{panel_key}'")
                manifest[panel_key] = str(scene_path)
                scene_signatures[panel_key] = panel_sig
                gen_count += 1
                continue

            # LLM image generation: defer to Phase 2.
            pending_llm_jobs.append((i, panel, scene_path, panel_sig))

        # ── Phase 2: LLM image generation — concurrent when scene_concurrency > 1.
        if pending_llm_jobs:
            slots_remaining = self.max_generations - gen_count
            panels_total = len(panels)
            total_pending = len(pending_llm_jobs)
            shared_anchor = _SharedAnchor(last_available_bytes)
            budget = _BudgetCounter(slots_remaining)
            manifest_lock = threading.Lock()
            sigs_lock = threading.Lock()

            def _llm_worker(job: tuple) -> None:
                j_i, j_panel, j_scene_path, j_panel_sig = job
                j_panel_key = f"panel_{j_i:02d}"

                # Static fallback if budget is exhausted at dispatch time.
                if not budget.try_claim():
                    j_scene_desc = str(j_panel.get("scene_description", "")).strip()
                    j_title_text = j_scene_desc[:90] if j_scene_desc else f"{self.project_name} - {j_panel_key}"
                    fallback = {
                        "scene_description": j_scene_desc,
                        "static_frame_spec": {
                            "renderer": "gradient",
                            "gradient": ["#0f1228", "#1e2450"],
                            "show_text": False,
                            "title_text": j_title_text,
                        },
                    }
                    ok = self._render_static_frame(fallback, j_panel_key, j_scene_path)
                    if not ok or not j_scene_path.exists() or j_scene_path.stat().st_size < 256:
                        raise RuntimeError(f"Static fallback generation failed for '{j_panel_key}'")
                    ep_copy = episode_scenes_dir / f"{j_panel_key}.png"
                    self._mirror_to_episode(j_scene_path, ep_copy)
                    with manifest_lock:
                        manifest[j_panel_key] = str(j_scene_path)
                    with sigs_lock:
                        scene_signatures[j_panel_key] = j_panel_sig
                    return

                # Snapshot the best available continuity anchor at generation start.
                prev_bytes = shared_anchor.get()

                j_scene_desc = j_panel.get("scene_description", "A dramatic manga scene")
                # Expand @Name tokens into @Name[visual_prompt snippet] for image prompt precision.
                j_scene_desc = _expand_at_mentions(str(j_scene_desc), char_visuals)
                j_chars_present = j_panel.get("characters_present", [])
                j_objects_present = j_panel.get("objects_present", [])
                # Merge objects_present into chars consistency check so object anchors are included
                j_all_entities_present = list(j_chars_present) + [o for o in j_objects_present if o not in j_chars_present]
                j_camera = j_panel.get("camera_angle", "medium-shot")
                j_mood = j_panel.get("mood", "dramatic")
                j_continuity_from_panel = j_panel.get("continuity_from_panel")
                j_shot_intent = str(j_panel.get("shot_intent", "") or "").strip()
                j_pose_direction = str(j_panel.get("pose_direction", "") or "").strip()
                j_dialogue_rows = j_panel.get("dialogue", []) if isinstance(j_panel.get("dialogue", []), list) else []
                j_speech_bubbles_raw = j_panel.get("speech_bubbles", []) if isinstance(j_panel.get("speech_bubbles"), list) else []

                # Build dialogue context snippet (for scene understanding)
                j_dialogue_context = []
                for dl in j_dialogue_rows[:5]:
                    if not isinstance(dl, dict):
                        continue
                    cname_dl = str(dl.get("character", "Speaker") or "Speaker")
                    line_dl = str(dl.get("line", "") or "").strip()
                    if line_dl:
                        j_dialogue_context.append(f"{cname_dl}: {line_dl}")
                j_dialogue_snippet = " | ".join(j_dialogue_context)

                # Build speech bubble render instructions.
                # Prefer explicit speech_bubbles array from planner; fall back to dialogue rows.
                # Each bubble is a numbered block so the image model can read each text distinctly.
                j_bubble_entries: list[dict] = []  # {char, text, style, position}
                if j_speech_bubbles_raw:
                    for sb in j_speech_bubbles_raw:
                        if not isinstance(sb, dict):
                            continue
                        sb_char = str(sb.get("character", "") or "").strip()
                        sb_text = str(sb.get("text", "") or "").strip()
                        sb_style = str(sb.get("style", "rounded") or "rounded").strip()
                        sb_pos = str(sb.get("position", "natural") or "natural").strip()
                        if sb_text:
                            j_bubble_entries.append({"char": sb_char, "text": sb_text, "style": sb_style, "pos": sb_pos})
                elif j_dialogue_rows:
                    # Fallback: derive bubble entries from dialogue array.
                    for dl in j_dialogue_rows[:6]:
                        if not isinstance(dl, dict):
                            continue
                        dl_char = str(dl.get("character", "Speaker") or "Speaker").strip()
                        dl_line = str(dl.get("line", "") or "").strip()
                        dl_mode = str(dl.get("delivery_mode", "dialogue") or "dialogue").strip()
                        if dl_line and dl_mode not in {"narration", "voiceover", "silent"}:
                            j_bubble_entries.append({"char": dl_char, "text": dl_line, "style": "rounded", "pos": "top-right"})

                j_bubble_render_text = ""
                j_bubble_repeat_text = ""
                if j_bubble_entries:
                    bubble_blocks = []
                    for idx, be in enumerate(j_bubble_entries, start=1):
                        block = (
                            f"BUBBLE {idx}: character={be['char']} | style={be['style']} | position={be['pos']}\n"
                            f"  VERBATIM TEXT (copy character-by-character, do NOT alter): \"{be['text']}\""
                        )
                        bubble_blocks.append(block)
                    bubbles_block_str = "\n".join(bubble_blocks)

                    # Repeat each text value at end of prompt to reinforce exact wording.
                    repeat_lines = [f"  Bubble {idx}: \"{be['text']}\"" for idx, be in enumerate(j_bubble_entries, start=1)]
                    j_bubble_repeat_text = (
                        "SPEECH BUBBLE TEXT VERIFICATION (render these EXACT strings — zero deviation allowed):\n"
                        + "\n".join(repeat_lines)
                    )

                    j_bubble_render_text = (
                        f"=== SPEECH BUBBLE RENDERING DIRECTIVE ===\n"
                        f"Render the following speech bubbles DIRECTLY INSIDE THIS IMAGE using manga-style lettering.\n"
                        f"The text in each bubble must be EXACTLY as written below — copy verbatim, letter-by-letter. "
                        f"Do not paraphrase, shorten, reword, or omit any word.\n"
                        f"{bubbles_block_str}\n"
                        f"Bubble rendering rules:\n"
                        f"- Use clean, legible manga font inside each bubble shape.\n"
                        f"- Draw a tail from the bubble pointing toward the speaking character's mouth.\n"
                        f"- Do NOT cover the character's face or the dominant visual element.\n"
                        f"- Prefer bubble positions above or beside the characters rather than at the bottom of the frame.\n"
                        f"- sharp-edged style = rectangular or polygonal bubble; rounded style = oval/cloud bubble; "
                        f"thought-bubble = cloud chain; jagged = spiky; whisper = dashed outline; electric = lightning-border.\n"
                        f"=== END SPEECH BUBBLE DIRECTIVE ===\n"
                    )

                j_char_snippets = [f"{cname}: {char_visuals.get(cname, cname)}" for cname in j_all_entities_present]
                j_chars_in_scene = "; ".join(j_char_snippets) if j_char_snippets else "No specific characters"
                width, height = self.resolution
                aesthetics = f"Aesthetic direction: {self.aesthetic_guidance}. " if self.aesthetic_guidance else ""

                # ── Style lock: prepended to every scene prompt to ensure manga/comic output.
                style_lock = (
                    f"=== MANDATORY STYLE LOCK ===\n"
                    f"This image MUST be rendered as a MANGA / COMIC PANEL. Art style: {self.art_style}.\n"
                    f"Required visual characteristics:\n"
                    f"- Bold, clean ink outlines on all characters, props, and background elements.\n"
                    f"- Flat cel-shaded or screentone fill colors — no photorealistic lighting gradients.\n"
                    f"- Manga panel composition: clear foreground/midground/background separation.\n"
                    f"- Expressive anime/manga faces with exaggerated emotion where mood calls for it.\n"
                    f"- FORBIDDEN: photo-realistic rendering, oil-painting style, 3D CGI look, watercolor bleed, impressionist brush.\n"
                    f"=== END STYLE LOCK ===\n"
                )

                # ── Character consistency lock: list every present character's immutable traits.
                char_consistency_lines = []
                for cname in j_all_entities_present:
                    cvis = char_visuals.get(cname, "")
                    if cvis:
                        char_consistency_lines.append(f"  [{cname}]: {cvis}")
                char_consistency_block = ""
                if char_consistency_lines:
                    char_consistency_block = (
                        f"=== CHARACTER CONSISTENCY LOCK ===\n"
                        f"Reproduce every character below with EXACT design fidelity — "
                        f"skin tone, hair color/style, eye color, face shape, outfit colors, accessories, and posture must match their reference IDENTICALLY. "
                        f"Do not alter or simplify ANY character feature.\n"
                        + "\n".join(char_consistency_lines) + "\n"
                        f"=== END CHARACTER CONSISTENCY LOCK ===\n"
                    )

                j_prompt = (
                    f"{style_lock}"
                    f"{char_consistency_block}"
                    f"SCENE: {j_scene_desc}. "
                    f"Camera: {j_camera}. Mood: {j_mood}. "
                    f"Characters in scene: {j_chars_in_scene}. "
                    f"Dialogue context for this panel: {j_dialogue_snippet or 'no spoken lines'}. "
                    f"{j_bubble_render_text}"
                    f"Shot intent: {j_shot_intent or 'story progression'}. "
                    f"Pose progression: {j_pose_direction or 'maintain continuity from previous panel'}. "
                    f"Continuity from panel: {j_continuity_from_panel}. "
                    f"Optional planner skill directives: {planner_skill_directives or 'none'}. "
                    f"{aesthetics}"
                    f"{j_bubble_repeat_text + chr(10) if j_bubble_repeat_text else ''}"
                    f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution. Manga/comic style ONLY."
                )

                print(f"Generating ({budget.count}/{min(slots_remaining, total_pending)}): {j_panel_key} ({j_camera}, {j_mood})")

                max_attempts = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        anchor_payload = []
                        if j_i == 0 and start_frame_bytes:
                            anchor_payload.append({"mime_type": "image/png", "data": start_frame_bytes})
                        if j_i == (panels_total - 1) and end_frame_bytes:
                            anchor_payload.append({"mime_type": "image/png", "data": end_frame_bytes})
                        if prev_bytes:
                            anchor_payload.append({"mime_type": "image/png", "data": prev_bytes})
                        if isinstance(j_continuity_from_panel, int) and j_continuity_from_panel > 0:
                            prior_idx = j_continuity_from_panel - 1
                            prior_path = scenes_dir / f"panel_{prior_idx:02d}.png"
                            if prior_path.exists():
                                try:
                                    anchor_payload.append({"mime_type": "image/png", "data": prior_path.read_bytes()})
                                except Exception:
                                    pass
                        for cname in j_chars_present:
                            cached = char_anchor_bytes.get(cname)
                            if cached:
                                anchor_payload.append({"mime_type": "image/png", "data": cached})
                            if len(anchor_payload) >= 4:
                                break
                        # Also add object reference anchors if present in panel
                        for oname in j_objects_present:
                            if len(anchor_payload) >= 4:
                                break
                            cached = char_anchor_bytes.get(oname)
                            if cached:
                                anchor_payload.append({"mime_type": "image/png", "data": cached})

                        if anchor_payload:
                            response = tracked_generate(
                                self.tracker,
                                model,
                                anchor_payload + [
                                    f"=== REFERENCE IMAGES PROVIDED ===\n"
                                    f"The attached images are character/scene reference anchors. "
                                    f"Reproduce every character's visual design with PIXEL-IDENTICAL fidelity: "
                                    f"same hairstyle, hair color, eye color, face shape, skin tone, outfit details, and accessories as shown. "
                                    f"Do NOT simplify, alter, or reinterpret any character feature. "
                                    f"The output MUST be a manga/comic panel — bold ink outlines, flat/cel-shaded colors, no photorealism.\n"
                                    f"=== END REFERENCE ANCHOR INSTRUCTIONS ===\n"
                                    f"{j_prompt}",
                                ],
                                purpose="scene_gen",
                            )
                        else:
                            response = tracked_generate(self.tracker, model, j_prompt, purpose="scene_gen")

                        image_data = self._extract_inline_image_bytes(response)
                        if not image_data:
                            raise ValueError("No image in response")

                        j_scene_path.write_bytes(image_data)
                        self._force_resize(j_scene_path)
                        if not self._is_valid_generated_image(j_scene_path):
                            raise ValueError("Generated image failed validation")

                        print(f"  ✓ Generated: {j_scene_path.name}")
                        shared_anchor.update(image_data)
                        ep_copy = episode_scenes_dir / f"{j_panel_key}.png"
                        self._mirror_to_episode(j_scene_path, ep_copy)
                        with manifest_lock:
                            manifest[j_panel_key] = str(j_scene_path)
                        with sigs_lock:
                            scene_signatures[j_panel_key] = j_panel_sig
                        return
                    except Exception as e:
                        print(f"  ✗ Attempt {attempt}/{max_attempts} failed for {j_panel_key}: {e}")
                        j_scene_path.unlink(missing_ok=True)

                # Last-resort local fallback so one failed panel does not break the whole episode.
                j_scene_desc = str(j_panel.get("scene_description", "")).strip()
                j_title_text = j_scene_desc[:90] if j_scene_desc else f"{self.project_name} - {j_panel_key}"
                fallback = {
                    "scene_description": j_scene_desc,
                    "static_frame_spec": {
                        "renderer": "gradient",
                        "gradient": ["#0f1228", "#1e2450"],
                        "show_text": False,
                        "title_text": j_title_text,
                    },
                }
                ok = self._render_static_frame(fallback, j_panel_key, j_scene_path)
                if not ok or not j_scene_path.exists() or j_scene_path.stat().st_size < 256:
                    raise RuntimeError(f"Scene generation failed for '{j_panel_key}' after {max_attempts} attempts")
                ep_copy = episode_scenes_dir / f"{j_panel_key}.png"
                self._mirror_to_episode(j_scene_path, ep_copy)
                with manifest_lock:
                    manifest[j_panel_key] = str(j_scene_path)
                with sigs_lock:
                    scene_signatures[j_panel_key] = j_panel_sig
                print(f"  ⚠️ Fallback static frame used for {j_panel_key} after repeated generation failures.")
                return

            worker_count = min(self.scene_concurrency, len(pending_llm_jobs))
            if worker_count > 1:
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    futures = [pool.submit(_llm_worker, job) for job in pending_llm_jobs]
                    for f in as_completed(futures):
                        f.result()
            else:
                for job in pending_llm_jobs:
                    _llm_worker(job)

            gen_count += budget.count

        manifest_path = scenes_dir / "scenes_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        with open(signatures_path, "w") as f:
            json.dump(scene_signatures, f, indent=2)

        print(f"Scene manifest: {len(manifest)} panels ({gen_count} generated)")
        return manifest

    def _force_resize(self, img_path: Path):
        with Image.open(img_path) as img:
            if img.size != self.resolution:
                print(f"  Resizing from {img.size} to {self.resolution}")
                img = img.resize(self.resolution, Image.Resampling.LANCZOS)
            img.save(img_path)

    @staticmethod
    def _mirror_to_episode(src: Path, dst: Path):
        try:
            if src.resolve() == dst.resolve():
                return
        except Exception:
            # If resolution fails, continue with safe copy logic below.
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink(missing_ok=True)
        try:
            # Prefer hardlink to avoid duplicate disk usage.
            dst.hardlink_to(src)
        except Exception:
            shutil.copy2(src, dst)
