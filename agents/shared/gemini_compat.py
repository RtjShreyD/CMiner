import os
from typing import Any

from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv

load_dotenv()


class GeminiModelAdapter:
    """Compatibility adapter exposing generate_content() like the legacy SDK."""

    def __init__(self, client: genai.Client, model_name: str):
        self._client = client
        self.model_name = model_name

    @staticmethod
    def _convert_legacy_content_item(item: Any) -> Any:
        # Compatibility for legacy payload style:
        # {"mime_type": "image/png", "data": <bytes>} -> Part.from_bytes(...)
        if isinstance(item, dict) and "mime_type" in item and "data" in item:
            mime_type = item.get("mime_type")
            data = item.get("data")
            if isinstance(mime_type, str) and isinstance(data, (bytes, bytearray)):
                return genai_types.Part.from_bytes(data=bytes(data), mime_type=mime_type)
        return item

    def _normalize_contents(self, contents: Any) -> Any:
        if isinstance(contents, list):
            return [self._convert_legacy_content_item(item) for item in contents]
        return self._convert_legacy_content_item(contents)

    def generate_content(self, contents: Any):
        normalized = self._normalize_contents(contents)
        return self._client.models.generate_content(model=self.model_name, contents=normalized)


def make_gemini_client(required: bool = True) -> genai.Client | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        if required:
            raise ValueError("GEMINI_API_KEY not found in environment.")
        print("Warning: GEMINI_API_KEY not found in environment; proceeding in non-API/mock mode.")
        return None
    return genai.Client(api_key=api_key)


def get_model(model_name: str, *, required_key: bool = True) -> GeminiModelAdapter:
    client = make_gemini_client(required=required_key)
    if client is None:
        # Keep behavior deterministic in offline mode.
        raise ValueError("GEMINI_API_KEY not found in environment.")
    return GeminiModelAdapter(client, model_name)
