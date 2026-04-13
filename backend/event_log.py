"""
Event logging helper for Echoes of the Tainted Throne.

Writes structured EventLogEntry records for significant game events.
These feed into the RECENT HISTORY block in the AI context.
"""

from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import SaveGame, EventLogEntry
    from sqlalchemy.orm import Session

MAX_LOG_ENTRIES = 200   # Prune to this count to prevent unbounded growth


def log_event(
    save: "SaveGame",
    event_type: str,
    data: dict,
    db: "Session",
) -> "EventLogEntry":
    """
    Create an EventLogEntry for a significant game event.
    Prunes old entries if count exceeds MAX_LOG_ENTRIES.
    Does NOT commit — caller commits.
    """
    from db.models import EventLogEntry

    champion = save.champion
    entry = EventLogEntry(
        champion_id=champion.id,
        event_id=event_type,
        event_data={
            "day":   getattr(save.world, "in_game_day", 1),
            "stage": champion.stage,
            "corruption": round(champion.corruption, 1),
            **data,
        },
        occurred_at=datetime.utcnow(),
    )
    db.add(entry)

    # Prune oldest entries if over limit
    # Count via the champion's event_log relationship length
    db.flush()  # so the new entry is counted
    all_entries = (
        db.query(EventLogEntry)
        .filter(EventLogEntry.champion_id == champion.id)
        .order_by(EventLogEntry.id.asc())
        .all()
    )
    if len(all_entries) > MAX_LOG_ENTRIES:
        excess = all_entries[: len(all_entries) - MAX_LOG_ENTRIES]
        for e in excess:
            db.delete(e)

    return entry


def format_recent_history(champion: "Champion", limit: int = 5) -> str:
    """
    Format the last N events as a structured RECENT HISTORY block for AI context.
    """
    if not champion.event_log:
        return ""

    recent = sorted(champion.event_log, key=lambda e: e.id, reverse=True)[:limit]
    recent.reverse()   # oldest first for narrative coherence

    lines = ["=== RECENT HISTORY ==="]
    for entry in recent:
        d = entry.event_data or {}
        day = d.get("day", "?")
        etype = entry.event_id.replace("_", " ")
        detail_parts = []

        if "enemy" in d:
            detail_parts.append(f"vs {d['enemy']}")
        if "outcome" in d:
            detail_parts.append(d["outcome"])
        if "corruption_gained" in d and float(d["corruption_gained"]) > 0:
            detail_parts.append(f"corruption +{d['corruption_gained']:.1f}%")
        if "choice_made" in d:
            detail_parts.append(f"chose: {d['choice_made']}")

        detail = " | ".join(detail_parts)
        suffix = f" — {detail}" if detail else ""
        lines.append(f"- Day {day} | {etype}{suffix}")

    return "\n".join(lines)
