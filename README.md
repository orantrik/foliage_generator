# Foliage Generator — UE5

Places foliage on any surface that uses a selected material.
Spacing rules follow the Israeli National Guide for Shading Trees (2020).

---

## Files

| File | Purpose |
|------|---------|
| `foliage_setup.py` | Run once in UE5 — creates the widget |
| `foliage_generator_core.py` | Called by Generate button — places foliage |
| `foliage_pick_material.py` | Called by Pick button — eyedropper for material |

---

## Setup (run once)

1. Copy all three `.py` files to one folder, e.g. `C:/FoliageGen/`
2. Open `foliage_setup.py` — set `SCRIPTS_FOLDER` to that path
3. In UE5: **Tools → Execute Python Script → select `foliage_setup.py`**
4. Widget is created at **Content/FoliageGenerator/EUW_FoliageGenerator**
5. Open the widget blueprint and wire two buttons (30 sec, see printed instructions)

---

## Usage

1. Right-click `EUW_FoliageGenerator` → **Run Editor Utility Widget**
2. Click a surface in the viewport → click **↗ Pick** to auto-fill the material path
   (or paste a `/Game/...` path manually)
3. Check the foliage assets you want to place (✓ marks assets already in the Foliage Tool)
4. Assign each a **Category** based on tree size
5. Click **▶ Generate Foliage**

---

## Foliage Categories (Israeli National Guide §4.1)

| Category     | Spacing   | Scale range | Alignment      |
|--------------|-----------|-------------|----------------|
| LARGE_TREE   | 10–15 m   | 0.90–1.10   | Upright        |
| MEDIUM_TREE  | 7–10 m    | 0.85–1.15   | Upright        |
| SMALL_TREE   | 4–7 m     | 0.80–1.20   | Surface normal |
| SHRUB        | 1.5–3 m   | 0.70–1.30   | Surface normal |

---

## Requirements

- UE5 with **Python Editor Script Plugin** enabled *(Edit → Plugins → "Python")*
- Foliage Tool plugin (default in UE5)
- FoliageType assets in your project (created via the Foliage Tool panel)
