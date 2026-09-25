from app.data.providers.mock_provider import MockProvider
from app.database.models.enums import ModelStatus
from app.database.models.league import TeamStrength
from app.database.models.modeling import ModelVersion
from app.services.sync_orchestrator import FullSyncService


def test_full_sync_trains_models_for_data_rich_competition_and_disables_for_sparse_one(db_session):
    report = FullSyncService(db_session, MockProvider()).run()

    d1_training = report.model_training["mock:MOCK-D1"]
    d2_training = report.model_training["mock:MOCK-D2"]

    assert d1_training.eligibility.dixon_coles.eligible
    assert d1_training.dixon_coles_version is not None
    assert d1_training.poisson_version is not None
    assert d1_training.team_strength_rows > 0

    assert not d2_training.eligibility.dixon_coles.eligible
    assert d2_training.skipped_reason and "insufficient" in d2_training.skipped_reason

    enabled_by_competition: dict[int, set[str]] = {}
    for v in db_session.query(ModelVersion).filter_by(status=ModelStatus.ENABLED).all():
        enabled_by_competition.setdefault(v.competition_id, set()).add(v.model_name)

    d1_competition_id = next(iter(v.competition_id for v in db_session.query(ModelVersion).all() if v.version == d1_training.dixon_coles_version))
    # D1 has enough goal AND corners/cards/first-half data for every Phase 3+5 model.
    assert enabled_by_competition[d1_competition_id] == {
        "dixon_coles",
        "poisson_baseline",
        "hierarchical_model",
        "first_half_model",
        "corners_model",
        "cards_model",
    }


def test_rerunning_full_sync_retires_the_previous_model_version(db_session):
    provider = MockProvider()
    FullSyncService(db_session, provider).run()
    first_versions = {v.version for v in db_session.query(ModelVersion).filter_by(model_name="dixon_coles", status=ModelStatus.ENABLED)}

    FullSyncService(db_session, provider).run()
    second_versions = {v.version for v in db_session.query(ModelVersion).filter_by(model_name="dixon_coles", status=ModelStatus.ENABLED)}

    assert first_versions.isdisjoint(second_versions)
    retired = db_session.query(ModelVersion).filter_by(model_name="dixon_coles", status=ModelStatus.RETIRED).all()
    assert {v.version for v in retired} == first_versions


def test_disabled_competition_records_reason_and_no_team_strength(db_session):
    provider = MockProvider()
    report = FullSyncService(db_session, provider).run()
    d2_training = report.model_training["mock:MOCK-D2"]
    assert d2_training.team_strength_rows == 0

    d2 = [mv for mv in db_session.query(ModelVersion).all() if mv.disabled_reason][0]
    assert d2.status == ModelStatus.DISABLED
    assert d2.disabled_reason is not None


def test_team_strength_rows_have_all_expected_fields(db_session):
    FullSyncService(db_session, MockProvider()).run()
    row = db_session.query(TeamStrength).first()
    assert row is not None
    assert row.attack_strength is not None
    assert row.defence_strength is not None
    assert row.opponent_adjusted_strength == row.attack_strength - row.defence_strength
    assert row.uncertainty is not None and row.uncertainty > 0
    assert row.method == "dixon_coles"
