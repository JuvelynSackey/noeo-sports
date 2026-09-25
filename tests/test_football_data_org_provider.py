import httpx
import respx

from app.data.providers.football_data_org import FootballDataOrgProvider

BASE_URL = "https://api.football-data.org/v4"


def _provider() -> FootballDataOrgProvider:
    return FootballDataOrgProvider(api_key="test-key", base_url=BASE_URL)


@respx.mock
def test_competitions_maps_provider_payload():
    respx.get(f"{BASE_URL}/competitions").mock(
        return_value=httpx.Response(
            200,
            json={
                "competitions": [
                    {
                        "id": 2021,
                        "name": "Premier League",
                        "type": "LEAGUE",
                        "area": {"name": "England"},
                        "currentSeason": {
                            "startDate": "2025-08-01",
                            "endDate": "2026-05-31",
                            "numberOfAvailableTeams": 20,
                        },
                    }
                ]
            },
        )
    )

    provider = _provider()
    competitions = provider.competitions()

    assert len(competitions) == 1
    comp = competitions[0]
    assert comp.competition_id == "2021"
    assert comp.competition_name == "Premier League"
    assert comp.country == "England"
    assert comp.competition_type == "DOMESTIC_LEAGUE"
    assert comp.season_id == "2025"
    assert comp.number_of_teams == 20
    assert comp.source_provider == "football_data_org"


@respx.mock
def test_results_only_include_finished_matches_with_scores():
    respx.get(f"{BASE_URL}/competitions/2021/matches").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 1,
                        "status": "FINISHED",
                        "utcDate": "2025-08-16T14:00:00Z",
                        "matchday": 1,
                        "homeTeam": {"id": 10},
                        "awayTeam": {"id": 20},
                        "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
                    },
                    {
                        "id": 2,
                        "status": "SCHEDULED",
                        "utcDate": "2025-08-23T14:00:00Z",
                        "matchday": 2,
                        "homeTeam": {"id": 30},
                        "awayTeam": {"id": 40},
                        "score": {"fullTime": {"home": None, "away": None}},
                    },
                ]
            },
        )
    )

    provider = _provider()
    results = provider.results("2021", "2025")

    assert len(results) == 1
    assert results[0].fixture_id == "1"
    assert results[0].home_goals == 2
    assert results[0].away_goals == 1
    assert results[0].home_goals_first_half == 1


@respx.mock
def test_fixtures_map_all_statuses():
    respx.get(f"{BASE_URL}/competitions/2021/matches").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 1,
                        "status": "POSTPONED",
                        "utcDate": "2025-08-16T14:00:00Z",
                        "matchday": 1,
                        "homeTeam": {"id": 10},
                        "awayTeam": {"id": 20},
                    }
                ]
            },
        )
    )

    provider = _provider()
    fixtures = provider.fixtures("2021", "2025")

    assert len(fixtures) == 1
    assert fixtures[0].status == "POSTPONED"


def test_statistics_and_xg_report_unavailable():
    provider = _provider()
    assert provider.statistics("1") == []
    assert provider.xg("1") is None


@respx.mock
def test_retries_on_rate_limit_then_succeeds():
    route = respx.get(f"{BASE_URL}/competitions").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"competitions": []}),
        ]
    )

    provider = _provider()
    result = provider.competitions()

    assert result == []
    assert route.call_count == 2
