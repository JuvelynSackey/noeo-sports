"""Enumerations shared across ORM models. Plain str enums so SQLite and
PostgreSQL both store them as text without extra dialect-specific work."""
from __future__ import annotations

import enum


class CompetitionStatus(str, enum.Enum):
    """MASTER BUILD PROMPT section 50."""

    DISCOVERED = "DISCOVERED"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    LIMITED_DATA = "LIMITED_DATA"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


class CompetitionType(str, enum.Enum):
    DOMESTIC_LEAGUE = "DOMESTIC_LEAGUE"
    CUP = "CUP"
    CONTINENTAL = "CONTINENTAL"
    INTERNATIONAL = "INTERNATIONAL"
    QUALIFYING = "QUALIFYING"
    PLAYOFF = "PLAYOFF"
    YOUTH = "YOUTH"
    WOMEN = "WOMEN"
    UNKNOWN = "UNKNOWN"


class CompetitionFormat(str, enum.Enum):
    """MASTER BUILD PROMPT section 7."""

    SINGLE_ROUND_ROBIN = "SINGLE_ROUND_ROBIN"
    DOUBLE_ROUND_ROBIN = "DOUBLE_ROUND_ROBIN"
    SPLIT_LEAGUE = "SPLIT_LEAGUE"
    PLAYOFFS = "PLAYOFFS"
    GROUP_STAGE = "GROUP_STAGE"
    KNOCKOUT = "KNOCKOUT"
    PROMOTION_RELEGATION_PLAYOFF = "PROMOTION_RELEGATION_PLAYOFF"
    IRREGULAR = "IRREGULAR"
    UNKNOWN = "UNKNOWN"


class SeasonStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


class DataQualityStatus(str, enum.Enum):
    """MASTER BUILD PROMPT section 15."""

    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class ValidationStatus(str, enum.Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    PENDING = "PENDING"


class FixtureStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    RESCHEDULED = "RESCHEDULED"
    IN_PLAY = "IN_PLAY"
    COMPLETED = "COMPLETED"


class ModelStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"
    RETIRED = "RETIRED"


class ForecastStatus(str, enum.Enum):
    """MASTER BUILD PROMPT section 61/62."""

    ACTIVE = "ACTIVE"
    LIMITED = "LIMITED"
    FAILED_VALIDATION = "FAILED_VALIDATION"


class DisagreementLevel(str, enum.Enum):
    LOW = "LOW_DISAGREEMENT"
    MEDIUM = "MEDIUM_DISAGREEMENT"
    HIGH = "HIGH_DISAGREEMENT"


class UserRole(str, enum.Enum):
    """MASTER BUILD PROMPT section 54."""

    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"
    SYSTEM = "SYSTEM"
