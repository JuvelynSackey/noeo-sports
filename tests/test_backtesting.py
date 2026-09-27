from app.config import Settings
from app.database.models.modeling import CalibrationResult
from app.services.backtesting import CANDIDATES, BacktestingService
from tests.test_ensemble import _seed_realistic_league


def test_backtest_skipped_with_too_little_data(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=50, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)  # 30 matches total

    report = BacktestingService(db_session, settings).run(competition, "dixon_coles", True)

    assert not report.completed
    assert report.skipped_reason
    assert db_session.query(CalibrationResult).filter_by(competition_id=competition.id).count() == 0


def test_backtest_completes_with_enough_data(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)  # 120 matches

    report = BacktestingService(db_session, settings).run(competition, "dixon_coles", True)

    assert report.completed
    assert report.n_folds > 1
    assert len(report.predictions) > 0
    assert report.metrics is not None
    assert report.metrics.n_matches == len(report.predictions)
    assert report.calibration_error is not None
    assert report.exact_score_mean_log_loss is not None
    assert report.total_goals_rmse is not None
    assert report.home_goal_residual_std is not None


def test_predictions_only_cover_matches_after_initial_train_window(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)  # 120 matches

    report = BacktestingService(db_session, settings).run(competition, "poisson_baseline", False)

    assert report.completed
    # At most (120 - 15) matches could ever be predicted out-of-sample.
    assert len(report.predictions) <= 120 - 15


def test_run_all_covers_every_candidate(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)

    reports = BacktestingService(db_session, settings).run_all(competition)

    assert set(reports) == {name for name, _ in CANDIDATES}
    assert all(r.completed for r in reports.values())


def test_backtest_persists_nothing_when_no_live_model_version(db_session):
    # No ModelTrainingService run -> no ENABLED ModelVersion to attach the result to.
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)

    report = BacktestingService(db_session, settings).run(competition, "dixon_coles", True)

    assert report.completed  # the backtest itself doesn't need a live ModelVersion to run
    assert db_session.query(CalibrationResult).filter_by(competition_id=competition.id).count() == 0


def test_backtest_persists_when_live_model_version_exists(db_session):
    from app.services.model_training import ModelTrainingService

    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)

    BacktestingService(db_session, settings).run(competition, "dixon_coles", True)

    record = db_session.query(CalibrationResult).filter_by(
        competition_id=competition.id, forecast_type="walk_forward_backtest", method="dixon_coles"
    ).one()
    assert record.brier_score is not None
    assert record.reliability_curve["n_folds"] > 1
