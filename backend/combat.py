"""
Combat resolution engine for Echoes of the Tainted Throne.

Combat is not simulated blow-by-blow — a single resolve_combat() call
determines the outcome of the whole fight based on Champion stats, active
status effects, transformation stage, and a weighted random element.

The result carries everything the calling route needs to:
  1. Fire corruption and submission events
  2. Build the encounter_data dict for scene generation
  3. Return updated game state to the frontend

Encounter definitions live in data/encounters/<id>.json.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Champion

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ENCOUNTERS_DIR = Path(__file__).parent.parent / "data" / "encounters"


# ---------------------------------------------------------------------------
# Stage combat penalties
# Higher stage = physically disadvantaged in standard combat
# ---------------------------------------------------------------------------

STAGE_COMBAT_PENALTIES: dict[int, int] = {
    0: 0,    # Full human capability
    1: -1,   # Fox ears / tail are distracting but not impairing
    2: -2,   # Softer frame, reduced physical threat
    3: -4,   # Significantly smaller, fragile-looking; fragility is real
    4: -6,   # Tiny draconic form — relies on companions or avoidance
}

# ---------------------------------------------------------------------------
# Status effects that modify combat rolls (effect_id → stat, modifier)
# ---------------------------------------------------------------------------

COMBAT_STATUS_MODIFIERS: dict[str, dict[str, int]] = {
    "pinned":            {"grace": -5, "force": -3},
    "high_arousal":      {"resolve": -2, "grace": -1},
    "desperate_arousal": {"resolve": -4, "grace": -2, "force": -1},
    "chastity_flat":     {"force": -1},
    "cursed_plug":       {"grace": -2},
    "essence_drained":   {"force": -3, "resolve": -2},
    "pheromone_drunk":   {"resolve": -3},
}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CombatResult:
    outcome: str               # "win" | "loss" | "flee"
    outcome_tier: str          # "decisive_win" | "narrow_win" | "narrow_loss" | "decisive_loss"
    encounter_id: str
    enemy_display_name: str
    champion_roll: int         # d20 result
    effective_score: int       # roll + stat modifiers
    enemy_difficulty: int
    margin: int                # positive = won by this, negative = lost by this
    corruption_gained: float
    submission_events: list[str]
    stage_at_combat: int
    scene_type: str
    scene_notes: str
    kasyrra_mark_hesitation: bool  # whether the Mark slowed the enemy
    hp_lost: int = 0           # HP damage taken this combat
    carried_to_safety: bool = False  # True if HP hit 0 and companions intervened
    encounter_choices: list = field(default_factory=list)  # choices available for this outcome

    def as_encounter_data(self) -> dict:
        """Build the encounter_data dict expected by prompt_builder."""
        return {
            "scene_type":          self.scene_type,
            "enemy":               self.enemy_display_name,
            "combat_result":       self.outcome,
            "outcome_tier":        self.outcome_tier,
            "corruption_gained":   self.corruption_gained,
            "submission_events":   self.submission_events,
            "notes":               self.scene_notes,
            "hp_lost":             self.hp_lost,
            "carried_to_safety":   self.carried_to_safety,
            "choices":             self.encounter_choices,
        }


# ---------------------------------------------------------------------------
# Encounter loader
# ---------------------------------------------------------------------------

def load_encounter(encounter_id: str) -> dict:
    """
    Load an encounter definition from data/encounters/<encounter_id>.json.
    Raises FileNotFoundError with a helpful message if missing.
    """
    path = _ENCOUNTERS_DIR / f"{encounter_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Encounter '{encounter_id}' not found at {path}. "
            f"Available: {[p.stem for p in _ENCOUNTERS_DIR.glob('*.json')]}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Core resolution
# ---------------------------------------------------------------------------

def resolve_combat(
    champion: Champion,
    encounter: dict,
    rng: random.Random | None = None,
) -> CombatResult:
    """
    Resolve a combat encounter and return a full CombatResult.

    Steps:
      1. Calculate champion's effective score for the encounter's combat_stat
      2. Roll d20 and add effective score
      3. Compare against encounter difficulty
      4. Select outcome branch (win / loss) and apply consequences
      5. Return result — does NOT commit; caller must db.commit()
    """
    from corruption import apply_corruption
    from submission import update_submission

    rng = rng or random.Random()

    encounter_id   = encounter.get("id", "unknown")
    display_name   = encounter.get("display_name", "Unknown Enemy")
    difficulty     = int(encounter.get("difficulty", 12))
    combat_stat    = encounter.get("combat_stat", "force")
    stage          = champion.stage
    respects_mark  = encounter.get("respects_kasyrra_mark", False)

    # -----------------------------------------------------------------------
    # 1. Effective score
    # -----------------------------------------------------------------------
    base_stat = getattr(champion, combat_stat, 10)
    stage_penalty = STAGE_COMBAT_PENALTIES.get(stage, 0)

    status_penalty = 0
    for effect_id, stat_mods in COMBAT_STATUS_MODIFIERS.items():
        if champion.has_status(effect_id):
            status_penalty += stat_mods.get(combat_stat, 0)

    effective_score = base_stat + stage_penalty + status_penalty

    # -----------------------------------------------------------------------
    # 2. Roll
    # -----------------------------------------------------------------------
    roll = rng.randint(1, 20)
    total = roll + effective_score

    # -----------------------------------------------------------------------
    # 3. Kasyrra Mark hesitation — reduces difficulty if enemy is corruptible
    # -----------------------------------------------------------------------
    mark_hesitation = False
    if champion.kasyrra_mark_applied and respects_mark:
        difficulty = max(1, difficulty - 2)
        mark_hesitation = True

    margin = total - difficulty

    # -----------------------------------------------------------------------
    # 4. Outcome branch — four tiers for deterministic outcomes
    #    decisive_win (margin >= 5), narrow_win (0-4),
    #    narrow_loss (-1 to -4), decisive_loss (<= -5)
    # -----------------------------------------------------------------------
    if margin >= 5:
        outcome = "win"
        outcome_tier = "decisive_win"
    elif margin >= 0:
        outcome = "win"
        outcome_tier = "narrow_win"
    elif margin >= -4:
        outcome = "loss"
        outcome_tier = "narrow_loss"
    else:
        outcome = "loss"
        outcome_tier = "decisive_loss"

    # Try tier-specific branch first, fall back to win/loss generic branch
    branch = encounter.get(outcome_tier, encounter.get(f"on_{outcome}", {}))

    # Stage variant override (e.g. stage 3 gets different notes)
    stage_variants = encounter.get("stage_variants", {})
    stage_key = str(stage)
    if stage_key in stage_variants:
        variant = stage_variants[stage_key].get(outcome_tier) or \
                  stage_variants[stage_key].get(f"on_{outcome}", {})
        branch = {**branch, **variant}   # variant overrides base, non-destructively

    corruption_gained = float(branch.get("corruption_gain", 0.0))
    submission_events: list[str] = list(branch.get("submission_events", []))
    scene_type        = branch.get("scene_type", f"encounter_{outcome_tier}")
    scene_notes       = branch.get("notes", "")

    # Extract player choices available for this outcome tier or generic outcome
    choices_all = encounter.get("choices", {})
    encounter_choices = choices_all.get(outcome_tier) or choices_all.get(outcome, [])

    # Append cursed-item bonus events if active
    bonus_events = _cursed_item_encounter_events(champion)
    submission_events = submission_events + bonus_events

    # -----------------------------------------------------------------------
    # 5. Apply consequences
    # -----------------------------------------------------------------------
    if corruption_gained > 0:
        apply_corruption(champion, corruption_gained, source=f"encounter:{encounter_id}")

    for event_id in submission_events:
        update_submission(champion, event_id)

    # -----------------------------------------------------------------------
    # 6. HP loss on combat loss
    #    Damage = 5 + |margin|, capped [5, 15].
    #    Narrow loss (margin -1) → 6 HP.  Decisive loss (margin -10) → 15 HP.
    # -----------------------------------------------------------------------
    hp_lost        = 0
    carried_to_safety = False

    if outcome == "loss":
        hp_lost = max(5, min(15, 5 + abs(margin)))
        champion.current_hp = max(0, champion.current_hp - hp_lost)

        # If HP hits zero: companions carry champion to safety
        # — add corruption penalty and set HP to 25% max
        if champion.current_hp <= 0:
            carried_to_safety = True
            apply_corruption(champion, 3.0, source="hp_zero_collapse")
            champion.current_hp = max(1, champion.max_hp // 4)

    return CombatResult(
        outcome=outcome,
        outcome_tier=outcome_tier,
        encounter_id=encounter_id,
        enemy_display_name=display_name,
        champion_roll=roll,
        effective_score=total,
        enemy_difficulty=difficulty,
        margin=margin,
        corruption_gained=corruption_gained,
        submission_events=submission_events,
        stage_at_combat=stage,
        scene_type=scene_type,
        scene_notes=scene_notes,
        kasyrra_mark_hesitation=mark_hesitation,
        hp_lost=hp_lost,
        carried_to_safety=carried_to_safety,
        encounter_choices=encounter_choices,
    )


# ---------------------------------------------------------------------------
# Cursed item bonus events (applied on top of encounter outcome)
# ---------------------------------------------------------------------------

def _cursed_item_encounter_events(champion: Champion) -> list[str]:
    """
    Certain cursed items add submission events to any encounter loss.
    These represent the additional vulnerability and humiliation of being
    in that state during combat.
    """
    extras: list[str] = []
    if champion.has_status("cursed_plug"):
        extras.append("plug_active")
    if champion.has_status("cursed_harem_clothes"):
        extras.append("cursed_clothing_worn")
    return extras


# ---------------------------------------------------------------------------
# Flee resolution (called when player chooses to flee)
# ---------------------------------------------------------------------------

def resolve_flee(
    champion: Champion,
    encounter: dict,
    rng: random.Random | None = None,
) -> CombatResult:
    """
    Attempt to flee. Uses grace stat vs a reduced difficulty.
    Fleeing always costs some corruption and a resistance submission event.
    """
    from corruption import apply_corruption
    from submission import update_submission

    rng = rng or random.Random()

    encounter_id = encounter.get("id", "unknown")
    display_name = encounter.get("display_name", "Unknown Enemy")
    flee_dc      = max(6, int(encounter.get("difficulty", 12)) - 4)

    roll    = rng.randint(1, 20)
    grace   = champion.grace + STAGE_COMBAT_PENALTIES.get(champion.stage, 0)
    total   = roll + grace
    margin  = total - flee_dc

    flee_branch = encounter.get("on_flee", {})
    corruption_gained = float(flee_branch.get("corruption_gain", 2.0))
    submission_events = list(flee_branch.get("submission_events", ["resisted_submission_check"]))

    if margin < 0:
        # Failed to flee — treated as a partial loss
        submission_events = ["combat_loss_oral_forced"]
        corruption_gained += 2.0

    apply_corruption(champion, corruption_gained, source=f"flee:{encounter_id}")
    for event_id in submission_events:
        update_submission(champion, event_id)

    return CombatResult(
        outcome="flee",
        outcome_tier="flee",
        encounter_id=encounter_id,
        enemy_display_name=display_name,
        champion_roll=roll,
        effective_score=total,
        enemy_difficulty=flee_dc,
        margin=margin,
        corruption_gained=corruption_gained,
        submission_events=submission_events,
        stage_at_combat=champion.stage,
        scene_type=flee_branch.get("scene_type", "encounter_win"),
        scene_notes=flee_branch.get("notes", ""),
        kasyrra_mark_hesitation=False,
    )
