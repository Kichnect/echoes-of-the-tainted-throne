"""
Prologue system for Echoes of the Tainted Throne.

The prologue is a linear tutorial sequence that plays before the main game.
It is skippable on subsequent playthroughs.
All content is pre-written — no AI generation except Act 4 (wolf loss scene,
which uses the standard scene stream).

Acts are loaded from data/prologue/acts.json.
Progress is tracked in champion.prologue_done (bool) and
save.story_flags['prologue_act'] (current act id, null when complete).
"""
from __future__ import annotations
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import SaveGame

_ACTS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "data", "prologue", "acts.json"
))

_ACTS_CACHE: dict | None = None


def load_prologue_acts() -> dict:
    """Load and cache prologue acts.json."""
    global _ACTS_CACHE
    if _ACTS_CACHE is None:
        with open(_ACTS_PATH, "r", encoding="utf-8") as f:
            _ACTS_CACHE = json.load(f)
    return _ACTS_CACHE


def is_prologue_done(save: "SaveGame") -> bool:
    """Return True if the champion has completed or skipped the prologue."""
    return bool(getattr(save.champion, "prologue_done", False))


def get_current_act(save: "SaveGame") -> str | None:
    """Return the current prologue act id, or None if complete."""
    flags = save.story_flags or {}
    return flags.get("prologue_act", "act_1_portal")


def advance_prologue_act(save: "SaveGame", completed_act_id: str, db) -> str | None:
    """
    Mark an act as complete and advance to the next.
    Returns the new act id, or None if prologue is now complete.
    """
    acts_data = load_prologue_acts()
    acts = acts_data.get("acts", [])
    ids = [a["id"] for a in acts]

    try:
        idx = ids.index(completed_act_id)
    except ValueError:
        return None

    if idx + 1 >= len(ids):
        # Prologue complete
        save.champion.prologue_done = True
        flags = dict(save.story_flags or {})
        flags["prologue_act"] = None
        flags["prologue_complete"] = True
        save.story_flags = flags
        # Apply full rest from the final act
        save.champion.current_hp = save.champion.max_hp
        db.flush()
        return None
    else:
        next_act_id = ids[idx + 1]
        flags = dict(save.story_flags or {})
        flags["prologue_act"] = next_act_id
        save.story_flags = flags
        db.flush()
        return next_act_id


def skip_prologue(save: "SaveGame", db) -> None:
    """Skip the prologue. Applies skip state and advances to day 3."""
    acts_data = load_prologue_acts()
    save.champion.prologue_done = True
    flags = dict(save.story_flags or {})
    flags["prologue_act"] = None
    flags["prologue_complete"] = True
    flags["prologue_skipped"] = True
    save.story_flags = flags

    # Advance to day 3
    save.world.in_game_day = acts_data.get("skip_start_day", 3)

    # Apply companion starting conditions for post-prologue
    for comp in save.companions:
        comp.is_present = True

    db.flush()


def get_act_text(act: dict, background: str) -> str:
    """Extract the text for an act, applying background variant if present."""
    if "variants" in act:
        return act["variants"].get(background, act["variants"].get("warrior", ""))
    return act.get("text", "")
