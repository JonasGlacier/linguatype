"""Google Translate engine using the public (free) endpoint.

No API key required.  Uses the same JSON endpoint that translate.google.com
calls from the browser.  Heavy usage may be rate-limited by Google.
"""

from __future__ import annotations

import re
import urllib.parse

import requests

from .base import Translator, TranslationError

_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 10  # seconds


def _flatten(obj: object) -> str:
    """Recursively flatten nested lists/strings from the Google response."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "".join(_flatten(item) for item in obj if item is not None)
    return ""


class GoogleTranslator(Translator):
    """Free Google Translate via the public JSON endpoint."""

    @property
    def name(self) -> str:
        return "Google Translate"

    def translate(self, text: str, target_lang: str) -> str:
        # Normalise zh variants that Google expects
        lang_map = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "zh": "zh-CN"}
        tl = lang_map.get(target_lang, target_lang)

        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": tl,
            "dt": "t",
            "q": text,
        }
        try:
            resp = requests.get(_ENDPOINT, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise TranslationError(f"Google Translate request failed: {exc}") from exc

        try:
            data = resp.json()
            # data[0] is a list of [translated_chunk, original_chunk, ...]
            parts = [seg[0] for seg in data[0] if seg and seg[0]]
            return "".join(parts)
        except Exception as exc:
            raise TranslationError(f"Unexpected Google response: {exc}") from exc
