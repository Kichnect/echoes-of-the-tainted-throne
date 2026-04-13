"""
Cursed item registry for Echoes of the Tainted Throne.

A CursedItemDef describes a physical item the Champion can acquire or have
forced onto them. Each item applies one or more status effects and has
specific acquisition and removal conditions.

The registry here is the canonical list.  Status-effect application is
delegated to status_effects.apply_status(); this module handles the
item-level logic (can it be applied, can it be removed, what else happens).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from status_effects import (
    apply_status, remove_status,
    StatusRemovalError, RemovalDifficulty,
    get_effect_strict,
)

if TYPE_CHECKING:
    from db.models import Champion


# ---------------------------------------------------------------------------
# CursedItemDef
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CursedItemDef:
    id: str
    display_name: str
    description: str

    # Status effects this item applies when worn
    status_effect_ids: list[str] = field(default_factory=list)

    # Item properties
    is_wearable: bool = True
    is_stackable: bool = False   # can more than one be applied at once?
    slot: str = "none"           # body slot: "chastity", "clothing", "plug", "collar", "misc"

    # Acquisition
    acquisition_note: str = ""   # where/how it is found or applied

    # Removal
    removal_difficulty: RemovalDifficulty = RemovalDifficulty.RITUAL
    removal_condition: str = ""

    # Corruption gain when the item is first applied
    corruption_on_apply: float = 0.0

    # Submission event fired when the item is first applied
    submission_event_on_apply: str | None = None

    # Corruption gain when successfully removed
    corruption_on_remove: float = 0.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ITEMS: list[CursedItemDef] = [

    CursedItemDef(
        id="chastity_device",
        display_name="Iron Chastity Device",
        description="A lockable iron cage with a short chain to a waistband ring. "
                    "Prevents penile stimulation entirely. The lock is a simple ward "
                    "against brute force — it will not break, but the key will.",
        status_effect_ids=["chastity_flat"],
        slot="chastity",
        acquisition_note="Applied by a dominant NPC, won as a bet, found in a trap chest, "
                         "or purchased at the Thornmere pleasure-shop.",
        removal_difficulty=RemovalDifficulty.KEY_ITEM,
        removal_condition="The matching key, a lockpicking success (Grace check DC 18), "
                          "or Tierlan's lockpick kit after he offers.",
        corruption_on_apply=2.0,
        submission_event_on_apply="chastity_device_applied",
    ),

    CursedItemDef(
        id="cursed_harem_outfit",
        display_name="Cursed Harem Attire",
        description="Layers of sheer silk and copper-thread embroidery with corruption "
                    "sigils stitched into the hems. Physically resists removal; the fabric "
                    "tightens when pulled. Leaves almost nothing to the imagination.",
        status_effect_ids=["cursed_harem_clothes"],
        slot="clothing",
        acquisition_note="Gifted by Kasyrra, forced by a cult devotee, or found as "
                         "a triggered trap in a ruin chest.",
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="Mireille's dispel ritual (requires 2 research notes) "
                          "or a purification shrine.",
        corruption_on_apply=3.0,
        submission_event_on_apply="cursed_clothing_worn",
    ),

    CursedItemDef(
        id="binding_plug",
        display_name="Binding Plug",
        description="Dark crystal carved into a tapered form, warm to the touch. "
                    "A short enchanted tether locks it in place the moment it is seated. "
                    "The crystal resonates faintly with movement — every step felt.",
        status_effect_ids=["cursed_plug"],
        slot="plug",
        acquisition_note="Applied by Kasyrra or a dominant encounter NPC. "
                         "Occasionally found in corruption-zone puzzle chests.",
        removal_difficulty=RemovalDifficulty.RITUAL,
        removal_condition="The binding key (carried by the NPC who applied it) "
                          "or Mireille's dispel ritual.",
        corruption_on_apply=3.5,
        submission_event_on_apply="plug_active",
    ),

    CursedItemDef(
        id="kasyrras_collar",
        display_name="Kasyrra's Collar",
        description="Thin hammered copper set with a single translucent amber stone. "
                    "Looks almost delicate. The brand it carries is not delicate. "
                    "Applies Kasyrra's Mark if not already present and activates "
                    "the Attraction Aura at Stage 2+.",
        status_effect_ids=["kasyrra_marked", "attraction_aura"],
        slot="collar",
        acquisition_note="Applied by Kasyrra at a significant encounter milestone. "
                         "Cannot be acquired any other way.",
        removal_difficulty=RemovalDifficulty.IMPOSSIBLE,
        removal_condition="Cannot be removed. Kasyrra designed it that way.",
        corruption_on_apply=5.0,
        submission_event_on_apply="kasyrra_encounter_submissive",
        corruption_on_remove=0.0,
    ),

    CursedItemDef(
        id="pheromone_vial_trap",
        display_name="Pheromone Vial (Triggered)",
        description="A small glass vial that shatters on contact and releases a cloud "
                    "of magically concentrated pheromones. Not wearable — a trap item "
                    "applied by encounter NPCs.",
        status_effect_ids=["pheromone_drunk"],
        slot="misc",
        is_wearable=False,
        acquisition_note="Triggered by imp swarms and some cultist encounters.",
        removal_difficulty=RemovalDifficulty.REST,
        removal_condition="Effect expires after 6 in-game hours.",
        corruption_on_apply=1.5,
        submission_event_on_apply=None,
    ),

]

CURSED_ITEMS: dict[str, CursedItemDef] = {item.id: item for item in _ITEMS}


def get_item(item_id: str) -> CursedItemDef | None:
    return CURSED_ITEMS.get(item_id)


def get_item_strict(item_id: str) -> CursedItemDef:
    if item_id not in CURSED_ITEMS:
        raise KeyError(f"Unknown cursed item: '{item_id}'")
    return CURSED_ITEMS[item_id]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_cursed_item(
    champion: Champion,
    item_id: str,
) -> CursedItemApplyResult:
    """
    Apply a cursed item to the champion.
    Fires all associated status effects, applies corruption and submission event.
    Does not commit — caller is responsible for db.commit().
    """
    from corruption import apply_corruption
    from submission import update_submission

    item = get_item_strict(item_id)

    statuses_applied: list[str] = []
    for effect_id in item.status_effect_ids:
        applied = apply_status(champion, effect_id)
        if applied:
            statuses_applied.append(effect_id)

    # Apply corruption hit
    corruption_result = None
    if item.corruption_on_apply > 0:
        corruption_result = apply_corruption(
            champion, item.corruption_on_apply, source=f"cursed_item:{item_id}"
        )

    # Fire submission event
    sub_result = None
    if item.submission_event_on_apply:
        sub_result = update_submission(champion, item.submission_event_on_apply)

    return CursedItemApplyResult(
        item_id=item_id,
        statuses_applied=statuses_applied,
        corruption_gained=item.corruption_on_apply,
        submission_event=item.submission_event_on_apply,
    )


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

def attempt_item_removal(
    champion: Champion,
    item_id: str,
    method: str = "player",
    forced: bool = False,
) -> CursedItemRemoveResult:
    """
    Attempt to remove a cursed item.

    method: "player" | "key_item" | "ritual" | "event" | "forced"
    forced: bypass removal difficulty checks (for engine-driven events)

    Returns a result describing what happened.
    Does not commit — caller is responsible.
    """
    from corruption import apply_corruption
    from submission import update_submission, update_submission_raw

    item = get_item_strict(item_id)

    # Check removal difficulty vs method
    if not forced:
        if item.removal_difficulty == RemovalDifficulty.IMPOSSIBLE:
            return CursedItemRemoveResult(
                item_id=item_id,
                success=False,
                reason=item.removal_condition,
                statuses_removed=[],
            )

        method_map = {
            "player":   [RemovalDifficulty.PLAYER],
            "key_item": [RemovalDifficulty.KEY_ITEM, RemovalDifficulty.PLAYER],
            "ritual":   [RemovalDifficulty.RITUAL, RemovalDifficulty.KEY_ITEM, RemovalDifficulty.PLAYER],
            "event":    [RemovalDifficulty.EVENT, RemovalDifficulty.RITUAL, RemovalDifficulty.KEY_ITEM, RemovalDifficulty.PLAYER],
        }
        allowed = method_map.get(method, [])
        if item.removal_difficulty not in allowed:
            return CursedItemRemoveResult(
                item_id=item_id,
                success=False,
                reason=f"Cannot remove with method '{method}'. {item.removal_condition}",
                statuses_removed=[],
            )

    removed_effects: list[str] = []
    for effect_id in item.status_effect_ids:
        try:
            did_remove = remove_status(champion, effect_id, forced=forced)
            if did_remove:
                removed_effects.append(effect_id)
        except StatusRemovalError:
            pass  # Some sub-effects may be impossible even if the item is removable

    # Fire the broke_curse_item submission event (resistance reward)
    if removed_effects:
        update_submission(champion, "broke_curse_item")

    return CursedItemRemoveResult(
        item_id=item_id,
        success=bool(removed_effects),
        reason="Removed successfully." if removed_effects else "No active effects found.",
        statuses_removed=removed_effects,
    )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CursedItemApplyResult:
    item_id: str
    statuses_applied: list[str]
    corruption_gained: float
    submission_event: str | None


@dataclass
class CursedItemRemoveResult:
    item_id: str
    success: bool
    reason: str
    statuses_removed: list[str]
