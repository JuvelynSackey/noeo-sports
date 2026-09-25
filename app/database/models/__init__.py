"""Import every model module so Base.metadata / Alembic autogenerate sees all tables."""
from app.database.models.audit import AuditLog, User  # noqa: F401
from app.database.models.competitions import Competition, Season  # noqa: F401
from app.database.models.fixtures import Fixture, MatchStatistic, Result, XGData  # noqa: F401
from app.database.models.league import LeagueParameter, TeamStrength  # noqa: F401
from app.database.models.modeling import CalibrationResult, ModelVersion, ModelWeight  # noqa: F401
from app.database.models.monitoring import ModelMonitoring, SystemEvent  # noqa: F401
from app.database.models.predictions import (  # noqa: F401
    Prediction,
    PredictionSnapshot,
    ScenarioPrediction,
)
from app.database.models.quality import DataQuality, ProviderRecord  # noqa: F401
from app.database.models.teams import Team, TeamAlias  # noqa: F401
