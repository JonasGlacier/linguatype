"""Abstract base class for translation engines."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TranslationError(Exception):
    """Raised when a translation request fails."""


class Translator(ABC):
    """Interface every translation engine must implement."""

    @abstractmethod
    def translate(self, text: str, target_lang: str) -> str:
        """Translate *text* into *target_lang* (BCP-47 code, e.g. ``"en"``, ``"zh-CN"``).

        Returns the translated string.
        Raises :class:`TranslationError` on failure.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name shown in the UI."""
