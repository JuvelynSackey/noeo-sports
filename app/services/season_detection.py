"""Automatic season detection — MASTER BUILD PROMPT section 4.

Given every season a provider reports for a competition, work out which one
is current/previous/next so current-season and historical-season data never
get mixed by the rest of the system.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.data.providers.schemas import SeasonDTO


@dataclass(frozen=True)
class SeasonWindow:
    current: SeasonDTO | None
    previous: SeasonDTO | None
    next: SeasonDTO | None


def detect_season_window(seasons: list[SeasonDTO], today: dt.date | None = None) -> SeasonWindow:
    today = today or dt.date.today()
    if not seasons:
        return SeasonWindow(current=None, previous=None, next=None)

    dated = [s for s in seasons if s.start_date and s.end_date]
    undated = [s for s in seasons if not (s.start_date and s.end_date)]

    current = next((s for s in dated if s.start_date <= today <= s.end_date), None)
    if current is None:
        # No season straddles today (off-season, or provider hasn't rolled the
        # fixture list yet) — fall back to the most recently reported season
        # that has already finished, which is a safer default than guessing forward.
        finished = sorted((s for s in dated if s.end_date < today), key=lambda s: s.end_date)
        current = finished[-1] if finished else None
        if current is None and undated:
            current = undated[0]

    previous = None
    next_season = None
    if current and current.start_date:
        before = sorted((s for s in dated if s.end_date < current.start_date), key=lambda s: s.end_date)
        previous = before[-1] if before else None
        after = sorted((s for s in dated if s.start_date > current.end_date), key=lambda s: s.start_date)
        next_season = after[0] if after else None

    return SeasonWindow(current=current, previous=previous, next=next_season)


def infer_season_status(window: SeasonWindow, season: SeasonDTO) -> str:
    if window.current and season.season_id == window.current.season_id:
        return "ACTIVE"
    if window.next and season.season_id == window.next.season_id:
        return "UPCOMING"
    return "FINISHED"
