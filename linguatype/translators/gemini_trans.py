"""Gemini translation engine.

Uses Google AI Studio's Gemini API (generateContent) with a minimal system prompt.
Defaults to ``gemini-1.5-flash``.

Requires a valid Google Gemini API key.
"""

from __future__ import annotations

import requests

from .base import Translator, TranslationError
from .openai_trans import _LANG_NAMES, _SYSTEM_PROMPT


class GeminiTranslator(Translator):
    """Google Gemini translation engine using raw HTTP requests."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return f"Gemini ({self._model})"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("Gemini API key is not configured.")

        lang_name = _LANG_NAMES.get(target_lang, target_lang)
        system = _SYSTEM_PROMPT.format(lang_name=lang_name)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent?key={self._api_key}"

        headers = {
            "Content-Type": "application/json",
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system}]
            },
            "generationConfig": {
                "temperature": 0.2
            }
        }

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            err_msg = f"Gemini request failed: {exc}"
            try:
                if exc.response is not None and exc.response.text:
                    err_json = exc.response.json()
                    if "error" in err_json and "message" in err_json["error"]:
                        err_msg = f"Gemini error: {err_json['error']['message']}"
            except Exception:
                pass
            raise TranslationError(err_msg) from exc

        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            translated_text = "".join(part["text"] for part in parts if "text" in part)
            return translated_text.strip()
        except Exception as exc:
            raise TranslationError(f"Unexpected Gemini response format: {exc}") from exc
