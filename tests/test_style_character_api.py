import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app


class StyleCharacterApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_style_profile_roundtrip(self):
        suffix = uuid4().hex[:8]
        profile_id = f"style-{suffix}"

        profile_payload = {
            "id": profile_id,
            "name": "Cyber Neon Subtitle",
            "category": "subtitle",
            "version": "v1",
            "tags": ["neon", "subtitle"],
            "preview_assets": {"thumbnail": "samples/subtitle-neon.png"},
            "config_json": {"font": "Orbitron", "stroke": 2},
        }
        create_profile = self.client.post("/api/styles/profiles", json=profile_payload)
        self.assertEqual(create_profile.status_code, 200)
        self.assertEqual(create_profile.json()["id"], profile_id)

        list_profiles = self.client.get("/api/styles/profiles")
        self.assertEqual(list_profiles.status_code, 200)
        ids = [r["id"] for r in list_profiles.json()]
        self.assertIn(profile_id, ids)

        get_profile = self.client.get(f"/api/styles/profiles/{profile_id}")
        self.assertEqual(get_profile.status_code, 200)
        self.assertEqual(get_profile.json()["name"], "Cyber Neon Subtitle")

    def test_character_pack_roundtrip(self):
        suffix = uuid4().hex[:8]
        pack_id = f"chars-{suffix}"

        payload = {
            "id": pack_id,
            "name": f"Core Detective Cast {suffix}",
            "source_agent": "charGen",
            "tags": ["manga", "detective"],
            "characters": [
                {
                    "character_id": "kaelen-thorne",
                    "display_name": "Kaelen Thorne",
                    "archetype": "hero",
                    "visual_prompt": "Tall detective in futuristic trench coat",
                    "tags": ["lead"],
                    "anchor_images": ["library/styles/previews/render-cinematic-anime.png"],
                    "metadata": {"voice_profile": "hero"},
                }
            ],
        }

        create_pack = self.client.post("/api/characters/packs", json=payload)
        self.assertEqual(create_pack.status_code, 200)
        self.assertEqual(create_pack.json()["id"], pack_id)

        list_packs = self.client.get("/api/characters/packs")
        self.assertEqual(list_packs.status_code, 200)
        ids = [r["id"] for r in list_packs.json()]
        self.assertIn(pack_id, ids)

        get_pack = self.client.get(f"/api/characters/packs/{pack_id}")
        self.assertEqual(get_pack.status_code, 200)
        body = get_pack.json()
        self.assertEqual(body["name"], f"Core Detective Cast {suffix}")
        self.assertEqual(body["characters"][0]["display_name"], "Kaelen Thorne")


if __name__ == "__main__":
    unittest.main()
