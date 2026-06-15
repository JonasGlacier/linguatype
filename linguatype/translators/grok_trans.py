"""Grok translation engine.

Uses xAI Grok API with a minimal system prompt. Defaults to ``grok-2``.

Requires a valid xAI API key.
"""

from __future__ import annotations

import requests

from .base import Translator, TranslationError
from .openai_trans import _LANG_NAMES, _SYSTEM_PROMPT


class GrokTranslator(Translator):
    """xAI Grok translation engine using raw HTTP requests."""

    def __init__(self, api_key: str, model: str = "grok-2") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return f"Grok ({self._model})"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("Grok API key is not configured.")

        lang_name = _LANG_NAMES.get(target_lang, target_lang)
        system = _SYSTEM_PROMPT.format(lang_name=lang_name)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }

        try:
            resp = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            err_msg = f"Grok request failed: {exc}"
            try:
                if exc.response is not None and exc.response.text:
                    err_json = exc.response.json()
                    if "error" in err_json and "message" in err_json["error"]:
                        err_msg = f"Grok error: {err_json['error']['message']}"
            except Exception:
                pass
            raise TranslationError(err_msg) from exc

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            raise TranslationError(f"Unexpected Grok response format: {exc}") from exc
