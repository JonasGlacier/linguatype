"""DeepL translation engine.

Requires a DeepL API key (free tier available at deepl.com).
Install: ``pip install deepl``
"""

from __future__ import annotations

from .base import Translator, TranslationError

# DeepL language code normalisation table
_LANG_MAP: dict[str, str] = {
    "zh-CN": "ZH",
    "zh-TW": "ZH",
    "zh": "ZH",
    "en": "EN-US",
    "en-GB": "EN-GB",
    "en-US": "EN-US",
    "de": "DE",
    "fr": "FR",
    "es": "ES",
    "pt": "PT-PT",
    "pt-BR": "PT-BR",
    "it": "IT",
    "nl": "NL",
    "pl": "PL",
    "ru": "RU",
    "ja": "JA",
    "ko": "KO",
}


class DeepLTranslator(Translator):
    """DeepL translation engine backed by the official Python SDK."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: object | None = None

    def _get_client(self):
        if self._client is None:
            try:
                import deepl  # type: ignore[import]
            except ImportError as exc:
                raise TranslationError(
                    "deepl package not installed. Run: pip install deepl"
                ) from exc
            self._client = deepl.Translator(self._api_key)
        return self._client

    @property
    def name(self) -> str:
        return "DeepL"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("DeepL API key is not configured.")

        tl = _LANG_MAP.get(target_lang, target_lang.upper())
        try:
            client = self._get_client()
            result = client.translate_text(text, target_lang=tl)
            return result.text
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"DeepL translation failed: {exc}") from exc
