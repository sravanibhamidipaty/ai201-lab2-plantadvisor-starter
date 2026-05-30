# Spec: Tool Functions

**File:** `tools.py`
**Status:** `get_seasonal_conditions` — Pre-implemented, read through. `lookup_plant` — complete spec fields before implementing.

---

## Purpose

These two functions are the tools the agent can call. They retrieve structured data from the local plant database and seasonal data files and return it to the agent loop, which passes it to the LLM as context for generating a response.

---

## Function 1: `lookup_plant()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `plant_name` | `str` | The plant name as entered by the user or chosen by the LLM — may be any casing, common name, scientific name, or alias |

**Output:** `dict`

When the plant is **found**, return:
```python
{"found": True, "plant": <the full plant dict from _plant_db>}
```

When the plant is **not found**, return:
```python
{"found": False, "name": <normalized input>, "message": <helpful string>}
```

---

### Design Decisions

*Complete the two blank fields below before writing code. The others are pre-filled for you.*

---

#### Input normalization

Strip leading/trailing whitespace and convert to lowercase before any comparison.

```python
normalized = plant_name.strip().lower()
```

---

#### Search order

Search in this order: direct key → display name → aliases. Keys are the fastest
lookup (O(1) dict access), so check those first. Display names are the next most
likely match for clean user input. Aliases are the broadest net, so they go last.

```
1. Direct key match: normalized in _plant_db
2. Display name match: plant["display_name"].lower() == normalized
3. Alias match: normalized in [alias.lower() for alias in plant["aliases"]]
```

---

#### Alias matching approach

*Aliases are stored as a list of strings. How will you check if the normalized input matches any alias in the list? Write your approach in pseudocode or plain English.*

```
For the current database size (~15 plants), iterate each plant and test membership against a lowercased copy of its alias list:

    if normalized in [alias.lower() for alias in plant["aliases"]]:
        return {"found": True, "plant": plant}

Both sides are lowercased, the input once via .strip().lower() (stored as `normalized`), and each alias via the comprehension, which gives the case-insensitive match the contract requires. The same `normalized` value is reused for the key, display_name, and alias checks so all three stay consistent.

SCALING NOTE - why this changes at thousands of plants:
The approach above is O(n x aliases) per call because it re-scans every plant and rebuilds the lowercased alias list each time. At thousands of plants that's wasteful. The fix is to build a flat reverse-lookup dict ONCE at load time that maps every searchable name to its slug:

    _name_index = {}
    for slug, plant in _plant_db.items():
        _name_index[slug] = slug
        _name_index[plant["display_name"].lower()] = slug

        for alias in plant["aliases"]:
            _name_index[alias.lower()] = slug

Then each lookup collapses to a single O(1) access:
    slug = _name_index.get(normalized)

A dict (hash map) is the right structure: keys are pre-normalized, lookups are constant time regardless of size, and the build cost is amortized across requests.
```

---

#### Not-found message

*When a plant isn't found, the agent will read your message and use it to decide what to tell the user. Write the exact string you'll return — make it useful to the agent, not just to a human reading logs.*

```
f"No plant named '{normalized}' was found in the plant care database. The "
f"database covers these {len(_plant_db)} plants: {', '.join(p['display_name'] "
f"for p in _plant_db.values())}. Do not invent specific care facts for an"
f"unknown plant. Either ask the user to pick one of the plants above, check "
f"whether they meant one of them (the name may be a typo or a variety of a "
f"listed plant), or clearly tell them this plant isn't covered and keep any "
f"general advice high-level and caveated."

```

---

#### Implementation Notes

*Fill this in after implementing and running the app.*

**Test: does `"devil's ivy"` return the pothos entry?**
```
Yes. The direct-key and display-name checks miss, then the alias check matches
"devil's ivy" against the lowercased pothos aliases and returns the full pothos
dict with found: True.
```

**Test: does `"SNAKE PLANT"` return the snake plant entry?**
```
Yes. The input normalizes to "snake plant", which fails the direct-key check
(the key is the slug "snake_plant", not the display name) but matches on the
display_name comparison and returns the snake plant entry.
```

**One edge case you discovered while implementing:**
```
The slug key and the display name are not the same string — the key is
"snake_plant" (underscore) while the display name is "Snake Plant" (space).
Normalization handles casing and whitespace but does NOT convert spaces to
underscores, so a user typing "snake plant" never hits the O(1) key match and
only succeeds at the display-name step. For any multi-word plant the
display-name and alias passes are doing the real work. Worth remembering if the
reverse-index optimization is ever added.
```

---

## Function 2: `get_seasonal_conditions()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `season` | `str \| None` | One of `"spring"`, `"summer"`, `"fall"`, `"winter"`, or `None` to auto-detect |

**Output:** `dict`

The full season dict from `_season_data`, plus one additional field:

| Added field | Type | Value |
|-------------|------|-------|
| `"detected_season"` | `bool` | `True` if auto-detected from the month; `False` if season was passed as an argument |

---

### Design Decisions

*This function is pre-implemented — read through these fields and the code before working on `lookup_plant`.*

---

#### Auto-detection logic

When `season` is `None`, get the current calendar month with `datetime.now().month`
and look it up in the `_MONTH_TO_SEASON` dict, which maps month numbers to season strings.

```python
current_month = datetime.now().month
season_key = _MONTH_TO_SEASON[current_month]
```

---

#### Season validation

If the caller passes an invalid season string (e.g., `"monsoon"`), the function
falls back to auto-detection — same as if `None` were passed. The `VALID_SEASONS`
set acts as the gate:

```python
VALID_SEASONS = {"spring", "summer", "fall", "winter"}
if season and season.lower() in VALID_SEASONS:
    ...  # use provided season
else:
    ...  # auto-detect
```

---

#### Return structure

The full season dict from `_season_data`, plus a `detected_season` boolean. Example for spring:

```python
{
    "season": "spring",
    "watering": "Increase watering frequency as plants break dormancy ...",
    "fertilizing": "Resume feeding with a balanced fertilizer ...",
    "light": "Days are lengthening — move plants closer to windows ...",
    "pests": "Watch for spider mites and aphids as temperatures rise ...",
    "detected_season": True   # True = auto-detected; False = caller specified
}
```

---

#### Implementation Notes

*Fill this in after testing.*

**Test: does calling with `season=None` return the correct season for the current month?**
```
Current month: May (month 5)
Expected season: spring
Returned season: spring (with detected_season: True)
```

**Test: does calling with `season="winter"` return winter data regardless of the current month?**
```
Yes. "winter" is in VALID_SEASONS, so the function uses it directly and returns
the winter data with detected_season: False, even though the current month (May)
would auto-detect to spring.
```

---

## Function 3: `get_plant_list()` *(optional challenge — added)*

### Purpose

Answer catalog / attribute questions that `lookup_plant` can't, because the
database can only be queried by a single name, not by attribute. Examples:
"what plants do you know about?", "what's a good beginner plant?", "which
plants are easy?". Returns a lightweight summary (name + difficulty), not full
care data, so the agent can follow up with `lookup_plant` once the user picks one.

### Input / Output Contract

**Inputs:** none.

**Output:** `dict`

```python
{
    "count": 15,
    "plants": [
        {"display_name": "Aloe Vera", "scientific_name": "Aloe vera", "difficulty": "easy"},
        ...
    ],
}
```

### Design Decisions

- **Summary only, not full care data.** Returning every plant's complete care
  dict would flood the context window for a question the user hasn't committed
  to yet. Name + difficulty is enough for the agent to recommend or list, then
  call `lookup_plant` for the chosen plant. This keeps the two tools composable:
  `get_plant_list` for discovery, `lookup_plant` for detail.
- **Sorted easy → hard, then alphabetical.** Difficulty is ranked
  `easy=0, moderate=1, hard=2`. This means "good beginner plant" questions
  surface the easy options at the top of the list the LLM reads, nudging better
  recommendations without hardcoding any single answer.

### Implementation Notes

**Test: "what plants do you know about?"**
```
Agent calls get_plant_list({}) once, then summarizes all 15 plants grouped by
difficulty. No lookup_plant call — it doesn't need full care data to list names.
```

**Test: "what's a good beginner plant?"**
```
Agent calls get_plant_list({}), sees the easy plants first (Aloe Vera, Chinese
Evergreen, Peace Lily, Philodendron, Pothos, Snake Plant...), and recommends one
(Pothos in testing), offering to look up its full care data next.
```
