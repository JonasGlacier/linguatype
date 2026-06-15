"""OpenAI translation engine.

Uses chat completions with a minimal system prompt.  Defaults to
``gpt-4o-mini`` which provides excellent quality at low cost.

Requires ``pip install openai`` and a valid OpenAI API key.
"""

from __future__ import annotations

# BCP-47 → human-readable name used in the system prompt
_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "en-US": "English",
    "en-GB": "British English",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
}

_SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate the user's text into {lang_name}. "
    "Return ONLY the translated text with no explanations, no quotes, "
    "no additional commentary."
)

from .base import Translator, TranslationError


class OpenAITranslator(Translator):
    """OpenAI chat-completion translation engine."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._client: object | None = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai  # type: ignore[import]
            except ImportError as exc:
                raise TranslationError(
                    "openai package not installed. Run: pip install openai"
                ) from exc
            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    @property
    def name(self) -> str:
        return f"OpenAI ({self._model})"

    def translate(self, text: str, target_lang: str) -> str:
        if not self._api_key:
            raise TranslationError("OpenAI API key is not configured.")

        lang_name = _LANG_NAMES.get(target_lang, target_lang)
        system = _SYSTEM_PROMPT.format(lang_name=lang_name)

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            return response.choices[0].message.content.strip()
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"OpenAI translation failed: {exc}") from exc
