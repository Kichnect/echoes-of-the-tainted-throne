"""
Weather system for Echoes of the Tainted Throne.

Weather changes every 1-3 in-game days via weighted random roll per region.
Each weather state has mechanical effects applied during time advancement.
"""
from __future__ import annotations
import random

# Weather transition weights per region_id
# Values sum to 100
REGION_WEATHER_WEIGHTS: dict[str, dict[str, int]] = {
    "wolf_road": {
        "clear": 30, "cloudy": 25, "rain": 20, "fog": 15, "storm": 5, "tainted_mist": 5,
    },
    "warming_frost": {
        "clear": 20, "cloudy": 20, "rain": 15, "fog": 20, "storm": 10, "tainted_mist": 15,
    },
    "imp_warren_entrance": {
        "clear": 25, "cloudy": 25, "rain": 20, "fog": 15, "storm": 5, "tainted_mist": 10,
    },
    "kitsune_circuit": {
        "clear": 40, "cloudy": 25, "rain": 20, "fog": 10, "storm": 3, "tainted_mist": 2,
    },
    "cult_ascent": {
        "clear": 15, "cloudy": 20, "rain": 15, "fog": 20, "storm": 10, "tainted_mist": 20,
    },
    "_default": {
        "clear": 30, "cloudy": 30, "rain": 20, "fog": 10, "storm": 5, "tainted_mist": 5,
    },
}

# Mechanical modifiers per weather state
WEATHER_EFFECTS: dict[str, dict] = {
    "clear":        {"morale_per_day": 5,  "travel_cost": 0,  "encounter_mod": 0,   "corruption_per_hour": 0.0,  "arousal_per_hour": 0,  "travel_blocked": False},
    "cloudy":       {"morale_per_day": 0,  "travel_cost": 0,  "encounter_mod": 0,   "corruption_per_hour": 0.0,  "arousal_per_hour": 0,  "travel_blocked": False},
    "rain":         {"morale_per_day": -2, "travel_cost": 1,  "encounter_mod": 10,  "corruption_per_hour": 0.0,  "arousal_per_hour": 0,  "travel_blocked": False},
    "fog":          {"morale_per_day": -2, "travel_cost": 1,  "encounter_mod": 20,  "corruption_per_hour": 0.0,  "arousal_per_hour": 0,  "travel_blocked": False},
    "storm":        {"morale_per_day": -5, "travel_cost": 99, "encounter_mod": -50, "corruption_per_hour": 0.0,  "arousal_per_hour": 0,  "travel_blocked": True},
    "tainted_mist": {"morale_per_day": -3, "travel_cost": 1,  "encounter_mod": 15,  "corruption_per_hour": 1.0,  "arousal_per_hour": 5,  "travel_blocked": False},
}

# Display symbols for frontend sidebar
WEATHER_SYMBOLS: dict[str, str] = {
    "clear":        "☀",
    "cloudy":       "☁",
    "rain":         "🌧",
    "fog":          "~",
    "storm":        "⚡",
    "tainted_mist": "☣",
}


def _region_to_id(region_name: str) -> str:
    """Convert display name to snake_case id."""
    return region_name.lower().replace(" ", "_").replace("-", "_")


def roll_next_weather(region_name: str) -> tuple[str, int]:
    """
    Roll the next weather state for a region.
    Returns (weather_state, days_until_next_change).
    """
    region_id = _region_to_id(region_name)
    weights = REGION_WEATHER_WEIGHTS.get(region_id, REGION_WEATHER_WEIGHTS["_default"])

    states = list(weights.keys())
    wts    = list(weights.values())
    new_weather = random.choices(states, weights=wts, k=1)[0]
    days_remaining = random.randint(1, 3)
    return new_weather, days_remaining


def get_weather_effects(weather: str) -> dict:
    """Return the mechanical effects dict for a weather state."""
    return WEATHER_EFFECTS.get(weather, WEATHER_EFFECTS["cloudy"])


def get_weather_symbol(weather: str) -> str:
    """Return the display symbol for a weather state."""
    return WEATHER_SYMBOLS.get(weather, "?")


def advance_weather(world) -> dict:
    """
    Called when a day rolls over. Decrements weather_days_remaining.
    If it hits 0, rolls new weather. Mutates world object in-place.
    Returns dict of changes.
    """
    days_rem = getattr(world, "weather_days_remaining", 1) or 1
    days_rem -= 1
    changed = False
    old_weather = str(world.weather.value if hasattr(world.weather, 'value') else world.weather)

    if days_rem <= 0:
        new_weather, new_days = roll_next_weather(world.region or "wolf_road")
        world.weather = new_weather
        world.weather_days_remaining = new_days
        changed = True
    else:
        world.weather_days_remaining = days_rem

    current = str(world.weather.value if hasattr(world.weather, 'value') else world.weather)
    return {
        "changed":          changed,
        "old_weather":      old_weather,
        "new_weather":      current,
        "days_remaining":   world.weather_days_remaining,
        "symbol":           get_weather_symbol(current),
        "effects":          get_weather_effects(current),
    }
