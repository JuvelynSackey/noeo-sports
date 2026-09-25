import datetime as dt

from app.data.providers.schemas import SeasonDTO
from app.services.season_detection import detect_season_window, infer_season_status


def _season(season_id: str, start: str, end: str) -> SeasonDTO:
    return SeasonDTO(
        competition_id="C1",
        season_id=season_id,
        name=season_id,
        start_date=dt.date.fromisoformat(start),
        end_date=dt.date.fromisoformat(end),
        status="UNKNOWN",
        source_provider="test",
        source_record_id=season_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={},
    )


def test_detects_season_straddling_today():
    seasons = [
        _season("2023", "2023-08-01", "2024-05-31"),
        _season("2024", "2024-08-01", "2025-05-31"),
        _season("2025", "2025-08-01", "2026-05-31"),
    ]
    window = detect_season_window(seasons, today=dt.date(2025, 12, 1))
    assert window.current.season_id == "2025"
    assert window.previous.season_id == "2024"
    assert window.next is None


def test_falls_back_to_most_recently_finished_in_off_season():
    seasons = [
        _season("2023", "2023-08-01", "2024-05-31"),
        _season("2024", "2024-08-01", "2025-05-31"),
    ]
    # Between seasons (June/July) — no season straddles "today".
    window = detect_season_window(seasons, today=dt.date(2025, 6, 15))
    assert window.current.season_id == "2024"
    assert window.previous.season_id == "2023"


def test_infer_season_status_labels_match_window():
    seasons = [
        _season("2024", "2024-08-01", "2025-05-31"),
        _season("2025", "2025-08-01", "2026-05-31"),
    ]
    window = detect_season_window(seasons, today=dt.date(2025, 12, 1))
    assert infer_season_status(window, seasons[1]) == "ACTIVE"
    assert infer_season_status(window, seasons[0]) == "FINISHED"


def test_empty_seasons_returns_empty_window():
    window = detect_season_window([])
    assert window.current is None
    assert window.previous is None
    assert window.next is None
