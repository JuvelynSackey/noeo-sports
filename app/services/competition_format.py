"""Expected fixture counts per competition format — MASTER BUILD PROMPT
section 7. Used by the data-quality engine to judge fixture completeness
without assuming every competition is a simple round robin."""
from __future__ import annotations

from app.database.models.enums import CompetitionFormat


def expected_fixture_count(fmt: CompetitionFormat, number_of_teams: int | None) -> int | None:
    """Best-effort expectation; None means "we don't have a reliable formula
    for this format/size" so callers should skip the completeness check
    rather than penalize a competition for not matching a guess."""
    if not number_of_teams or number_of_teams < 2:
        return None

    n = number_of_teams
    if fmt == CompetitionFormat.SINGLE_ROUND_ROBIN:
        return n * (n - 1) // 2
    if fmt == CompetitionFormat.DOUBLE_ROUND_ROBIN:
        return n * (n - 1)
    return None
