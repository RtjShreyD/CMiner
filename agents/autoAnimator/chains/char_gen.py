"""
Character Generator – Generates reference portraits with strict consistency.

Produces: chars/char_NAME.png + chars/chars_manifest.json
Resume: skips if character image already exists.
Art style is enforced from config for cross-episode consistency.
"""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging

from PIL import Image

from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate

logger = logging.getLogger(__name__)


class CharGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 5,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        aesthetic_guidance: str = "",
        tracker: Optional[LLMTracker] = None,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.aesthetic_guidance = aesthetic_guidance or ""
        self.tracker = tracker

    def _build_prompt(self, visual_prompt: str, bubble_style: str = "") -> str:
        width, height = self.resolution
        aesthetics = f" Aesthetic direction: {self.aesthetic_guidance}." if self.aesthetic_guidance else ""
        bubble_hint = (
            f" Include a small example speech bubble in the lower corner showing this character's "
            f"distinctive bubble style: {bubble_style}."
        ) if bubble_style else ""
        return (
            f"=== MANGA CHARACTER REFERENCE SHEET ===\n"
            f"Generate a full-body character reference portrait in MANGA / COMIC style. Art style: {self.art_style}.\n"
            f"MANDATORY visual requirements:\n"
            f"- Bold clean ink outlines on the character silhouette, face, clothing, and accessories.\n"
            f"- Flat cel-shaded or screentone fill — no photorealistic shading, no painterly brush texture.\n"
            f"- Expressive anime/manga facial features (distinct eyes, clear expression).\n"
            f"- FORBIDDEN: photorealism, 3D render look, oil painting, watercolor bleed.\n"
            f"CHARACTER DESCRIPTION (all traits below are IMMUTABLE — must appear exactly as described):\n"
            f"{visual_prompt}.\n"
            f"{aesthetics}"
            f"{bubble_hint}"
            f"Clean plain background (no scene elements), professional character sheet layout.\n"
            f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution. Manga/comic style ONLY."
        )

    def _build_object_prompt(self, visual_prompt: str, object_type: str = "") -> str:
        width, height = self.resolution
        aesthetics = f" Aesthetic direction: {self.aesthetic_guidance}." if self.aesthetic_guidance else ""
        type_hint = f" This is a {object_type}." if object_type else ""
        return (
            f"=== MANGA OBJECT REFERENCE SHEET ===\n"
            f"Generate a clear reference sheet for this story object in MANGA / COMIC style. Art style: {self.art_style}.{type_hint}\n"
            f"MANDATORY visual requirements:\n"
            f"- Bold clean ink outlines on all surfaces, edges, and detail elements.\n"
            f"- Flat cel-shaded or screentone fill — no photorealistic shading.\n"
            f"- Show the object from multiple angles if space allows (front, side, 3/4 perspective).\n"
            f"- Include label callouts / technical annotations if the object has dials, buttons, or text markings.\n"
            f"- FORBIDDEN: photorealism, 3D render look, oil painting, watercolor bleed.\n"
            f"OBJECT DESCRIPTION (all traits below are IMMUTABLE — must appear exactly as described):\n"
            f"{visual_prompt}.\n"
            f"{aesthetics}"
            f"Clean plain background (no scene elements), professional infographic/reference sheet layout.\n"
            f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution. Manga/comic style ONLY."
        )

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
                # Reject near-solid placeholder-like images.
                if all((mx - mn) < 8 for mn, mx in extrema):
                    return False
            return True
        except Exception:
            return False

    def run(self, manga_board: Dict[str, Any], session_dir: Path, force_names: Optional[set[str]] = None) -> Dict[str, str]:
        """Generate character portraits. Returns {char_name: image_path}."""
        print("--- Pipeline: Character Generation ---")
        logger.info("CharGen.run() started | session=%s", session_dir)
        chars_dir = session_dir / "chars"
        chars_dir.mkdir(parents=True, exist_ok=True)

        characters = manga_board.get("characters", [])
        manifest: Dict[str, str] = {}
        anchor_path = None
        gen_count = 0
        model = get_model(self.image_model_name)
        current_episode = max(1, int(manga_board.get("episode_number", 1) or 1))
        episode_chars_dir = session_dir / "episodes" / f"episode{current_episode}" / "chars"
        episode_chars_dir.mkdir(parents=True, exist_ok=True)

        existing_manifest_path = chars_dir / "chars_manifest.json"
        existing_manifest: Dict[str, str] = {}
        if existing_manifest_path.exists():
            try:
                parsed = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    existing_manifest = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                existing_manifest = {}

        # Phase 1: sequential pass — handle reuses/caches. Collect what needs generation.
        generation_queue: list[tuple[str, str, Path]] = []  # (name, safe_name, char_path)
        for i, char in enumerate(characters):
            if gen_count >= self.max_generations:
                print(f"Hit max_generations ({self.max_generations}), stopping.")
                break

            name = char.get("name", f"char_{i}")
            safe_name = name.replace(" ", "_").lower()
            char_path = chars_dir / f"char_{safe_name}.png"
            force_regen = bool(force_names and name in force_names)

            # Allow planner/director to explicitly reuse an existing character image.
            reuse_char = str(char.get("reuse_character_from", "") or "").strip()
            if not force_regen and reuse_char:
                source_path = existing_manifest.get(reuse_char)
                if source_path:
                    src = Path(source_path)
                    if src.exists() and self._is_valid_generated_image(src):
                        shutil.copy2(src, char_path)
                        manifest[name] = str(char_path)
                        ep_copy = episode_chars_dir / f"char_{safe_name}.png"
                        self._mirror_to_episode(char_path, ep_copy)
                        if anchor_path is None:
                            anchor_path = char_path
                        print(f"Reused character image for {name} from {reuse_char}.")
                        continue

            # Resume: skip only if existing image is valid.
            if char_path.exists():
                if force_regen:
                    print(f"Force-regenerating portrait for {name}.")
                    char_path.unlink(missing_ok=True)
                else:
                    if self._is_valid_generated_image(char_path):
                        print(f"Found existing portrait for {name}, skipping.")
                        manifest[name] = str(char_path)
                        ep_copy = episode_chars_dir / f"char_{safe_name}.png"
                        self._mirror_to_episode(char_path, ep_copy)
                        if anchor_path is None:
                            anchor_path = char_path
                        continue
                    print(f"Found invalid portrait for {name}, regenerating.")
                    char_path.unlink(missing_ok=True)

            visual_prompt = char.get("visual_prompt", char.get("description", "An anime character"))
            bubble_style = str(char.get("bubble_style", "") or "").strip()
            generation_queue.append((name, safe_name, char_path, visual_prompt, bubble_style))

        # Phase 2: generate queued characters.
        # First char is generated sequentially to establish the art-style anchor.
        # Remaining chars are generated in parallel using the first char as anchor.
        if generation_queue and gen_count < self.max_generations:
            first_name, first_safe, first_path, first_prompt, first_bubble = generation_queue[0]
            anchor_bytes = anchor_path.read_bytes() if anchor_path and anchor_path.exists() else None
            ok = self._generate_single_char(
                model, first_name, first_path, first_prompt, anchor_bytes, gen_count + 1,
                bubble_style=first_bubble,
            )
            if not ok:
                raise RuntimeError(f"Character generation failed for '{first_name}' after 3 attempts")
            gen_count += 1
            manifest[first_name] = str(first_path)
            ep_copy = episode_chars_dir / f"char_{first_safe}.png"
            self._mirror_to_episode(first_path, ep_copy)
            if anchor_path is None:
                anchor_path = first_path

            remaining = generation_queue[1:]
            if remaining and gen_count < self.max_generations:
                anchor_bytes_for_rest = anchor_path.read_bytes() if anchor_path and anchor_path.exists() else None
                slots_left = self.max_generations - gen_count
                capped = remaining[:slots_left]

                def _gen_worker(args: tuple) -> tuple[str, str, Path]:
                    rname, rsafe, rpath, rprompt, rbubble = args
                    ok = self._generate_single_char(
                        model, rname, rpath, rprompt, anchor_bytes_for_rest, -1,
                        bubble_style=rbubble,
                    )
                    if not ok:
                        raise RuntimeError(f"Character generation failed for '{rname}' after 3 attempts")
                    return rname, rsafe, rpath

                with ThreadPoolExecutor(max_workers=min(len(capped), self.max_generations)) as pool:
                    futures = {pool.submit(_gen_worker, item): item for item in capped}
                    for future in as_completed(futures):
                        rname, rsafe, rpath = future.result()
                        gen_count += 1
                        manifest[rname] = str(rpath)
                        ep_copy = episode_chars_dir / f"char_{rsafe}.png"
                        self._mirror_to_episode(rpath, ep_copy)

        # Save manifest and anchor metadata for cross-step consistency
        manifest_path = chars_dir / "chars_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        anchors = {}
        for char in characters:
            name = char.get("name")
            if name and name in manifest:
                anchors[name] = {
                    "image": manifest[name],
                    "visual_prompt": char.get("visual_prompt", char.get("description", "")),
                    "style": self.art_style,
                }

        # ── Phase 3: Generate object reference images.
        objects = manga_board.get("objects", []) if isinstance(manga_board.get("objects"), list) else []
        objects_generation_queue: list[tuple[str, str, Path, str, str]] = []
        for obj in objects:
            if gen_count >= self.max_generations:
                print(f"Hit max_generations ({self.max_generations}), skipping remaining objects.")
                break
            obj_name = str(obj.get("name", "") or "").strip()
            if not obj_name:
                continue
            safe_name = obj_name.replace(" ", "_").lower()
            obj_path = chars_dir / f"obj_{safe_name}.png"
            force_regen = bool(force_names and obj_name in force_names)
            if obj_path.exists() and not force_regen and self._is_valid_generated_image(obj_path):
                print(f"Found existing object reference for {obj_name}, skipping.")
                manifest[obj_name] = str(obj_path)
                ep_obj_copy = episode_chars_dir / f"obj_{safe_name}.png"
                self._mirror_to_episode(obj_path, ep_obj_copy)
                anchors[obj_name] = {
                    "image": str(obj_path),
                    "visual_prompt": obj.get("visual_prompt", obj.get("description", "")),
                    "style": self.art_style,
                    "entity_type": "object",
                    "object_type": obj.get("object_type", "prop"),
                }
                continue
            visual_prompt = str(obj.get("visual_prompt", obj.get("description", "A story object")) or "A story object")
            object_type = str(obj.get("object_type", "") or "")
            objects_generation_queue.append((obj_name, safe_name, obj_path, visual_prompt, object_type))

        if objects_generation_queue:
            obj_anchor_bytes = anchor_path.read_bytes() if anchor_path and anchor_path.exists() else None

            def _gen_object_worker(args: tuple) -> tuple[str, str, Path]:
                oname, osafe, opath, oprompt, otype = args
                obj_prompt = self._build_object_prompt(oprompt, otype)
                ok = self._generate_single_char(
                    model, oname, opath, oprompt, obj_anchor_bytes, -1,
                    custom_prompt=obj_prompt,
                )
                if not ok:
                    print(f"Warning: Object reference generation failed for '{oname}' — skipping.")
                    return oname, osafe, opath
                return oname, osafe, opath

            slots_left = max(0, self.max_generations - gen_count)
            capped_objs = objects_generation_queue[:slots_left] if slots_left else []
            if capped_objs:
                with ThreadPoolExecutor(max_workers=min(len(capped_objs), self.max_generations)) as pool:
                    obj_futures = {pool.submit(_gen_object_worker, item): item for item in capped_objs}
                    for future in as_completed(obj_futures):
                        oname, osafe, opath = future.result()
                        if opath.exists() and self._is_valid_generated_image(opath):
                            gen_count += 1
                            manifest[oname] = str(opath)
                            ep_obj_copy = episode_chars_dir / f"obj_{osafe}.png"
                            self._mirror_to_episode(opath, ep_obj_copy)
                            # Find the original object dict for visual_prompt / type
                            orig_obj = next((o for o in objects if str(o.get("name", "")).strip() == oname), {})
                            anchors[oname] = {
                                "image": str(opath),
                                "visual_prompt": orig_obj.get("visual_prompt", orig_obj.get("description", "")),
                                "style": self.art_style,
                                "entity_type": "object",
                                "object_type": orig_obj.get("object_type", "prop"),
                            }

        # Persist updated manifest and anchors (with objects included)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        anchor_path_json = chars_dir / "char_anchors.json"
        with open(anchor_path_json, "w") as f:
            json.dump(anchors, f, indent=2)

        print(f"Character manifest: {len(manifest)} characters ({gen_count} generated)")
        print(f"Character anchors saved to {anchor_path_json}")
        logger.info("CharGen.run() complete | %d entries generated | session=%s", gen_count, session_dir)
        return manifest

    def _generate_single_char(
        self,
        model: Any,
        name: str,
        char_path: Path,
        visual_prompt: str,
        anchor_bytes: Optional[bytes],
        slot_label: int,
        bubble_style: str = "",
        custom_prompt: str | None = None,
    ) -> bool:
        """Generate one character/object portrait. Returns True on success, False on failure."""
        prompt = custom_prompt if custom_prompt else self._build_prompt(visual_prompt, bubble_style=bubble_style)
        label = f"{slot_label}/{self.max_generations}" if slot_label > 0 else "parallel"
        print(f"Generating portrait ({label}): {name}")
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if anchor_bytes:
                    response = tracked_generate(
                        self.tracker,
                        model,
                        [
                            {"mime_type": "image/png", "data": anchor_bytes},
                            f"=== ART STYLE ANCHOR ===\n"
                            f"The attached image establishes the EXACT manga/comic art style for this series. "
                            f"Generate a NEW character in the identical art style: same ink outline weight, "
                            f"same cel-shading palette approach, same facial proportion style, same line quality. "
                            f"Do NOT change the rendering style. This must visually belong to the same series.\n"
                            f"=== END ANCHOR ===\n"
                            f"{prompt}",
                        ],
                        purpose="char_gen",
                    )
                else:
                    response = tracked_generate(self.tracker, model, prompt, purpose="char_gen")

                image_data = self._extract_inline_image_bytes(response)
                if not image_data:
                    raise ValueError("No image in response")

                char_path.write_bytes(image_data)
                self._force_resize(char_path)
                if not self._is_valid_generated_image(char_path):
                    raise ValueError("Generated image failed validation")

                print(f"  ✓ Generated: {char_path.name}")
                return True
            except Exception as e:
                print(f"  ✗ Attempt {attempt}/{max_attempts} failed for {name}: {e}")
                char_path.unlink(missing_ok=True)
        return False

    def _force_resize(self, img_path: Path):
        with Image.open(img_path) as img:
            if img.size != self.resolution:
                print(f"  Resizing from {img.size} to {self.resolution}")
                img = img.resize(self.resolution, Image.Resampling.LANCZOS)
            img.save(img_path)

    @staticmethod
    def _mirror_to_episode(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink(missing_ok=True)
        try:
            # Prefer hardlink to avoid duplicate disk usage.
            dst.hardlink_to(src)
        except Exception:
            shutil.copy2(src, dst)

    def generate_banner(
        self,
        project_name: str,
        session_dir: Path,
        characters: list,
        char_manifest: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Generate a wide panoramic show banner / title-card image.

        Saves to session_dir/banner/show_banner.png and returns the path on success.
        Returns None if generation fails.
        """
        banner_dir = session_dir / "banner"
        banner_dir.mkdir(parents=True, exist_ok=True)
        banner_path = banner_dir / "show_banner.png"

        if self._is_valid_generated_image(banner_path):
            logger.info("Banner already exists, skipping generation: %s", banner_path)
            return banner_path

        char_manifest = char_manifest or {}

        char_lines = [
            f"- {c.get('name', '')}: {str(c.get('visual_prompt', c.get('description', '')) or '').strip()[:200]}"
            for c in characters if c.get("name")
        ]
        char_roster = "\n".join(char_lines) if char_lines else "The main protagonist."
        aesthetics = f" Aesthetic direction: {self.aesthetic_guidance}." if self.aesthetic_guidance else ""

        banner_prompt = (
            f"=== SHOW BANNER / TITLE CARD ===\n"
            f"Generate a wide panoramic key-art banner for the animated series titled: '{project_name}'.\n"
            f"Art style: {self.art_style}. "
            f"MANDATORY: same EXACT ink outline weight, cel-shading, and line quality as the character reference attached.{aesthetics}\n"
            f"Composition: dramatic widescreen panoramic layout (16:9 cinematic), all main characters shown together in a signature group pose.\n"
            f"Include the series title '{project_name}' as bold stylized manga lettering in the upper or lower third.\n"
            f"Maintain exact skin tones, hair color, eye color, outfit colors, and accessory details for each character to match their reference portraits.\n"
            f"Characters to include:\n{char_roster}\n"
            f"Mood: epic, cinematic, series-premiere feel. Rich background environment hinting at the story world.\n"
            f"FORBIDDEN: photorealism, watercolor bleed, 3D render look.\n"
            f"CRITICAL: 1280x720 resolution (16:9 widescreen). Manga/comic style ONLY."
        )

        anchor_bytes: Optional[bytes] = None
        for img_path in char_manifest.values():
            p = Path(img_path)
            if p.exists() and self._is_valid_generated_image(p):
                anchor_bytes = p.read_bytes()
                break

        model = get_model(self.image_model_name)
        for attempt in range(1, 4):
            try:
                if anchor_bytes:
                    response = tracked_generate(
                        self.tracker,
                        model,
                        [
                            {"mime_type": "image/png", "data": anchor_bytes},
                            f"=== ART STYLE ANCHOR ===\n"
                            f"The attached image establishes the EXACT manga/comic art style for this series. "
                            f"Follow the same ink outline weight, cel-shading palette, facial proportions, and line quality.\n"
                            f"=== END ANCHOR ===\n"
                            f"{banner_prompt}",
                        ],
                        purpose="char_gen",
                    )
                else:
                    response = tracked_generate(self.tracker, model, banner_prompt, purpose="char_gen")

                image_data = self._extract_inline_image_bytes(response)
                if not image_data:
                    raise ValueError("No image in response")

                banner_path.write_bytes(image_data)
                self._force_resize_banner(banner_path)
                if not self._is_valid_generated_image(banner_path):
                    raise ValueError("Banner image failed validation")

                logger.info("Banner generated: %s", banner_path)
                print(f"  ✓ Show banner generated: {banner_path.name}")
                return banner_path

            except Exception as e:
                logger.warning("Banner generation attempt %d/3 failed: %s", attempt, e)
                print(f"  ✗ Banner attempt {attempt}/3 failed: {e}")
                banner_path.unlink(missing_ok=True)

        logger.error("Banner generation failed after 3 attempts.")
        return None

    def _force_resize_banner(self, img_path: Path):
        """Resize banner to 1280x720 widescreen."""
        banner_res = (1280, 720)
        with Image.open(img_path) as img:
            if img.size != banner_res:
                img = img.resize(banner_res, Image.Resampling.LANCZOS)
            img.save(img_path)
