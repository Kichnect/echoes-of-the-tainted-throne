"""Level and XP system for Echoes of the Tainted Throne."""

# XP thresholds for each level (index = level - 1, so [0] = XP needed for level 2)
XP_THRESHOLDS = [100, 250, 450, 700, 1000, 1350, 1750, 2200, 2700]

# XP rewards
XP_FROM_COMBAT_WIN  = 25
XP_FROM_COMBAT_LOSS = 10
XP_FROM_DISCOVERY   = 15
XP_FROM_REST        = 5

# Stage-driven stat degradation (applied on top of base stats)
# These are deltas relative to base 10 — applied at each stage
STAGE_STAT_DELTAS = {
    0: {"force": 0, "resolve": 0, "grace": 0, "presence": 0},
    1: {"force": 0, "resolve": 0, "grace": 0, "presence": 0},  # no degradation yet
    2: {"force": -1, "resolve": 0, "grace": 1, "presence": 0},
    3: {"force": -2, "resolve": -2, "grace": 2, "presence": 2},
    4: {"force": -4, "resolve": -3, "grace": 3, "presence": 4},
}

# HP bonus per level above 1
HP_PER_LEVEL = 10


def get_level_for_xp(xp: int) -> int:
    """Return the level (1-10) for a given XP total."""
    level = 1
    for threshold in XP_THRESHOLDS:
        if xp >= threshold:
            level += 1
        else:
            break
    return min(level, 10)


def get_xp_to_next_level(xp: int) -> int | None:
    """Return XP needed for next level, or None if at max."""
    level = get_level_for_xp(xp)
    if level >= 10:
        return None
    return XP_THRESHOLDS[level - 1] - xp


def award_xp(champion, xp_amount: int, source: str = "") -> dict:
    """
    Add XP to champion, update level if threshold crossed, adjust max_hp.
    Returns dict with old_level, new_level, xp_gained, leveled_up.
    """
    old_level = champion.level or 1
    old_xp    = champion.experience or 0

    champion.experience = old_xp + xp_amount
    new_level = get_level_for_xp(champion.experience)
    champion.level = new_level

    leveled_up = new_level > old_level
    if leveled_up:
        # +10 max HP per level gained
        levels_gained = new_level - old_level
        champion.max_hp = (champion.max_hp or 90) + (HP_PER_LEVEL * levels_gained)
        # Heal some HP on level-up
        champion.current_hp = min(champion.current_hp + 20, champion.max_hp)

    return {
        "old_level":  old_level,
        "new_level":  new_level,
        "xp_gained":  xp_amount,
        "total_xp":   champion.experience,
        "leveled_up": leveled_up,
        "source":     source,
    }


def apply_stage_stat_deltas(champion, stage: int):
    """
    Apply stat degradation/boost for the given stage.
    This replaces any previous stage's deltas — call after stage transition.
    Note: This modifies the base stat values. Background bonuses are NOT re-applied here.
    """
    deltas = STAGE_STAT_DELTAS.get(stage, {})
    # Reset to base 10 first, then apply stage delta
    # (background bonus was applied at creation, stored in equipment_slots effects)
    base = 10
    for stat in ("force", "resolve", "grace", "presence"):
        setattr(champion, stat, base + deltas.get(stat, 0))
