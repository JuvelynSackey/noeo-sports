"""Teams and team aliases — MASTER BUILD PROMPT section 5 (canonical team IDs,
so renamed/merged/reserve teams don't break historical continuity)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.mixins import ProvenanceMixin, TimestampMixin


class Team(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("source_provider", "source_record_id", name="uq_team_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_team_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    current_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(128))
    is_reserve_team: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_dissolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    merged_into_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))

    aliases: Mapped[list["TeamAlias"]] = relationship(back_populates="team", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Team {self.canonical_team_id} {self.current_name!r}>"


class TeamAlias(Base, TimestampMixin):
    """Historical names a team has played under, so a rename doesn't fragment history."""

    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("team_id", "alias_name", name="uq_team_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[str | None] = mapped_column(String(32))
    effective_to: Mapped[str | None] = mapped_column(String(32))

    team: Mapped[Team] = relationship(back_populates="aliases")
