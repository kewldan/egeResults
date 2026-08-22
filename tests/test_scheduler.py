"""Тесты сборки планировщика: в архивном режиме job'ов нет вовсе."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from ege_notifier.config import Settings
from ege_notifier.scheduler import build_scheduler


def _settings(**overrides: object) -> Settings:
    base = dict(
        timezone="Europe/Moscow",
        check_cron=None,
        check_interval_seconds=21600,
        page_monitor_interval_seconds=300,
        archive_mode=False,
    )
    base.update(overrides)
    return cast(Settings, SimpleNamespace(**base))


def test_scheduler_has_check_job_normally():
    scheduler = build_scheduler(_settings(), results=None, notifier=None)  # type: ignore[arg-type]
    assert [job.id for job in scheduler.get_jobs()] == ["check_results"]


def test_scheduler_adds_monitor_job_when_monitor_given():
    scheduler = build_scheduler(
        _settings(),
        results=None,  # type: ignore[arg-type]
        notifier=None,  # type: ignore[arg-type]
        subscriptions=cast(object, object()),  # type: ignore[arg-type]
        monitor=cast(object, object()),  # type: ignore[arg-type]
    )
    assert {job.id for job in scheduler.get_jobs()} == {"check_results", "page_monitor"}


def test_scheduler_empty_in_archive_mode():
    """ARCHIVE_MODE=true: ни плановой проверки, ни монитора — даже если monitor передан."""
    scheduler = build_scheduler(
        _settings(archive_mode=True),
        results=None,  # type: ignore[arg-type]
        notifier=None,  # type: ignore[arg-type]
        subscriptions=cast(object, object()),  # type: ignore[arg-type]
        monitor=cast(object, object()),  # type: ignore[arg-type]
    )
    assert scheduler.get_jobs() == []
