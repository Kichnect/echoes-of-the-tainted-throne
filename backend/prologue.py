"""
Prologue system for Echoes of the Tainted Throne.

The prologue is a linear tutorial sequence that plays before the main game.
It is skippable on subsequent playthroughs.
All content is pre-written — no AI generation except Act 4 (wolf loss scene,
which uses the standard scene stream).

Acts are loaded from data/prologue/acts.json.
Progress is tracked in champion.prologue_done (bool) and
save.story_flags['prologue_act'] (current act id, null when complete).

Act day/time transitions:
  act_1_portal          → Day 1, morning
  act_2_explore         → Day 1, morning
  act_3_imp             → Day 1, midday
  act_4_wolf            → Day 1, afternoon
  act_5_reunion         → Day 1, dusk
  act_6_waystation_night→ Day 1 → Day 2 (rest, day+1)
  act_7_lone_wolf       → Day 2, morning
  act_8_day3_threshold  → Day 2 → Day 3 (day+1), midday
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

# Map time-of-day strings to WorldState enum-compatible values
# These match the TimeOfDay enum values used in db/models.py
_TIME_MAP: dict[str, str] = {
    "morning":   "morning",
    "midday":    "midday",
    "afternoon": "afternoon",
    "dusk":      "dusk",
    "night":     "night",
    "dawn":      "dawn",
}


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


def _apply_act_world_state(save: "SaveGame", act: dict) -> None:
    """
    Apply the day and time-of-day from an act definition to the world state.
    Acts that are 'rest' types advance the day by 1 (handled by caller).
    """
    day = act.get("day")
    time_str = act.get("time_of_day")

    if day is not None:
        save.world.in_game_day = day

    if time_str:
        mapped = _TIME_MAP.get(time_str, time_str)
        try:
            # Try to set via enum if WorldState.time_of_day is an enum column
            from db.models import TimeOfDay as _TOD
            save.world.time_of_day = _TOD(mapped)
        except Exception:
            save.world.time_of_day = mapped


def advance_prologue_act(save: "SaveGame", completed_act_id: str, db) -> str | None:
    """
    Mark an act as complete and advance to the next.
    Applies day/time state for the next act.
    Returns the new act id, or None if prologue is now complete.
    """
    acts_data = load_prologue_acts()
    acts = acts_data.get("acts", [])
    ids = [a["id"] for a in acts]

    try:
        idx = ids.index(completed_act_id)
    except ValueError:
        return None

    # Apply mechanical effects of the completed act
    completed_act = acts[idx]
    mechanical = completed_act.get("mechanical", {})
    if mechanical.get("rest_full"):
        save.champion.current_hp = save.champion.max_hp

    # Apply corruption gain for tutorial combat losses (tracked by frontend,
    # but also applied here for act_4_wolf and act_7_lone_wolf loss)
    # Corruption gain on combat acts is handled separately via /api/combat/resolve.

    if idx + 1 >= len(acts):
        # Prologue complete
        save.champion.prologue_done = True
        flags = dict(save.story_flags or {})
        flags["prologue_act"] = None
        flags["prologue_complete"] = True
        save.story_flags = flags

        # Set final world state: Day 3, midday (tutorial_complete is Day 3)
        completed_act_type = completed_act.get("type", "")
        if completed_act_type == "tutorial_complete":
            save.world.in_game_day = 3
            try:
                from db.models import TimeOfDay as _TOD
                save.world.time_of_day = _TOD("midday")
            except Exception:
                save.world.time_of_day = "midday"

        db.flush()
        return None
    else:
        next_act_id = ids[idx + 1]
        next_act = acts[idx + 1]
        flags = dict(save.story_flags or {})
        flags["prologue_act"] = next_act_id
        save.story_flags = flags

        # Apply the world state for the incoming act
        _apply_act_world_state(save, next_act)

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

    # Advance to day 3, midday
    save.world.in_game_day = acts_data.get("skip_start_day", 3)
    try:
        from db.models import TimeOfDay as _TOD
        save.world.time_of_day = _TOD("midday")
    except Exception:
        save.world.time_of_day = "midday"

    # Apply companion starting conditions for post-prologue
    for comp in save.companions:
        comp.is_present = True

    db.flush()


def get_act_text(act: dict, background: str) -> str:
    """Extract the text for an act, applying background variant if present."""
    if "variants" in act:
        return act["variants"].get(background, act["variants"].get("warrior", ""))
    return act.get("text", act.get("setup_text", ""))
