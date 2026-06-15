"""OpenRouter translation engine.

Uses OpenRouter API with a minimal system prompt. Defaults to
``google/gemini-2.5-flash``.

Requires a valid OpenRouter API key.
"""

from __future__ import annotations

import requests

from .base import Translator, TranslationError
from .openai_trans import _LANG_NAMES, _SYSTEM_PROMPT


class OpenRouterTranslator(Translator):
    """OpenRouter translation engine using raw HTTP requests."""

    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return f"OpenRouter ({self._model})"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("OpenRouter API key is not configured.")

        lang_name = _LANG_NAMES.get(target_lang, target_lang)
        system = _SYSTEM_PROMPT.format(lang_name=lang_name)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/LinguaType/LinguaType",
            "X-Title": "LinguaType",
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
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            err_msg = f"OpenRouter request failed: {exc}"
            try:
                if exc.response is not None and exc.response.text:
                    err_json = exc.response.json()
                    if "error" in err_json and "message" in err_json["error"]:
                        err_msg = f"OpenRouter error: {err_json['error']['message']}"
            except Exception:
                pass
            raise TranslationError(err_msg) from exc

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            raise TranslationError(f"Unexpected OpenRouter response format: {exc}") from exc
