"""
Status effect registry and management for Echoes of the Tainted Throne.

A StatusEffectDef is read-only data (the canonical definition of an effect).
apply_status / remove_status mutate the SQLAlchemy ActiveStatus records on
the Champion.

All canonical effect IDs live in this file. If an effect ID is referenced
anywhere else in the codebase (submission.py, corruption.py, AI context),
it must be defined here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Champion, ActiveStatus


# ---------------------------------------------------------------------------
# Removal difficulty enum
# ---------------------------------------------------------------------------

class RemovalDifficulty(str, enum.Enum):
    IMPOSSIBLE  = "impossible"   # Cannot be removed at all
    RITUAL      = "ritual"       # Requires Mireille's research or shrine purification
    KEY_ITEM    = "key_item"     # Requires a specific carried item (key, solvent)
    REST        = "rest"         # Removed by resting (temporary effects)
    EVENT       = "event"        # Removed when a specific game event resolves
    PLAYER      = "player"       # Champion can remove voluntarily


# ---------------------------------------------------------------------------
# StatusEffectDef
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusEffectDef:
    id: str
    display_name: str
    description: str

    # Item classification
    is_cursed_item: bool = False
    is_toy: bool = False
    is_permanent: bool = False           # Never expires; only removed by explicit action

    # Duration (None = permanent until explicit removal)
    default_duration_hours: int | None = None

    # Stat modifiers applied to champion while active.
    # Keys match Champion column names: "force", "grace", "resolve", "presence", "essence"
    stat_modifiers: dict[str, int] = field(default_factory=dict)

    # Corruption
    corruption_gain_multiplier: float = 1.0   # multiplier on all incoming gains
    passive_corruption_per_hour: float = 0.0

    # Submission / arousal
    passive_submission_per_hour: float = 0.0
    passive_arousal_per_hour: float = 0.0
    submission_gain_multiplier: float = 1.0   # multiplier on positive submission events

    # Removal
    removal_difficulty: RemovalDifficulty = RemovalDifficulty.PLAYER
    removal_condition: str = ""

    # Short note injected into the AI context block
    scene_note: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_EFFECTS: list[StatusEffectDef] = [

    # -----------------------------------------------------------------------
    # Cursed items — physically locked onto the Champion
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="chastity_flat",
        display_name="Chastity Device",
        description="An iron device, locked. Prevents penile stimulation entirely. "
                    "Arousal builds with nowhere to go.",
        is_cursed_item=True,
        stat_modifiers={"force": -2, "grace": -1},
        passive_submission_per_hour=0.8,
        passive_arousal_per_hour=1.2,
        submission_gain_multiplier=1.3,
        removal_difficulty=RemovalDifficulty.KEY_ITEM,
        removal_condition="Requires the matching key or a locksmith event.",
        scene_note="Chastity device is physically locked. Penile stimulation impossible. "
                   "Arousal accumulates without outlet.",
    ),

    StatusEffectDef(
        id="cursed_harem_clothes",
        display_name="Cursed Harem Attire",
        description="Diaphanous silk and gemstone finery stitched with corruption runes. "
                    "Resists removal and marks the wearer as available.",
        is_cursed_item=True,
        stat_modifiers={"resolve": -2, "presence": 1},
        passive_submission_per_hour=0.5,
        passive_arousal_per_hour=0.8,
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="Mireille's dispel ritual or a purification shrine.",
        scene_note="Wearing cursed harem attire. Sheer, elaborate, impossible to simply remove.",
    ),

    StatusEffectDef(
        id="cursed_plug",
        display_name="Binding Plug",
        description="An enchanted plug with a tether mechanism that locks in place. "
                    "Every movement is felt.",
        is_cursed_item=True,
        is_toy=True,
        stat_modifiers={"grace": -2},
        passive_submission_per_hour=1.0,
        passive_arousal_per_hour=2.0,
        submission_gain_multiplier=1.2,
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="Requires ritual removal or the binding key.",
        scene_note="Binding plug locked in place. Every step, every movement registers.",
    ),

    # -----------------------------------------------------------------------
    # Marks — permanent or near-permanent magical brands
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="kasyrra_marked",
        display_name="Kasyrra's Mark",
        description="A brand of draconic possession inscribed somewhere on the skin. "
                    "Corrupted creatures hesitate on her scent. Her pull is always present.",
        is_permanent=True,
        passive_submission_per_hour=0.2,
        passive_arousal_per_hour=0.3,
        passive_corruption_per_hour=0.1,
        removal_difficulty=RemovalDifficulty.IMPOSSIBLE,
        removal_condition="Cannot be removed.",
        scene_note="Kasyrra's Mark active. Corrupted creatures hesitate (briefly) before "
                   "acting against the Champion. Kasyrra's influence present at all times.",
    ),

    StatusEffectDef(
        id="broodmarked",
        display_name="Broodmark",
        description="A demon matriarch's claim-mark. Corruption seeps in passively; "
                    "her brood treats the Champion as claimed property.",
        is_permanent=False,
        default_duration_hours=168,   # 7 in-game days
        passive_corruption_per_hour=0.5,
        passive_submission_per_hour=0.5,
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="Purification shrine or Mireille's counter-ritual.",
        scene_note="Broodmarked. Demon-kin treat the Champion as claimed.",
    ),

    StatusEffectDef(
        id="corruption_marked",
        display_name="Corruption Marked",
        description="A targeting brand applied by Kasyrra or a corruption priest. "
                    "Corruption gains are amplified for several days.",
        default_duration_hours=72,    # 3 in-game days
        corruption_gain_multiplier=1.1,
        passive_corruption_per_hour=0.15,
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="Expires after 3 days or purification.",
        scene_note="Corruption Marked. All corruption gains +10%.",
    ),

    # -----------------------------------------------------------------------
    # Environmental / zone effects
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="tainted",
        display_name="Tainted (Zone)",
        description="The Champion is inside a corruption-saturated region. "
                    "Corruption accumulates passively every hour.",
        passive_corruption_per_hour=1.0,
        removal_difficulty=RemovalDifficulty.EVENT,
        removal_condition="Leave the tainted region.",
        scene_note="In a corruption zone. Passive corruption accumulates.",
    ),

    # -----------------------------------------------------------------------
    # Arousal states — auto-managed by submission engine
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="high_arousal",
        display_name="High Arousal",
        description="Arousal above 70. Focus is compromised; the body is insistent.",
        stat_modifiers={"resolve": -2, "grace": -1},
        submission_gain_multiplier=1.2,
        removal_difficulty=RemovalDifficulty.REST,
        removal_condition="Arousal drops below 70 (rest, resolution, or orgasm).",
        scene_note="High Arousal active. Champion is distracted and compromised.",
    ),

    StatusEffectDef(
        id="desperate_arousal",
        display_name="Desperate Arousal",
        description="Arousal above 90. Rational thought is genuinely difficult. "
                    "The body's demand overwhelms everything else.",
        stat_modifiers={"resolve": -4, "grace": -2, "force": -1},
        submission_gain_multiplier=1.5,
        removal_difficulty=RemovalDifficulty.REST,
        removal_condition="Arousal drops below 90.",
        scene_note="Desperate Arousal. Severe resolve and grace penalties. "
                   "Submission events gain 50% more weight.",
    ),

    # -----------------------------------------------------------------------
    # Combat / encounter states
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="pinned",
        display_name="Pinned",
        description="Physically restrained. Movement is near-impossible.",
        default_duration_hours=1,
        stat_modifiers={"grace": -5, "force": -3},
        removal_difficulty=RemovalDifficulty.EVENT,
        removal_condition="Combat ends or a companion intervenes.",
        scene_note="Pinned. Grace and Force severely reduced.",
    ),

    StatusEffectDef(
        id="essence_drained",
        display_name="Essence Drained",
        description="Magical and physical reserves depleted. "
                    "Recovery takes most of a day.",
        default_duration_hours=8,
        stat_modifiers={"force": -3, "resolve": -2},
        removal_difficulty=RemovalDifficulty.REST,
        removal_condition="Rest for 8 hours.",
        scene_note="Essence depleted. Force and Resolve reduced.",
    ),

    StatusEffectDef(
        id="pheromone_drunk",
        display_name="Pheromone Drunk",
        description="Overwhelmed by magical pheromones. Resolve is compromised; "
                    "presence paradoxically heightened.",
        default_duration_hours=6,
        stat_modifiers={"resolve": -3, "presence": 2},
        passive_submission_per_hour=1.5,
        submission_gain_multiplier=1.4,
        removal_difficulty=RemovalDifficulty.REST,
        removal_condition="Effect expires after 6 hours.",
        scene_note="Pheromone drunk. Severely impaired resolve, unusual presence.",
    ),

    # -----------------------------------------------------------------------
    # Stage-related passive effects
    # -----------------------------------------------------------------------

    StatusEffectDef(
        id="attraction_aura",
        display_name="Attraction Aura",
        description="The Champion's Stage 3+ form radiates an involuntary allure. "
                    "NPCs and creatures respond to their presence before they speak.",
        passive_arousal_per_hour=0.5,
        removal_difficulty=RemovalDifficulty.IMPOSSIBLE,
        removal_condition="Inherent to Stage 3+ form. Cannot be removed.",
        scene_note="Attraction Aura active. NPCs register the Champion's presence "
                   "differently — drawing toward them before conscious decision.",
    ),

    StatusEffectDef(
        id="temporary_enslavement",
        display_name="Temporarily Enslaved",
        description="Under another's dominion by contract, force, or ritual. "
                    "Autonomy is restricted for the duration.",
        default_duration_hours=24,
        stat_modifiers={"force": -2, "resolve": -3},
        passive_submission_per_hour=2.0,
        passive_arousal_per_hour=1.5,
        removal_difficulty=RemovalDifficulty.EVENT,
        removal_condition="Event resolution — companion rescue, contract fulfilment, "
                          "or successful escape check.",
        scene_note="Temporarily enslaved. Under another's command. "
                   "Resolve and Force reduced; submission accumulates rapidly.",
    ),
]

# Build lookup dict
STATUS_EFFECTS: dict[str, StatusEffectDef] = {e.id: e for e in _EFFECTS}


def get_effect(effect_id: str) -> StatusEffectDef | None:
    return STATUS_EFFECTS.get(effect_id)


def get_effect_strict(effect_id: str) -> StatusEffectDef:
    if effect_id not in STATUS_EFFECTS:
        raise KeyError(f"Unknown status effect: '{effect_id}'. "
                       "Add it to status_effects.py before referencing it.")
    return STATUS_EFFECTS[effect_id]


# ---------------------------------------------------------------------------
# Apply / remove
# ---------------------------------------------------------------------------

def apply_status(
    champion: Champion,
    effect_id: str,
    duration_override_hours: int | None = None,
) -> bool:
    """
    Apply a status effect to the champion.
    Returns True if newly applied, False if already active (no duplicate created).

    Does not commit — caller is responsible for db.commit().
    """
    from db.models import ActiveStatus

    defn = get_effect_strict(effect_id)

    # No duplicate active effects
    if champion.has_status(effect_id):
        return False

    duration = duration_override_hours if duration_override_hours is not None \
               else defn.default_duration_hours

    status = ActiveStatus(
        champion_id=champion.id,
        effect_id=effect_id,
        display_name=defn.display_name,
        is_active=True,
        is_cursed_item=defn.is_cursed_item,
        is_toy=defn.is_toy,
        duration_remaining=duration,
        applied_at=datetime.utcnow(),
    )
    champion.statuses.append(status)

    # Apply stat modifiers directly to champion columns
    _apply_stat_mods(champion, defn.stat_modifiers, direction=1)

    # Sync cursed-item flag on champion
    if defn.is_cursed_item and effect_id == "chastity_flat":
        champion.chastity_locked = True

    return True


def remove_status(
    champion: Champion,
    effect_id: str,
    forced: bool = False,
) -> bool:
    """
    Remove a status effect from the champion.

    If forced=False, respects removal_difficulty — IMPOSSIBLE effects
    cannot be removed, KEY_ITEM / RITUAL effects raise StatusRemovalError
    unless forced.

    Returns True if removed, False if not found.
    Does not commit — caller is responsible for db.commit().
    """
    defn = get_effect_strict(effect_id)

    if not forced:
        if defn.removal_difficulty == RemovalDifficulty.IMPOSSIBLE:
            raise StatusRemovalError(
                f"'{defn.display_name}' cannot be removed: {defn.removal_condition}"
            )

    for status in champion.statuses:
        if status.effect_id == effect_id and status.is_active:
            status.is_active = False
            _apply_stat_mods(champion, defn.stat_modifiers, direction=-1)

            if effect_id == "chastity_flat":
                champion.chastity_locked = False

            return True

    return False


# ---------------------------------------------------------------------------
# Duration tick
# ---------------------------------------------------------------------------

def tick_status_durations(champion: Champion, hours_elapsed: float = 1.0) -> list[str]:
    """
    Advance duration counters on all active timed effects.
    Returns list of effect_ids that expired this tick.

    Does not commit — caller is responsible.
    """
    expired: list[str] = []

    for status in champion.statuses:
        if not status.is_active:
            continue
        if status.duration_remaining is None:
            continue  # permanent or indefinite

        status.duration_remaining -= int(hours_elapsed)
        if status.duration_remaining <= 0:
            defn = STATUS_EFFECTS.get(status.effect_id)
            if defn:
                _apply_stat_mods(champion, defn.stat_modifiers, direction=-1)
            status.is_active = False
            expired.append(status.effect_id)

    return expired


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_stat_mods(champion: Champion, mods: dict[str, int], direction: int) -> None:
    """Add or subtract stat modifiers. direction: +1 to apply, -1 to reverse."""
    for stat, value in mods.items():
        current = getattr(champion, stat, None)
        if current is not None:
            setattr(champion, stat, current + (value * direction))


def active_scene_notes(champion: Champion) -> list[str]:
    """Return scene_note strings for all currently active effects that have one."""
    notes = []
    for status in champion.statuses:
        if not status.is_active:
            continue
        defn = STATUS_EFFECTS.get(status.effect_id)
        if defn and defn.scene_note:
            notes.append(defn.scene_note)
    return notes


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class StatusRemovalError(RuntimeError):
    """Raised when attempting to remove an effect that cannot be removed."""
