from app.data.providers.mock_provider import MockProvider, _round_robin_pairs


def test_round_robin_covers_every_pair_exactly_once():
    teams = ["A", "B", "C", "D"]
    pairs = _round_robin_pairs(teams)
    unordered = {frozenset(p) for p in pairs}
    assert len(pairs) == 6  # n*(n-1)/2 for single round robin
    assert len(unordered) == 6
    for team in teams:
        appearances = sum(1 for p in pairs if team in p)
        assert appearances == 3  # plays every other team once


def test_competitions_have_seasons_and_status():
    provider = MockProvider()
    competitions = provider.competitions()
    assert {c.competition_id for c in competitions} == {"MOCK-D1", "MOCK-D2"}
    for comp in competitions:
        assert comp.source_provider == "mock"
        seasons = provider.seasons(comp.competition_id)
        assert len(seasons) >= 1


def test_fixtures_and_results_are_consistent():
    provider = MockProvider()
    fixtures = provider.fixtures("MOCK-D1", "2024")
    results = provider.results("MOCK-D1", "2024")

    # 2024 season is FINISHED in the mock world -> every fixture has a result.
    finished_fixture_ids = {f.fixture_id for f in fixtures if f.status == "COMPLETED"}
    result_fixture_ids = {r.fixture_id for r in results}
    assert finished_fixture_ids == result_fixture_ids
    assert result_fixture_ids
    assert result_fixture_ids <= {f.fixture_id for f in fixtures}

    for result in results:
        assert result.home_goals >= 0
        assert result.away_goals >= 0
        assert result.home_goals_first_half <= result.home_goals
        assert result.away_goals_first_half <= result.away_goals


def test_statistics_only_available_for_finished_fixtures():
    provider = MockProvider()
    fixtures = provider.fixtures("MOCK-D1", "2024")
    finished = next(f for f in fixtures if f.status == "COMPLETED")
    stats = provider.statistics(finished.fixture_id)
    assert stats
    stat_names = {s.stat_name for s in stats}
    assert "corners" in stat_names


def test_xg_reported_as_unavailable():
    provider = MockProvider()
    fixtures = provider.fixtures("MOCK-D1", "2024")
    assert provider.xg(fixtures[0].fixture_id) is None


def test_current_season_has_both_completed_and_scheduled_fixtures():
    provider = MockProvider()
    fixtures = provider.fixtures("MOCK-D1", "2026")
    statuses = {f.status for f in fixtures}
    assert "SCHEDULED" in statuses
    assert "COMPLETED" in statuses


def test_deterministic_with_fixed_seed():
    a = MockProvider(seed=7).results("MOCK-D1", "2024")
    b = MockProvider(seed=7).results("MOCK-D1", "2024")
    assert [r.home_goals for r in a] == [r.home_goals for r in b]
    assert [r.away_goals for r in a] == [r.away_goals for r in b]
