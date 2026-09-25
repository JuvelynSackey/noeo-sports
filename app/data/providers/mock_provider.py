"""Offline, deterministic provider for local development and tests.

Reads a small static "world" (competitions + team registry) from JSON, then
*generates* a round-robin fixture list and results with a seeded RNG so the
whole pipeline (discovery -> teams -> fixtures -> results -> statistics) is
exercisable with no network access and no API key. Never used in production.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any

from app.data.providers.base import FootballDataProvider
from app.data.providers.schemas import (
    CompetitionDTO,
    FixtureDTO,
    ResultDTO,
    SeasonDTO,
    StatisticDTO,
    TeamDTO,
    XGDTO,
)

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "mock_fixtures"


def _round_robin_pairs(team_ids: list[str]) -> list[tuple[str, str]]:
    """Circle-method single round robin: returns (home, away) pairs in play order."""
    ids = list(team_ids)
    if len(ids) % 2 == 1:
        ids.append("BYE")
    n = len(ids)
    rounds: list[list[tuple[str, str]]] = []
    for round_no in range(n - 1):
        pairs = []
        for i in range(n // 2):
            home, away = ids[i], ids[n - 1 - i]
            if "BYE" not in (home, away):
                pairs.append((home, away) if round_no % 2 == 0 else (away, home))
        rounds.append(pairs)
        ids.insert(1, ids.pop())
    return [pair for round_pairs in rounds for pair in round_pairs]


class MockProvider(FootballDataProvider):
    name = "mock"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._competitions_raw: list[dict[str, Any]] = json.loads(
            (_FIXTURE_DIR / "competitions.json").read_text(encoding="utf-8")
        )
        self._team_registry: dict[str, dict[str, Any]] = json.loads(
            (_FIXTURE_DIR / "team_registry.json").read_text(encoding="utf-8")
        )
        self._team_map: dict[str, list[str]] = json.loads(
            (_FIXTURE_DIR / "teams.json").read_text(encoding="utf-8")
        )

    def _provenance(self, source_record_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_provider": self.name,
            "source_record_id": source_record_id,
            "retrieved_at": dt.datetime.now(dt.timezone.utc),
            "raw_payload": raw,
        }

    def _competition_raw(self, competition_id: str) -> dict[str, Any]:
        for comp in self._competitions_raw:
            if comp["competition_id"] == competition_id:
                return comp
        raise KeyError(f"unknown mock competition {competition_id}")

    def competitions(self) -> list[CompetitionDTO]:
        results: list[CompetitionDTO] = []
        for comp in self._competitions_raw:
            current_season = comp["seasons"][-1]
            results.append(
                CompetitionDTO(
                    competition_id=comp["competition_id"],
                    competition_name=comp["competition_name"],
                    country=comp.get("country"),
                    region=comp.get("region"),
                    competition_type=comp.get("competition_type", "UNKNOWN"),
                    division_level=comp.get("division_level"),
                    season_id=current_season["season_id"],
                    season_name=current_season["name"],
                    start_date=_date(current_season["start_date"]),
                    end_date=_date(current_season["end_date"]),
                    status=current_season["status"],
                    number_of_teams=comp.get("number_of_teams"),
                    competition_format=comp.get("competition_format", "UNKNOWN"),
                    **self._provenance(comp["competition_id"], comp),
                )
            )
        return results

    def seasons(self, competition_id: str) -> list[SeasonDTO]:
        comp = self._competition_raw(competition_id)
        return [
            SeasonDTO(
                competition_id=competition_id,
                season_id=season["season_id"],
                name=season["name"],
                start_date=_date(season["start_date"]),
                end_date=_date(season["end_date"]),
                status=season["status"],
                current_matchday=None,
                **self._provenance(f"{competition_id}:{season['season_id']}", season),
            )
            for season in comp["seasons"]
        ]

    def teams(self, competition_id: str, season_id: str) -> list[TeamDTO]:
        team_ids = self._team_map[competition_id]
        return [
            TeamDTO(
                team_id=tid,
                name=self._team_registry[tid]["name"],
                short_name=None,
                country=self._team_registry[tid].get("country"),
                founded=None,
                venue=None,
                **self._provenance(tid, self._team_registry[tid]),
            )
            for tid in team_ids
        ]

    def _generate_matches(self, competition_id: str, season_id: str) -> list[dict[str, Any]]:
        comp = self._competition_raw(competition_id)
        season = next(s for s in comp["seasons"] if s["season_id"] == season_id)
        team_ids = self._team_map[competition_id]
        pairs = _round_robin_pairs(team_ids)

        start = _date(season["start_date"])
        end = _date(season["end_date"])
        total_days = max((end - start).days, len(pairs))
        step = max(total_days // max(len(pairs), 1), 1)

        rng = random.Random(f"{self._seed}:{competition_id}:{season_id}")
        today = dt.date.today()
        matches = []
        for idx, (home, away) in enumerate(pairs):
            kickoff_date = start + dt.timedelta(days=idx * step)
            kickoff = dt.datetime.combine(kickoff_date, dt.time(hour=15, tzinfo=dt.timezone.utc))
            fixture_id = f"{competition_id}:{season_id}:{idx:03d}"
            is_finished = season["status"] == "FINISHED" or kickoff_date <= today
            match: dict[str, Any] = {
                "fixture_id": fixture_id,
                "round": str(idx // max(len(team_ids) // 2, 1) + 1),
                "kickoff": kickoff,
                "home": home,
                "away": away,
                "status": "COMPLETED" if is_finished else "SCHEDULED",
            }
            if is_finished:
                match["home_goals"] = rng.choices([0, 1, 2, 3, 4], weights=[18, 32, 28, 14, 8])[0]
                match["away_goals"] = rng.choices([0, 1, 2, 3, 4], weights=[24, 32, 25, 12, 7])[0]
                match["home_goals_ht"] = rng.randint(0, match["home_goals"])
                match["away_goals_ht"] = rng.randint(0, match["away_goals"])
            matches.append(match)
        return matches

    def fixtures(self, competition_id: str, season_id: str) -> list[FixtureDTO]:
        return [
            FixtureDTO(
                fixture_id=m["fixture_id"],
                competition_id=competition_id,
                season_id=season_id,
                round=m["round"],
                kickoff_utc=m["kickoff"],
                home_team_id=m["home"],
                away_team_id=m["away"],
                venue=None,
                status=m["status"],
                **self._provenance(m["fixture_id"], m),
            )
            for m in self._generate_matches(competition_id, season_id)
        ]

    def results(self, competition_id: str, season_id: str) -> list[ResultDTO]:
        return [
            ResultDTO(
                fixture_id=m["fixture_id"],
                home_goals=m["home_goals"],
                away_goals=m["away_goals"],
                home_goals_first_half=m["home_goals_ht"],
                away_goals_first_half=m["away_goals_ht"],
                **self._provenance(m["fixture_id"], m),
            )
            for m in self._generate_matches(competition_id, season_id)
            if m["status"] == "COMPLETED"
        ]

    def statistics(self, fixture_id: str) -> list[StatisticDTO]:
        competition_id, season_id, _ = fixture_id.split(":")
        for m in self._generate_matches(competition_id, season_id):
            if m["fixture_id"] != fixture_id or m["status"] != "COMPLETED":
                continue
            rng = random.Random(f"{self._seed}:{fixture_id}:stats")
            stats = []
            for team_id, prefix in ((m["home"], "home"), (m["away"], "away")):
                stats.extend(
                    [
                        StatisticDTO(
                            fixture_id=fixture_id,
                            team_id=team_id,
                            stat_name="corners",
                            stat_value=float(rng.randint(2, 9)),
                            **self._provenance(f"{fixture_id}:{team_id}:corners", m),
                        ),
                        StatisticDTO(
                            fixture_id=fixture_id,
                            team_id=team_id,
                            stat_name="yellow_cards",
                            stat_value=float(rng.randint(0, 4)),
                            **self._provenance(f"{fixture_id}:{team_id}:yellow_cards", m),
                        ),
                        StatisticDTO(
                            fixture_id=fixture_id,
                            team_id=team_id,
                            stat_name="red_cards",
                            stat_value=float(rng.choices([0, 1], weights=[95, 5])[0]),
                            **self._provenance(f"{fixture_id}:{team_id}:red_cards", m),
                        ),
                    ]
                )
            return stats
        return []

    def xg(self, fixture_id: str) -> XGDTO | None:
        # The mock world deliberately does not model xG so the pipeline exercises
        # the DATA_UNAVAILABLE fallback path described in section 20.
        return None


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)
