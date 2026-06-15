"""Anthropic translation engine.

Uses messages API with a minimal system prompt. Defaults to
``claude-3-5-sonnet-latest``.

Requires a valid Anthropic API key.
"""

from __future__ import annotations

import requests

from .base import Translator, TranslationError
from .openai_trans import _LANG_NAMES, _SYSTEM_PROMPT


class AnthropicTranslator(Translator):
    """Anthropic translation engine using raw HTTP requests."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-latest") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return f"Anthropic ({self._model})"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("Anthropic API key is not configured.")

        lang_name = _LANG_NAMES.get(target_lang, target_lang)
        system = _SYSTEM_PROMPT.format(lang_name=lang_name)

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": [
                {"role": "user", "content": text}
            ],
            "temperature": 0.2,
        }

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            err_msg = f"Anthropic request failed: {exc}"
            try:
                # Try to extract more details from JSON error response if possible
                if exc.response is not None and exc.response.text:
                    err_json = exc.response.json()
                    if "error" in err_json and "message" in err_json["error"]:
                        err_msg = f"Anthropic error: {err_json['error']['message']}"
            except Exception:
                pass
            raise TranslationError(err_msg) from exc

        try:
            data = resp.json()
            return data["content"][0]["text"].strip()
        except Exception as exc:
            raise TranslationError(f"Unexpected Anthropic response: {exc}") from exc
