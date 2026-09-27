"""Automatic synchronization report — MASTER BUILD PROMPT section 63.

Renders a `FullSyncReport` into the exact template the spec asks for.
Every value is read off the report object — nothing here is a hard-coded
example number, and a competition with nothing to say for a given line
(no provider errors, nothing requiring review) just shows zero rather than
inventing content to fill the line.
"""
from __future__ import annotations

from app.services.sync_orchestrator import FullSyncReport


def render_sync_report(report: FullSyncReport) -> str:
    lines: list[str] = []
    d = report.discovery

    lines.append("FOOTBALL DATA SYNCHRONIZATION")
    lines.append(f"Competitions discovered: {d.competitions_discovered if d else 0}")
    lines.append(f"New competitions: {len(d.new_competitions) if d else 0}")
    lines.append(f"Updated competitions: {len(d.updated_competitions) if d else 0}")
    lines.append(f"New seasons: {len(d.new_seasons) if d else 0}")
    lines.append(f"Updated seasons: {len(d.updated_seasons) if d else 0}")
    lines.append("")
    lines.append(f"New teams: {report.new_teams}")
    lines.append(f"Updated teams: {report.updated_teams}")
    lines.append("")
    lines.append(f"New fixtures: {report.new_fixtures}")
    lines.append(f"Updated fixtures: {report.updated_fixtures}")
    lines.append(f"New results: {report.new_results}")
    lines.append("")
    lines.append("Data-quality summary:")
    if report.data_quality_summary:
        for key, status in report.data_quality_summary.items():
            lines.append(f"  {key}: {status}")
    else:
        lines.append("  (none)")
    lines.append(f"Models activated: {len(report.models_activated)}")
    for name in report.models_activated:
        lines.append(f"  - {name}")
    lines.append(f"Models disabled: {len(report.models_disabled)}")
    for name in report.models_disabled:
        lines.append(f"  - {name}")
    lines.append(f"Models requiring review: {len(report.models_requiring_review)}")
    for name in report.models_requiring_review:
        lines.append(f"  - {name}")
    lines.append(f"Champion/challenger decisions: {len(report.champion_challenger_decisions)}")
    for name in report.champion_challenger_decisions:
        lines.append(f"  - {name}")
    lines.append("")
    lines.append(f"Provider errors: {len(report.provider_errors)}")
    for e in report.provider_errors:
        lines.append(f"  - {e}")
    lines.append(f"Validation errors: {len(report.validation_errors)}")
    for e in report.validation_errors:
        lines.append(f"  - {e}")
    lines.append("")
    lines.append(f"System status: {report.system_status}")

    return "\n".join(lines)
