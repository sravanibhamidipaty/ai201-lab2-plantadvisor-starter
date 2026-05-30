import json
import os
from datetime import datetime
from config import DATA_PATH

# Plant database and seasonal data are loaded once at module load.
# This mirrors how a real service would cache its data source in memory.
with open(os.path.join(DATA_PATH, "plants.json"), encoding="utf-8") as f:
    _plant_db = json.load(f)

with open(os.path.join(DATA_PATH, "seasons.json"), encoding="utf-8") as f:
    _season_data = json.load(f)

# Maps calendar months to seasons for auto-detection.
_MONTH_TO_SEASON = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall",  10: "fall",  11: "fall",
}


def lookup_plant(plant_name: str) -> dict:
    normalized = plant_name.strip().lower()

    # 1. Direct key match - O(1)
    if normalized in _plant_db:
        return {"found": True, "plant": _plant_db[normalized]}

    # 2. Display name, then 3. alias - one pass over the plants
    for plant in _plant_db.values():
        if plant["display_name"].lower() == normalized:
            return {"found": True, "plant": plant}
        if normalized in [alias.lower() for alias in plant["aliases"]]:
            return {"found": True, "plant": plant}

    available = ", ".join(p["display_name"] for p in _plant_db.values())
    return {
        "found": False,
        "name": normalized,
        "message": (
            f"No plant named '{normalized}' was found in the plant care database. "
            f"The database covers these {len(_plant_db)} plants: {available}. "
            f"Do not invent specific care facts for an unknown plant. Either ask "
            f"the user to pick one of the plants above, check whether they meant "
            f"one of them (the name may be a typo or a variety of a listed plant), "
            f"or clearly tell them this plant isn't covered and keep any general "
            f"advice high-level and caveated."
        ),
    }


def get_plant_list() -> dict:
    """
    Return a catalog of every plant in the database with its display name,
    scientific name, and difficulty level.

    Use this to answer "what plants do you know about?" or attribute-style
    questions like "what's a good beginner plant?" — questions that can't be
    answered by looking up a single plant by name. Returns names and difficulty
    only (not full care data) so the agent can follow up with lookup_plant() for
    whichever plant the user picks.
    """
    plants = [
        {
            "display_name": plant["display_name"],
            "scientific_name": plant["scientific_name"],
            "difficulty": plant["difficulty"],
        }
        for plant in _plant_db.values()
    ]
    # Sort by difficulty (easy first) then name, so "good beginner plant"
    # questions surface the easy plants at the top of the list.
    _difficulty_rank = {"easy": 0, "moderate": 1, "hard": 2}
    plants.sort(key=lambda p: (_difficulty_rank.get(p["difficulty"], 99), p["display_name"]))
    return {"count": len(plants), "plants": plants}


def get_seasonal_conditions(season: str | None = None) -> dict:
    """
    Return current seasonal care context for houseplants.

    If season is provided and valid, returns that season's data.
    If season is None (or invalid), auto-detects from the current calendar month.

    Pre-implemented — read through this and the spec before working on lookup_plant().
    """
    VALID_SEASONS = {"spring", "summer", "fall", "winter"}

    if season and season.lower() in VALID_SEASONS:
        # Caller specified a valid season — use it directly
        season_key = season.lower()
        detected = False
    else:
        # Auto-detect from the current month using the _MONTH_TO_SEASON mapping
        current_month = datetime.now().month
        season_key = _MONTH_TO_SEASON[current_month]
        detected = True

    # Copy the season dict so we don't mutate the cached data
    result = dict(_season_data[season_key])
    result["detected_season"] = detected
    return result
