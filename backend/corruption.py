"""
Corruption engine for Echoes of the Tainted Throne.

Handles:
- Corruption score management (0–100)
- PONR (Point of No Return) gate locking
- Stage detection and transitions
- Height offset calculation
- Stage transition events
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Champion

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Corruption % at which each PONR locks in — changes below this threshold
# become permanent even if corruption is later reduced.
PONR_GATES: dict[int, float] = {
    1: 20.0,   # Eyes, scent, fox ears/tail — lock in
    2: 45.0,   # Fur coverage, frame shift — lock in
    3: 65.0,   # Kobold-vulpine skeletal restructuring, size reduction — lock in
    4: 85.0,   # Full draconic descent begins — irreversible
}

# Corruption % range for each transformation stage
STAGE_THRESHOLDS: dict[int, tuple[float, float]] = {
    0: (0.0,  20.0),   # Human
    1: (20.0, 45.0),   # Vulpine-Touched
    2: (45.0, 65.0),   # Full Vulpine
    3: (65.0, 85.0),   # Kobold-Vulpine Hybrid
    4: (85.0, 100.0),  # Draconic Final Form
}

# Height lost (inches, negative) at the midpoint of each stage transition
# Stage 0 → 1: -1 to -2 inches  (average -1.5)
# Stage 1 → 2: -3 to -4 inches cumulative (average -3.5, delta -2.0)
# Stage 2 → 3: -8 to -14 inches cumulative (average -11, delta -7.5)
# Stage 3 → 4: 3.5–4 ft final height — handled by setting absolute offset
STAGE_HEIGHT_DELTAS: dict[int, float] = {
    1: -1.5,   # delta when entering Stage 1
    2: -2.0,   # additional delta when entering Stage 2
    3: -7.5,   # additional delta when entering Stage 3
    4: 0.0,    # Stage 4 uses STAGE_4_CUMULATIVE_HEIGHT_LOSS instead
}

# By Stage 4, the Champion has lost roughly 16–18 inches from baseline
STAGE_4_CUMULATIVE_HEIGHT_LOSS: float = -17.0


# ---------------------------------------------------------------------------
# Data result type
# ---------------------------------------------------------------------------

@dataclass
class CorruptionResult:
    old_corruption: float
    new_corruption: float
    old_stage: int
    new_stage: int
    stage_changed: bool
    ponr_gates_triggered: list[int]  # gate numbers newly locked this update
    corruption_delta: float


# ---------------------------------------------------------------------------
# Helper: background stat bonus
# ---------------------------------------------------------------------------

def _reapply_background_bonus(champion):
    """Re-add background stat bonus after stage-driven stat reset."""
    bg = getattr(champion, 'background', 'warrior') or 'warrior'
    bonuses = {'warrior': ('force', 2), 'scholar': ('presence', 2), 'scout': ('grace', 2)}
    if bg in bonuses:
        stat, val = bonuses[bg]
        current = getattr(champion, stat, 10)
        setattr(champion, stat, current + val)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def get_stage_for_corruption(corruption: float) -> int:
    """Return the transformation stage for a given corruption value."""
    for stage, (low, high) in STAGE_THRESHOLDS.items():
        if low <= corruption < high:
            return stage
    # Exactly 100% → Stage 4
    return 4


def apply_corruption(
    champion: Champion,
    delta: float,
    source: str = "unknown",
) -> CorruptionResult:
    """
    Apply a corruption delta to the champion, enforce PONR locks, update stage.

    PONR logic:
    - Once corruption passes a gate threshold, that gate locks.
    - Locked gates mean the physical changes for that stage are permanent
      even if corruption drops below the threshold.
    - The *stage displayed* is max(current_stage_from_corruption, highest_locked_stage).

    Returns a CorruptionResult describing what changed.
    """
    old_corruption = champion.corruption
    old_stage = champion.stage

    # Clamp delta application
    new_corruption = max(0.0, min(100.0, old_corruption + delta))

    # Check PONR gates — lock any newly passed thresholds
    ponr_triggered: list[int] = []

    if not champion.ponr_1_locked and new_corruption >= PONR_GATES[1]:
        champion.ponr_1_locked = True
        ponr_triggered.append(1)

    if not champion.ponr_2_locked and new_corruption >= PONR_GATES[2]:
        champion.ponr_2_locked = True
        ponr_triggered.append(2)

    if not champion.ponr_3_locked and new_corruption >= PONR_GATES[3]:
        champion.ponr_3_locked = True
        ponr_triggered.append(3)

    if not champion.ponr_4_locked and new_corruption >= PONR_GATES[4]:
        champion.ponr_4_locked = True
        ponr_triggered.append(4)

    champion.corruption = new_corruption

    # Determine effective stage: corruption may drop, but locked PONR gates
    # ensure physical changes don't reverse.
    new_stage = _effective_stage(champion)
    champion.stage = new_stage

    # Apply height offset for new stages entered
    if new_stage > old_stage:
        _apply_height_delta(champion, old_stage, new_stage)

    # Sync character sheet when stage changes
    if new_stage != old_stage:
        try:
            from character_sheet_sync import update_character_sheet
            update_character_sheet(champion, new_stage)
        except Exception:
            pass  # non-fatal — sheet may not exist for older saves

        try:
            from leveling import apply_stage_stat_deltas
            # Re-apply base stats for new stage, then re-add background bonuses
            apply_stage_stat_deltas(champion, new_stage)
            # Background bonuses: warrior +2 force, scholar +2 presence, scout +2 grace
            _reapply_background_bonus(champion)
        except Exception:
            pass  # non-fatal

    return CorruptionResult(
        old_corruption=old_corruption,
        new_corruption=new_corruption,
        old_stage=old_stage,
        new_stage=new_stage,
        stage_changed=new_stage != old_stage,
        ponr_gates_triggered=ponr_triggered,
        corruption_delta=delta,
    )


def _effective_stage(champion: Champion) -> int:
    """
    Effective stage is the maximum of:
    - Stage derived from current corruption value
    - Highest PONR-locked stage

    This ensures physical changes don't reverse when corruption drops.
    """
    corruption_stage = get_stage_for_corruption(champion.corruption)

    locked_stage = 0
    if champion.ponr_1_locked:
        locked_stage = max(locked_stage, 1)
    if champion.ponr_2_locked:
        locked_stage = max(locked_stage, 2)
    if champion.ponr_3_locked:
        locked_stage = max(locked_stage, 3)
    if champion.ponr_4_locked:
        locked_stage = max(locked_stage, 4)

    return max(corruption_stage, locked_stage)


def _apply_height_delta(champion: Champion, old_stage: int, new_stage: int) -> None:
    """Apply cumulative height loss for newly entered stages."""
    if new_stage == 4 and old_stage < 4:
        # Stage 4 sets the absolute cumulative loss
        champion.height_offset_in = STAGE_4_CUMULATIVE_HEIGHT_LOSS
    else:
        for stage in range(old_stage + 1, new_stage + 1):
            champion.height_offset_in += STAGE_HEIGHT_DELTAS.get(stage, 0.0)


# ---------------------------------------------------------------------------
# Corruption gain modifiers
# ---------------------------------------------------------------------------

def modified_corruption_gain(champion: Champion, base_delta: float) -> float:
    """
    Apply active status modifiers to an incoming corruption gain.
    Losses (negative delta) are not amplified.
    """
    if base_delta <= 0:
        return base_delta

    # Apply sin modifier
    try:
        from sin_system import get_corruption_modifier
        sin_mod = get_corruption_modifier(champion)
        base_delta = base_delta * (1.0 + sin_mod)
    except Exception:
        pass

    multiplier = 1.0

    # Corruption Marked status: +10% gain for 3 days
    if champion.has_status("corruption_marked"):
        multiplier += 0.10

    # Tainted (in corruption zone): passive +1/hr handled elsewhere, but
    # direct gains also scale slightly
    if champion.has_status("tainted"):
        multiplier += 0.05

    return base_delta * multiplier


# ---------------------------------------------------------------------------
# Passive corruption tick (called per in-game hour)
# ---------------------------------------------------------------------------

def passive_corruption_tick(champion: Champion, hours_elapsed: float = 1.0) -> float:
    """
    Apply passive corruption from environmental sources.
    Returns the corruption delta applied.
    """
    delta = 0.0

    if champion.has_status("tainted"):
        delta += 1.0 * hours_elapsed  # Corruption zones: +1/hr

    if delta != 0.0:
        apply_corruption(champion, delta, source="passive_tick")

    return delta


# ---------------------------------------------------------------------------
# Convenience: stage info for AI context
# ---------------------------------------------------------------------------

STAGE_NAMES: dict[int, str] = {
    0: "Human",
    1: "Vulpine-Touched",
    2: "Full Vulpine",
    3: "Kobold-Vulpine Hybrid",
    4: "Draconic Final Form",
}

STAGE_BRIEF: dict[int, str] = {
    0: "No visible changes. Internal shifts only.",
    1: "Fox ears, full tail, amber eyes, fur patches — clearly changed.",
    2: "Significant fur coverage, softened frame, feminization apparent.",
    3: "Noticeably small, scales emerging, hybrid kobold-vulpine features — striking.",
    4: "Full draconic form — feminine, hypersensitive, 3.5–4 ft at shoulder.",
}
