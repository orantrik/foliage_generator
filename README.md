# Foliage Generator — UE5

Places foliage on any surface that uses a selected material, using spacing rules from the Israeli National Guide for Shading Trees (2020).

---

## Setup (run once)

1. Copy both `.py` files to a local folder, e.g. `C:/FoliageGen/`
2. Open `foliage_setup.py` and set `CORE_SCRIPT_PATH` to the full path of `foliage_generator_core.py`
3. In UE5: **Tools → Execute Python Script → select `foliage_setup.py`**
4. Widget is created at **Content/FoliageGenerator/EUW_FoliageGenerator**

---

## Usage

1. Right-click `EUW_FoliageGenerator` → **Run Editor Utility Widget**
2. Set the **Material Path** (e.g. `/Game/Materials/M_Ground`)
3. Check the foliage assets you want to place and assign each a **Category**
4. Click **▶ Generate Foliage**

---

## Foliage Categories (Israeli National Guide §4.1)

| Category     | Spacing   | Scale range | Alignment     |
|--------------|-----------|-------------|---------------|
| LARGE_TREE   | 10–15 m   | 0.90–1.10   | Upright       |
| MEDIUM_TREE  | 7–10 m    | 0.85–1.15   | Upright       |
| SMALL_TREE   | 4–7 m     | 0.80–1.20   | Surface normal |
| SHRUB        | 1.5–3 m   | 0.70–1.30   | Surface normal |

---

## Config (edit `foliage_generator_core.py`)

| Variable              | Description                                        |
|-----------------------|----------------------------------------------------|
| `TARGET_MATERIAL_PATH`| Content path of the material to detect            |
| `FOLIAGE_TYPES`       | List of `(FoliageType asset path, category)` pairs |
| `PLACEMENT_SEED`      | Change to get a different random layout            |

---

## Requirements

- Unreal Engine 5 with **Python Editor Script Plugin** enabled
  *(Edit → Plugins → search "Python" → enable)*
- Foliage Tool plugin enabled (default in UE5)
- FoliageType assets already created in your project
