"""
Submission score engine for Echoes of the Tainted Throne.

Submission score (0–100) drives:
- Rose color path accumulation
- Certain transformation flavor
- Scene variation in AI-generated prose
- High-arousal / desperate-arousal state thresholds

The score is NOT shown to the player as a number.
They observe its effects through scene writing, NPC reactions, and status effects.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Champion

# ---------------------------------------------------------------------------
# Event table
# ---------------------------------------------------------------------------

# Each event ID maps to a base submission delta.
# Positive = increases submission (toward Rose path, arousal compounding)
# Negative = decreases submission (resistance, dominant behavior)

SUBMISSION_EVENTS: dict[str, float] = {
    # --- Submission-increasing events ---
    "combat_loss_penetrated":           +8.0,
    "combat_loss_oral_forced":          +5.0,
    "chastity_device_applied":          +3.0,   # per day locked (caller passes days)
    "cursed_clothing_worn":             +2.0,   # per encounter
    "plug_active":                      +4.0,   # per encounter
    "npc_dominant_submission":          +10.0,
    "orgasm_anal_only":                 +6.0,
    "orgasm_oral_only":                 +4.0,
    "dirty_talk_accepted":              +3.0,
    "referred_to_as_good_girl":         +4.0,
    "temporary_sex_slave_event":        +15.0,  # full event completion
    "companion_carries_champion":       +1.0,   # per occurrence (late-stage)
    "kasyrra_encounter_submissive":     +12.0,

    # --- Submission-decreasing events (resistance/dominance) ---
    "orgasm_penile_stimulation":        -8.0,
    "penetrated_as_dominant":           -10.0,
    "resisted_submission_check":        -5.0,
    "escaped_submission_situation":     -7.0,
    "broke_curse_item":                 -6.0,
    "companion_assisted_escape":        -3.0,
}

# ---------------------------------------------------------------------------
# Submission thresholds for color path contribution
# ---------------------------------------------------------------------------

# These are checked during color path calculation, not enforced here.
SUBMISSION_PATH_THRESHOLDS = {
    "rose_likely":    60.0,
    "rose_dominant":  80.0,
}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SubmissionResult:
    event_id: str
    base_delta: float
    applied_delta: float         # after multipliers
    old_score: float
    new_score: float
    multipliers_applied: list[str]


# ---------------------------------------------------------------------------
# Core update function
# ---------------------------------------------------------------------------

def update_submission(
    champion: Champion,
    event_id: str,
    multiplier_override: float | None = None,
) -> SubmissionResult:
    """
    Apply a submission event to the champion.

    Multipliers stack:
    - Chastity device (locked): ×1.3 on positive deltas
    - High arousal status: ×1.2 on positive deltas
    - Desperate arousal: ×1.5 on positive deltas

    After update, also update color path accumulator for Rose path.
    Returns a SubmissionResult with full breakdown.
    """
    base_delta = SUBMISSION_EVENTS.get(event_id, 0.0)
    multipliers: list[str] = []

    if multiplier_override is not None:
        applied_delta = base_delta * multiplier_override
        multipliers.append(f"override×{multiplier_override:.2f}")
    else:
        applied_delta = base_delta

        if applied_delta > 0:
            if champion.has_status("chastity_flat"):
                applied_delta *= 1.3
                multipliers.append("chastity×1.3")

            if champion.has_status("high_arousal"):
                applied_delta *= 1.2
                multipliers.append("high_arousal×1.2")

            if champion.has_status("desperate_arousal"):
                applied_delta *= 1.5
                multipliers.append("desperate_arousal×1.5")

    old_score = champion.submission_score
    new_score = max(0.0, min(100.0, old_score + applied_delta))
    champion.submission_score = new_score

    # Accumulate into the Rose color path tracker
    if applied_delta > 0:
        champion.cp_submission_events += applied_delta

    # Specific events also feed other color path accumulators
    _update_color_path_accumulators(champion, event_id)

    result = SubmissionResult(
        event_id=event_id,
        base_delta=base_delta,
        applied_delta=applied_delta,
        old_score=old_score,
        new_score=new_score,
        multipliers_applied=multipliers,
    )

    # Attraction arc update
    _MALE_PLEASURE_EVENTS = {
        "combat_loss_penetrated", "orgasm_anal_only", "orgasm_oral_only",
        "orgasm_multiple", "used_as_toy", "temporary_enslavement",
        "combat_loss_oral_forced",
    }
    sheet = None
    try:
        sheet = champion.save.character_sheet
    except Exception:
        pass

    if sheet is not None:
        arc_delta = 0
        if event_id in _MALE_PLEASURE_EVENTS:
            arc_delta += 8
        # Check submission score crossing 50
        if result.old_score < 50.0 <= result.new_score:
            arc_delta += 10
        if arc_delta > 0:
            old_arc_label = sheet.attraction_current
            sheet.attraction_arc_score = min(100, sheet.attraction_arc_score + arc_delta)
            # Update attraction_current based on score thresholds:
            # 0-29: female-leaning, 30-49: uncertain, 50-69: male-drawn,
            # 70-84: seeking dominance, 85-100: devoted to manhood
            score = sheet.attraction_arc_score
            if score >= 85:
                new_label = "devoted to manhood"
            elif score >= 70:
                new_label = "seeking dominance"
            elif score >= 50:
                new_label = "male-drawn"
            elif score >= 30:
                new_label = "uncertain"
            else:
                new_label = "female-leaning"
            if new_label != old_arc_label:
                sheet.attraction_current = new_label
                # Flag the threshold crossing for companion reaction
                flags = champion.save.story_flags or {}
                flags[f"attraction_crossed_{new_label.replace(' ', '_')}"] = True
                champion.save.story_flags = flags

    return result


def update_submission_raw(champion: Champion, delta: float) -> float:
    """Apply a raw submission delta (not from event table). Returns new score."""
    champion.submission_score = max(0.0, min(100.0, champion.submission_score + delta))
    if delta > 0:
        champion.cp_submission_events += delta
    return champion.submission_score


# ---------------------------------------------------------------------------
# Passive submission tick (per in-game hour)
# ---------------------------------------------------------------------------

def passive_submission_tick(champion: Champion, hours_elapsed: float = 1.0) -> float:
    """
    Apply passive submission gain from persistent status effects.
    Called by the time-advancement loop.
    Returns total delta applied.
    """
    delta = 0.0

    if champion.has_status("chastity_flat"):
        delta += 0.8 * hours_elapsed

    if champion.has_status("cursed_harem_clothes"):
        delta += 0.5 * hours_elapsed

    if champion.has_status("cursed_plug"):
        delta += 1.0 * hours_elapsed

    if champion.has_status("kasyrra_marked"):
        delta += 0.2 * hours_elapsed

    if champion.has_status("high_arousal"):
        delta += 1.5 * hours_elapsed

    if delta > 0:
        update_submission_raw(champion, delta)

    return delta


# ---------------------------------------------------------------------------
# Arousal passive tick (per in-game hour)
# ---------------------------------------------------------------------------

def passive_arousal_tick(champion: Champion, hours_elapsed: float = 1.0) -> int:
    """
    Apply passive arousal gain from persistent status effects.
    Arousal is an int 0–100.
    Returns new arousal value.
    """
    gain = 0.0

    if champion.has_status("chastity_flat"):
        gain += 1.2 * hours_elapsed

    if champion.has_status("cursed_plug"):
        gain += 2.0 * hours_elapsed

    if champion.has_status("cursed_harem_clothes"):
        gain += 0.8 * hours_elapsed

    if champion.has_status("kasyrra_marked"):
        gain += 0.3 * hours_elapsed

    if gain > 0:
        champion.arousal = max(0, min(100, champion.arousal + int(gain)))

    # Apply arousal threshold status effects
    _check_arousal_thresholds(champion)

    return champion.arousal


def _check_arousal_thresholds(champion: Champion) -> None:
    """Automatically apply/remove High Arousal and Desperate Arousal statuses."""
    from db.models import ActiveStatus

    if champion.arousal >= 70 and not champion.has_status("high_arousal"):
        status = ActiveStatus(
            champion_id=champion.id,
            effect_id="high_arousal",
            display_name="High Arousal",
            is_active=True,
            duration_remaining=None,
        )
        champion.statuses.append(status)

    if champion.arousal < 70:
        for s in champion.statuses:
            if s.effect_id == "high_arousal":
                s.is_active = False

    if champion.arousal >= 90 and not champion.has_status("desperate_arousal"):
        status = ActiveStatus(
            champion_id=champion.id,
            effect_id="desperate_arousal",
            display_name="Desperate Arousal",
            is_active=True,
            duration_remaining=None,
        )
        champion.statuses.append(status)

    if champion.arousal < 90:
        for s in champion.statuses:
            if s.effect_id == "desperate_arousal":
                s.is_active = False


# ---------------------------------------------------------------------------
# Color path accumulator side-effects
# ---------------------------------------------------------------------------

def _update_color_path_accumulators(champion: Champion, event_id: str) -> None:
    """Update color path tracking fields based on the event that fired."""
    # Rose — feminization events
    if event_id in {
        "referred_to_as_good_girl",
        "dirty_talk_accepted",
        "cursed_clothing_worn",
        "temporary_sex_slave_event",
        "combat_loss_penetrated",
    }:
        champion.cp_feminization_events += 1

    # Resistance actions (Crimson / Teal / Ivory)
    if event_id in {
        "resisted_submission_check",
        "escaped_submission_situation",
        "broke_curse_item",
        "orgasm_penile_stimulation",
        "penetrated_as_dominant",
    }:
        champion.cp_resistance_actions += 1

    # Kasyrra alignment (Violet / Amber)
    if event_id == "kasyrra_encounter_submissive":
        champion.cp_kasyrra_submission += abs(SUBMISSION_EVENTS[event_id])
