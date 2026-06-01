from __future__ import annotations

from ege_notifier.config import Settings
from ege_notifier.providers.base import (
    FetchedResult,
    ResultsProvider,
    StudentQuery,
)
from ege_notifier.providers.ege_spb import EgeSpbProvider
from ege_notifier.providers.mock import MockResultsProvider


def build_provider(settings: Settings) -> ResultsProvider:
    if settings.provider == "mock":
        return MockResultsProvider(settings.mock_fixtures_path)
    if settings.provider == "ege_spb":
        return EgeSpbProvider(
            settings.ege_spb_base_url,
            timeout=settings.request_timeout,
            mode=settings.ege_spb_mode,
            wave=settings.ege_spb_wave,
        )
    raise ValueError(f"Неизвестный провайдер: {settings.provider}")


__all__ = [
    "ResultsProvider",
    "StudentQuery",
    "FetchedResult",
    "MockResultsProvider",
    "EgeSpbProvider",
    "build_provider",
]
