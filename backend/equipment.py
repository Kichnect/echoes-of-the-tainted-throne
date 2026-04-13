"""Equipment system for Echoes of the Tainted Throne."""

# Starting equipment per background
STARTING_EQUIPMENT = {
    "warrior": {
        "main_hand": {"id": "iron_spear", "name": "Iron Spear", "effects": {"force": 1}},
        "body":      {"id": "leather_vest", "name": "Leather Vest", "effects": {"max_hp": 10}},
        "legs":      {"id": "travel_boots", "name": "Travel Boots", "effects": {"grace": 1}},
    },
    "scholar": {
        "main_hand": {"id": "arcanist_staff", "name": "Arcanist Staff", "effects": {"presence": 2}},
        "body":      {"id": "worn_robes", "name": "Worn Robes", "effects": {}},
    },
    "scout": {
        "main_hand": {"id": "short_bow", "name": "Short Bow", "effects": {"grace": 1}},
        "body":      {"id": "light_leather", "name": "Light Leather Armor", "effects": {"max_hp": 5}},
    },
}

SLOT_ORDER = ["head", "body", "legs", "hands", "main_hand", "accessory", "cursed_slot"]

SLOT_LABELS = {
    "head":        "Head",
    "body":        "Body",
    "legs":        "Legs",
    "hands":       "Hands",
    "main_hand":   "Main Hand",
    "accessory":   "Accessory",
    "cursed_slot": "Cursed Slot",
}


def get_starting_equipment(background: str) -> dict:
    """Return the starting equipment dict for a background."""
    base = {slot: None for slot in SLOT_ORDER}
    items = STARTING_EQUIPMENT.get(background, {})
    base.update(items)
    return base


def get_stat_bonuses(equipment_slots: dict) -> dict:
    """Sum all stat bonuses from equipped items. Returns dict of stat → bonus."""
    bonuses = {}
    for slot_item in (equipment_slots or {}).values():
        if slot_item and isinstance(slot_item, dict):
            for stat, val in (slot_item.get("effects") or {}).items():
                bonuses[stat] = bonuses.get(stat, 0) + val
    return bonuses


def serialize_equipment(equipment_slots: dict) -> list:
    """Return a list of slot dicts for frontend display."""
    slots = equipment_slots or {}
    result = []
    for slot_key in SLOT_ORDER:
        item = slots.get(slot_key)
        result.append({
            "slot":  slot_key,
            "label": SLOT_LABELS[slot_key],
            "item":  item,
        })
    return result
