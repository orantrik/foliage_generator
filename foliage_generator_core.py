"""
Foliage Generator Core — Unreal Engine 5
=========================================
Accepts StaticMesh paths directly — no pre-existing FoliageType assets needed.

CONFIG BOX FORMAT (FoliageConfig in widget, one line per mesh):
  /Game/Trees/SM_Oak        LARGE_TREE
  /Game/Trees/SM_Birch      MEDIUM_TREE
  /Game/Shrubs/SM_Bush      SHRUB
  # lines starting with # are ignored

CATEGORIES (Israeli National Guide for Shading Trees, 2020):
  LARGE_TREE   spacing 10-15 m   upright
  MEDIUM_TREE  spacing  7-10 m   upright
  SMALL_TREE   spacing   4-7 m   surface-aligned
  SHRUB        spacing 1.5-3 m   surface-aligned

HOW TO USE:
  1. Right-click EUW_FoliageGenerator → Run Editor Utility Widget
  2. Pick material, fill or auto-scan mesh list, click Generate
"""

import unreal
import random
import math
import time
import json
import os

# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

WIDGET_ASSET_PATH  = "/Game/FoliageGenerator/EUW_FoliageGenerator"
WIDGET_OBJECT_PATH = WIDGET_ASSET_PATH + "." + WIDGET_ASSET_PATH.split("/")[-1]

# Config file written next to this script — lets you re-run without widget open
_THIS_DIR          = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE        = os.path.join(_THIS_DIR, "foliage_config.json")
LAST_MATERIAL_FILE = os.path.join(_THIS_DIR, "last_material.txt")

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY RULES  — Israeli National Guide for Shading Trees (2020)
# ══════════════════════════════════════════════════════════════════════════════

CATEGORY_RULES = {
    # jitter values raised to reflect Israeli courtyard aesthetic:
    # informal/naturalistic scatter (plant_planning.pdf + courtyard research).
    # Trees: 0.40 gives loose clusters; shrubs: 0.45 gives flowing drifts.
    "LARGE_TREE":  {"spacing": 1100, "jitter": 0.40, "scale": (0.90, 1.10), "align_normal": False},
    "MEDIUM_TREE": {"spacing":  850, "jitter": 0.40, "scale": (0.85, 1.15), "align_normal": False},
    "SMALL_TREE":  {"spacing":  500, "jitter": 0.35, "scale": (0.80, 1.20), "align_normal": True},
    "SHRUB":       {"spacing":  220, "jitter": 0.45, "scale": (0.70, 1.30), "align_normal": True},
}

MAX_POINTS_PER_CATEGORY = 500   # hard cap on spawned actors per surface patch per category

# Cell subdivision — guarantees every small courtyard gets dedicated planting cells.
# A 10 m cell ensures a 15 m × 15 m courtyard produces 1–4 cells instead of
# competing with a 450 m actor for statistical probability.
CELL_SIZE_CM = 1000   # 10 m per cell

# ── plant_planning.pdf — Table 3: tree dimensions by sidewalk/area width ──────
# Spacing bounds (cm) per category, derived from Israeli Ministry of Transport
# street planning guidelines.  Used to clamp the 30%-coverage spacing formula
# so that large trees are not placed too sparsely for Israeli courtyard scale.
SPACING_BOUNDS_CM = {
    "LARGE_TREE":  (1000, 1200),  # 10–12 m  (Table 3 — large tree row)
    "MEDIUM_TREE": ( 700, 1000),  # 7–10 m   (Table 3 — medium tree row)
    "SMALL_TREE":  ( 400,  600),  # 4–6 m    (Table 3 — small tree row)
    "SHRUB":       ( 150,  300),  # 1.5–3 m  (mass planting / drift)
}

# ── National Guide for Shading Trees (2020) ───────────────────────────────────
# Section 5.1 — canopy diameter thresholds (cm) per category
CANOPY_THRESHOLDS_CM = {
    # (min_inclusive, max_exclusive)
    "LARGE_TREE":  (1000, float("inf")),  # ≥10 m canopy
    "MEDIUM_TREE": (700,  1000),           # 7–10 m canopy
    "SMALL_TREE":  (400,  700),            # 4–7  m canopy
    "SHRUB":       (0,    400),            # <4   m canopy
}
# Section 4.4 — minimum shade coverage for public squares
TARGET_SHADE_COVERAGE = 0.30
# Section 4.1 — patch-area thresholds (m²) for choosing which category to prefer.
# Principle: "largest tree the cross-section can bear."
# Thresholds chosen so that at least 4 trees fit in each patch at guide spacing.
AREA_CATEGORY_THRESHOLDS_M2 = [
    (5000, "LARGE_TREE"),   # large park / open square
    (500,  "MEDIUM_TREE"),  # medium garden / large sports court
    (50,   "SMALL_TREE"),   # small court / footpath
    (0,    "SHRUB"),        # tiny planter / corner
]

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_running_widget():
    """Return the running EUW widget instance, or None."""
    try:
        subsystem    = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        widget_asset = unreal.find_object(None, WIDGET_OBJECT_PATH)
        if not widget_asset:
            widget_asset = unreal.load_object(None, WIDGET_OBJECT_PATH)
        if not widget_asset:
            return None
        return subsystem.find_utility_widget_from_blueprint(widget_asset)
    except Exception:
        return None


def _get_child(widget, name):
    for fn in [
        lambda: widget.get_widget_from_name(name),
        lambda: unreal.UserWidget.get_widget_from_name(widget, name),
    ]:
        try:
            w = fn()
            if w is not None:
                return w
        except Exception:
            pass
    return None


def _widget_text(widget, name, fallback=""):
    w = _get_child(widget, name)
    return str(w.get_text()).strip() if w else fallback


def _set_widget_text(widget, name, text):
    w = _get_child(widget, name)
    if w is None:
        return
    for val in [text, unreal.Text(text)]:
        try:
            w.set_text(val)
            return
        except Exception:
            continue


def _set_status(msg, widget=None):
    print(f"[Foliage] {msg}")
    if widget is None:
        widget = _get_running_widget()
    if widget:
        _set_widget_text(widget, "StatusLog", msg)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG FILE
# ══════════════════════════════════════════════════════════════════════════════

def _save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[Foliage] Could not save config file: {e}")


def _load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  CONTENT BROWSER SELECTION  — quick plant picker using native CB thumbnails
# ══════════════════════════════════════════════════════════════════════════════

def _extract_static_mesh(asset):
    """
    Return a raw StaticMesh from *asset*.

    Handles two cases:
      1. asset is already a StaticMesh → returned as-is.
      2. asset is a FoliageType_InstancedStaticMesh (or any other wrapper that
         exposes a 'mesh' property) → the inner StaticMesh is extracted and
         returned.

    Returns None if the asset cannot be resolved to a StaticMesh.
    """
    if asset is None:
        return None
    if isinstance(asset, unreal.StaticMesh):
        return asset
    # Try to unwrap FoliageType_InstancedStaticMesh (and similar wrappers)
    try:
        inner = asset.get_editor_property("mesh")
        if isinstance(inner, unreal.StaticMesh):
            return inner
    except Exception:
        pass
    return None


def _canopy_diameter_cm(mesh):
    """
    Measure the horizontal (XY) canopy footprint of a StaticMesh asset in cm.
    Uses the mesh local bounding box — the largest of the X and Y extents.
    Falls back to 500 cm (5 m) if the bounding box can't be read.
    """
    try:
        bbox = mesh.get_bounding_box()
        dx = bbox.max.x - bbox.min.x
        dy = bbox.max.y - bbox.min.y
        return max(dx, dy)
    except Exception:
        return 500.0


def _classify_by_diameter(diameter_cm):
    """
    Classify a mesh into a foliage category based on its measured canopy
    diameter, using the National Guide for Shading Trees (2020) Section 5.1
    canopy diameter thresholds.
    """
    for cat, (lo, hi) in CANOPY_THRESHOLDS_CM.items():
        if lo <= diameter_cm < hi:
            return cat
    return "SHRUB"


def _spacing_for_coverage(canopy_diameter_cm, target=TARGET_SHADE_COVERAGE,
                          category=None):
    """
    Derive planting spacing (cm) to achieve the target shade coverage fraction.

    Based on National Guide Section 4.4 (30% shade minimum for public squares).
    Formula for square grid:
        coverage = π × r² / s²   →   s = r × √(π / coverage)

    The result is clamped to the bounds from plant_planning.pdf Table 3
    (Israeli Ministry of Transport street planning guidelines).  This keeps
    large trees within the realistic 10–12 m courtyard spacing range rather
    than letting the formula produce 19+ m spacings for big canopies.

    If no category is given the old diameter-relative clamp is used as fallback.
    """
    r = canopy_diameter_cm / 2.0
    spacing = r * math.sqrt(math.pi / target)

    if category and category in SPACING_BOUNDS_CM:
        lo_cm, hi_cm = SPACING_BOUNDS_CM[category]
    else:
        # Fallback: slight overlap lower, 2× upper (original behaviour)
        lo_cm = canopy_diameter_cm * 0.90
        hi_cm = canopy_diameter_cm * 2.00

    return max(lo_cm, min(spacing, hi_cm))


def _category_for_patch(patch_area_m2, available_categories):
    """
    Select the most appropriate foliage category for a surface patch of the
    given area, according to the National Guide principle 'largest tree the
    space can bear' (Section 4.1 Note d).

    Searches from the ideal category outward (both smaller and larger) until
    an available category is found.  Returns None if nothing is available.
    """
    # Determine the ideal category by area threshold
    ideal = "SHRUB"
    for min_area, cat in AREA_CATEGORY_THRESHOLDS_M2:
        if patch_area_m2 >= min_area:
            ideal = cat
            break

    priority = ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]
    ideal_idx = priority.index(ideal)

    # Search: ideal first, then smaller (safer), then larger
    search_order = [ideal_idx]
    for delta in range(1, len(priority)):
        if ideal_idx + delta < len(priority):
            search_order.append(ideal_idx + delta)     # smaller
        if ideal_idx - delta >= 0:
            search_order.append(ideal_idx - delta)     # larger

    for idx in search_order:
        cat = priority[idx]
        if cat in available_categories:
            return cat
    return None


def _guess_category(name):
    """Name-based fallback when mesh diameter cannot be measured (legacy)."""
    n = name.upper()
    if any(w in n for w in ["SHRUB", "BUSH", "HEDGE", "GRASS", "IVY", "PLANT",
                             "FERN", "FLOWER", "WEED", "REED", "LEAF", "LEAVES",
                             "LITTER", "DRY", "GROUND", "COVER", "MOSS"]):
        return "SHRUB"
    if any(w in n for w in ["SMALL", "SAPLING", "YOUNG"]):
        return "SMALL_TREE"
    if any(w in n for w in ["LARGE", "BIG", "TALL", "GIANT"]):
        return "LARGE_TREE"
    return "MEDIUM_TREE"


def _mesh_list_from_cb_selection(cat_lookup):
    """
    Return [(sm_path, category)] for every StaticMesh or
    FoliageType_InstancedStaticMesh currently selected in the Content Browser.

    Category assignment priority:
      1. Explicit category from cat_lookup (previously saved config).
      2. Auto-detection from the mesh's measured canopy diameter using the
         National Guide Section 5.1 thresholds.
      3. Name-based heuristic fallback (_guess_category).
    """
    try:
        selected = unreal.EditorUtilityLibrary.get_selected_assets()
    except Exception:
        return []

    result = []
    for asset in selected:
        sm_path = None
        mesh    = None
        name    = ""

        if isinstance(asset, unreal.StaticMesh):
            p       = asset.get_path_name()
            sm_path = p.rsplit(".", 1)[0] if "." in p else p
            name    = asset.get_name()
            mesh    = asset
        elif isinstance(asset, unreal.FoliageType_InstancedStaticMesh):
            try:
                m = asset.get_editor_property("mesh")
                if m:
                    p       = m.get_path_name()
                    sm_path = p.rsplit(".", 1)[0] if "." in p else p
                    name    = m.get_name()
                    mesh    = m
            except Exception:
                pass

        if sm_path:
            if sm_path in cat_lookup:
                # Honour previously assigned category
                category = cat_lookup[sm_path]
            elif mesh is not None:
                # Auto-detect from measured bounding box
                diameter = _canopy_diameter_cm(mesh)
                category = _classify_by_diameter(diameter)
                print(f"[Foliage]   Auto-classified '{name}': "
                      f"canopy {diameter/100:.1f} m → {category}")
            else:
                category = _guess_category(name)
            result.append((sm_path, category))
    return result

# ══════════════════════════════════════════════════════════════════════════════
#  MESH SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def _scan_static_meshes(folder="/Game/"):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    filter_  = unreal.ARFilter(
        class_names       = ["StaticMesh"],
        package_paths     = [folder],
        recursive_paths   = True,
        recursive_classes = False,
    )
    assets = registry.get_assets(filter_)
    paths  = []
    for a in assets:
        pkg  = str(a.package_path)
        name = str(a.asset_name)
        paths.append(f"{pkg}/{name}")
    return sorted(paths)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG PARSING
# ══════════════════════════════════════════════════════════════════════════════

def _parse_mesh_config(text):
    valid  = set(CATEGORY_RULES.keys())
    result = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts    = line.split()
        sm_path  = parts[0]
        category = parts[1].upper() if len(parts) >= 2 else "MEDIUM_TREE"
        if category not in valid:
            category = "MEDIUM_TREE"
        result.append((sm_path, category))
    return result

# ══════════════════════════════════════════════════════════════════════════════
#  READ CONFIG FROM WIDGET
# ══════════════════════════════════════════════════════════════════════════════

def _read_widget_config(widget):
    material_path = _widget_text(widget, "MaterialPathInput")

    # Fallback: read from file written by foliage_pick_material.py
    if not material_path:
        try:
            if os.path.exists(LAST_MATERIAL_FILE):
                with open(LAST_MATERIAL_FILE) as f:
                    material_path = f.read().strip()
                if material_path:
                    _set_widget_text(widget, "MaterialPathInput", material_path)
                    print(f"[Foliage] Material loaded from last_material.txt: {material_path}")
        except Exception:
            pass

    if not material_path:
        _set_status(
            "⚠  Material path is empty.\n"
            "Select a surface → click ↗ Pick, or paste a /Game/... path.",
            widget
        )
        return None

    seed_str = _widget_text(widget, "SeedInput", "42")
    try:
        seed = int(seed_str)
    except ValueError:
        seed = 42

    mesh_folder = _widget_text(widget, "MeshFolderInput", "/Game/").rstrip("/") or "/Game/"
    cfg_text    = _widget_text(widget, "FoliageConfig", "")
    mesh_list   = _parse_mesh_config(cfg_text)

    if not mesh_list:
        saved = _load_config()

        # ── Priority 1: Content Browser selection ─────────────────────────────
        # Build category lookup from saved JSON so CB-selected meshes inherit
        # their previously assigned categories.
        cat_lookup = {}
        if saved and saved.get("mesh_list"):
            for row in saved["mesh_list"]:
                cat_lookup[row[0]] = row[1]

        cb_list = _mesh_list_from_cb_selection(cat_lookup)
        if cb_list:
            mesh_list = cb_list
            print(f"[Foliage] Using {len(mesh_list)} mesh(es) from Content Browser selection")
            for path, cat in mesh_list[:5]:
                print(f"[Foliage]   {path.split('/')[-1]}  [{cat}]")
            if len(mesh_list) > 5:
                print(f"[Foliage]   … and {len(mesh_list) - 5} more")

        # ── Priority 2: Saved JSON config ──────────────────────────────────────
        elif saved and saved.get("mesh_list"):
            mesh_list = [(row[0], row[1]) for row in saved["mesh_list"]]
            print(f"[Foliage] FoliageConfig empty — using {len(mesh_list)} mesh(es) from foliage_config.json")

        # ── Priority 3: First run — scan and save ──────────────────────────────
        else:
            _set_status(f"Scanning {mesh_folder} for meshes...", widget)
            paths = _scan_static_meshes(mesh_folder)
            if not paths:
                _set_status(
                    f"⚠  No StaticMesh assets found in {mesh_folder}\n"
                    "Set MeshFolderInput to a folder that contains your tree/shrub meshes.",
                    widget
                )
                return None

            auto_cfg = {
                "material_path": material_path,
                "seed":          seed,
                "mesh_folder":   mesh_folder,
                "mesh_list":     [[p, "MEDIUM_TREE"] for p in paths],
            }
            _save_config(auto_cfg)

            preview = "\n  ".join(p.split("/")[-1] for p in paths[:8])
            if len(paths) > 8:
                preview += f"\n  … and {len(paths) - 8} more"

            _set_status(
                f"Found {len(paths)} mesh(es). Config saved to:\n{CONFIG_FILE}\n\n"
                f"First 8:\n  {preview}\n\n"
                "── QUICK WAY ──────────────────────────────\n"
                "In the Content Browser, Ctrl+click the\n"
                "tree/shrub meshes you want, then click\n"
                "▶ Generate Foliage — no JSON editing needed.\n\n"
                "── FULL CONFIG ─────────────────────────────\n"
                "Edit foliage_config.json: remove non-foliage\n"
                "rows, set LARGE_TREE / MEDIUM_TREE / SHRUB.\n"
                "Then click ▶ Generate Foliage again.",
                widget
            )
            print(f"[Foliage] Config written to: {CONFIG_FILE}")
            return None

    # Load existing JSON first so category_settings / canopy_collision written
    # by foliage_settings.py are NOT overwritten on every Generate click.
    cfg = _load_config() or {}
    cfg.update({
        "material_path": material_path,
        "seed":          seed,
        "mesh_folder":   mesh_folder,
        "mesh_list":     [[p, c] for p, c in mesh_list],
    })
    _save_config(cfg)
    return cfg

# ══════════════════════════════════════════════════════════════════════════════
#  SURFACE MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def _clean_path(raw):
    """Strip object suffix and return the clean package path."""
    p = raw
    if ":" in p:
        p = p.split(":")[0]
    if "." in p:
        p = p.rsplit(".", 1)[0]
    return p


def _effective_materials(component):
    """
    Yield every effective material on a StaticMeshComponent.
    Component-level overrides take priority per slot; slots with no override
    fall back to the mesh asset's own material array.
    This covers both 'material set on component' and 'material set on mesh'.
    """
    overrides = []
    mesh_mats = []
    try:
        overrides = list(component.get_materials() or [])
    except Exception:
        pass
    try:
        sm = component.get_editor_property("static_mesh")
        if sm:
            raw = list(sm.get_materials() or [])
            for entry in raw:
                if entry is None:
                    mesh_mats.append(None)
                elif isinstance(entry, unreal.MaterialInterface):
                    # Some UE versions return MaterialInterface directly
                    mesh_mats.append(entry)
                elif hasattr(entry, "material_interface"):
                    # StaticMaterial struct (most UE5 versions)
                    mesh_mats.append(entry.material_interface)
                else:
                    mesh_mats.append(None)
    except Exception:
        pass

    n = max(len(overrides), len(mesh_mats))
    for i in range(n):
        mat = overrides[i] if i < len(overrides) else None
        if mat is None and i < len(mesh_mats):
            mat = mesh_mats[i]
        if mat is not None:
            yield mat


def _material_root(mat):
    """
    Walk the MaterialInstance parent chain and return the root material path.
    Stops when the parent is not a MaterialInstance (i.e. it is the master
    material) or when the chain is longer than 8 levels (safety cap).
    Returns the clean path of the highest ancestor found.
    """
    current = mat
    path    = _clean_path(mat.get_path_name())
    for _ in range(8):
        if not isinstance(current, unreal.MaterialInstance):
            break
        try:
            parent = current.get_editor_property("parent")
            if parent is None:
                break
            path    = _clean_path(parent.get_path_name())
            current = parent
        except Exception:
            break
    return path


def _material_matches(component, target_path):
    """
    Return True when any effective material slot on this component shares
    the same material family as target_path.

    Matching rules (checked in order, most to least specific):
      1. Exact path match (fastest — catches the most common case).
      2. The slot material's direct parent is target_path (child instance).
      3. The slot material and target_path share the same root master material.
         This catches sibling instances (MI_Grass_A and MI_Grass_B both derived
         from MM_Grass) so the user only needs to pick one grass instance and
         ALL grass patches in the scene are found automatically.
    """
    target      = _clean_path(target_path)
    target_root = None   # computed lazily

    for mat in _effective_materials(component):
        mat_path = _clean_path(mat.get_path_name())

        # Rule 1 — exact match
        if mat_path == target:
            return True

        if isinstance(mat, unreal.MaterialInstance):
            # Rule 2 — direct parent is target
            try:
                parent = mat.get_editor_property("parent")
                if parent and _clean_path(parent.get_path_name()) == target:
                    return True
            except Exception:
                pass

            # Rule 3 — shared root master material
            if target_root is None:
                # Lazily compute root of the target material
                try:
                    t = unreal.load_asset(target_path)
                    target_root = _material_root(t) if t else target
                except Exception:
                    target_root = target

            if _material_root(mat) == target_root:
                return True

    return False


def _find_matching_actors(world, material_path):
    """
    Return [(actor, comp)] for every actor that should receive foliage.

    STEP 1 — Material scan (primary):
      Find all actors whose StaticMeshComponent uses the target material or
      any instance sharing the same master material (parent-chain matching).
      Comma-separated paths are supported so multiple grass materials can be
      targeted in one run.

    STEP 2 — Z-level companion scan (automatic):
      After the material scan, find additional FLAT actors sitting at the same
      ground Z level as the already-found surfaces.  These are companion grass
      patches that use a different material (e.g. a different grass colour for
      inner courtyards vs. outer border strips).  Criteria:
        • Thin vertical extent (half-height < 30 cm) — flat ground mesh
        • Top surface within 40 cm of the average top-Z of matched actors
        • Not already in the result set
      This is why center courtyard patches were empty even though they were
      visually identical grass — they just had a different material assigned.
    """
    editor_subs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    mat_paths   = [p.strip() for p in material_path.split(",") if p.strip()]

    result    = []
    found_ids = set()
    n_total   = 0

    # ── Step 1: material scan ─────────────────────────────────────────────────
    for actor in editor_subs.get_all_level_actors():
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp is None:
            continue
        n_total += 1
        if any(_material_matches(comp, mp) for mp in mat_paths):
            result.append((actor, comp))
            found_ids.add(id(actor))

    print(f"[Foliage] Material scan: {n_total} actors checked → {len(result)} matched")

    # ── Step 2: Z-level companion scan ────────────────────────────────────────
    if result:
        # Collect the top-Z of each matched surface patch
        ref_top_zs = []
        for actor, comp in result:
            try:
                origin, extent = actor.get_actor_bounds(False)
                ref_top_zs.append(origin.z + extent.z)
            except Exception:
                pass

        if ref_top_zs:
            avg_top_z  = sum(ref_top_zs) / len(ref_top_zs)
            z_tol      = 40.0      # cm — surfaces within 40 cm of avg grass top
            flat_limit = 30.0      # cm — half-height threshold for "flat" actor

            n_companion = 0
            for actor in editor_subs.get_all_level_actors():
                if id(actor) in found_ids:
                    continue
                comp = actor.get_component_by_class(unreal.StaticMeshComponent)
                if comp is None:
                    continue
                try:
                    origin, extent = actor.get_actor_bounds(False)
                    top_z = origin.z + extent.z
                    # Flat actor (thin ground mesh) at the same Z level
                    if extent.z < flat_limit and abs(top_z - avg_top_z) < z_tol:
                        result.append((actor, comp))
                        found_ids.add(id(actor))
                        n_companion += 1
                except Exception:
                    pass

            if n_companion:
                print(f"[Foliage] Z-companion scan: +{n_companion} flat actor(s) "
                      f"at Z≈{avg_top_z/100:.1f} m (different material, same ground level)")

    print(f"[Foliage] Total surfaces to plant: {len(result)}")
    return result


def _probe_effective_width(world, px0, px1, py0, py1, ptop, pz_lo, pz_hi,
                           pactor, material_path):
    """
    Measure the maximum contiguous grass width perpendicular to the patch's
    long axis using cross-section traces.

    WHY THIS IS NEEDED:
      A grass strip that runs along 3 sides of a building has a bounding box
      that covers the entire building footprint (e.g. 40m × 30m).  The bbox
      short-side is 30m → LARGE_TREE is selected.  But the actual grass is
      only 2m wide.  This probe fires cross-section traces to find the real
      contiguous grass width, correctly classifying the strip as SHRUB-only.

    Algorithm:
      • Identify the long axis (X or Y).
      • Fire N_CROSS evenly-spaced cross-sections perpendicular to the long axis.
      • For each cross-section, count the maximum run of consecutive trace hits.
      • Return the longest hit-run × sample step = effective grass width.
      • Falls back to bbox short-side if no traces hit (avoids skipping the patch).

    3 cross-sections × 6 samples = 18 traces per patch — fast enough for 50+ patches.
    """
    W, H   = px1 - px0, py1 - py0
    N_CROSS, N_SAMPLE = 3, 6
    max_width = 0

    if W >= H:
        step_long  = W / N_CROSS
        step_short = H / N_SAMPLE
        for i in range(N_CROSS):
            x = px0 + step_long * (i + 0.5)
            run = best = 0
            for j in range(N_SAMPLE):
                y = py0 + step_short * (j + 0.5)
                if _trace(world, x, y, ptop, pz_lo, pz_hi,
                          source_actor=pactor, material_path=material_path):
                    run += 1; best = max(best, run)
                else:
                    run = 0
            max_width = max(max_width, best * step_short)
    else:
        step_long  = H / N_CROSS
        step_short = W / N_SAMPLE
        for j in range(N_CROSS):
            y = py0 + step_long * (j + 0.5)
            run = best = 0
            for i in range(N_SAMPLE):
                x = px0 + step_short * (i + 0.5)
                if _trace(world, x, y, ptop, pz_lo, pz_hi,
                          source_actor=pactor, material_path=material_path):
                    run += 1; best = max(best, run)
                else:
                    run = 0
            max_width = max(max_width, best * step_short)

    return max_width if max_width > 0 else min(W, H)


def _patches_for_surface(actor, comp):
    """
    Yield (x0, x1, y0, y1, top_z, z_lo, z_hi, actor) for every discrete
    surface patch to cover.

    • InstancedStaticMeshComponent (HISM / HISMA): one patch per instance,
      each computed from the instance world transform + mesh local bounds.
      This prevents the single actor's full-park AABB being used as the grid.
    • Regular StaticMeshComponent: one patch from the actor AABB.
    """
    if isinstance(comp, unreal.InstancedStaticMeshComponent):
        count = 0
        try:
            count = comp.get_instance_count()
        except Exception:
            pass

        if count > 0:
            # Local bounding box of the mesh asset (used for per-instance extents)
            local_bbox = None
            try:
                sm = comp.get_editor_property("static_mesh")
                if sm:
                    local_bbox = sm.get_bounding_box()
            except Exception:
                pass

            for i in range(count):
                try:
                    t   = comp.get_instance_transform(i, True)   # world space
                    loc = t.translation
                    sc  = t.scale3d

                    if local_bbox:
                        # Scale local half-extents to world space
                        hx = (local_bbox.max.x - local_bbox.min.x) / 2 * max(abs(sc.x), abs(sc.y))
                        hy = (local_bbox.max.y - local_bbox.min.y) / 2 * max(abs(sc.x), abs(sc.y))
                        hz = (local_bbox.max.z - local_bbox.min.z) / 2 * abs(sc.z)
                        cz = loc.z + (local_bbox.min.z + local_bbox.max.z) / 2 * sc.z
                    else:
                        hx = hy = hz = 500.0
                        cz = loc.z

                    top_z = cz + hz
                    yield (loc.x - hx, loc.x + hx,
                           loc.y - hy, loc.y + hy,
                           top_z,
                           cz - hz - 200,   # z_lo
                           top_z + 200,     # z_hi
                           actor)
                except Exception:
                    continue
            return   # all instances yielded

    # Regular (non-instanced) actor — use actor world AABB
    origin, extent = actor.get_actor_bounds(False)
    top_z = origin.z + extent.z
    yield (origin.x - extent.x, origin.x + extent.x,
           origin.y - extent.y, origin.y + extent.y,
           top_z,
           origin.z - extent.z - 200,
           top_z + 200,
           actor)


def _cell_patches_for_surface(actor, comp, world, material_path):
    """
    Subdivide one actor AABB into CELL_SIZE_CM × CELL_SIZE_CM cells.
    Fire a centre-probe in each cell; yield only cells confirmed to contain grass.

    ROOT CAUSE FIX:
      Both grass actors have huge bounding boxes (450 m × 350 m and 230 m × 190 m).
      With 500 candidate points spread uniformly over the bbox, a 15 m courtyard
      (≈ 0.1% of the area) statistically gets 0–1 candidates — never enough to place
      anything.  10 m cells guarantee ≥ 1 cell per distinct grass patch regardless of
      how many separate patches share the same actor.

    InstancedStaticMeshComponent actors still delegate to the per-instance path in
    _patches_for_surface; only regular StaticMeshActors are subdivided here.
    """
    # HISM / instanced: use the existing per-instance path (instances are already small)
    if isinstance(comp, unreal.InstancedStaticMeshComponent):
        yield from _patches_for_surface(actor, comp)
        return

    try:
        origin, extent = actor.get_actor_bounds(False)
    except Exception:
        return

    x0, x1 = origin.x - extent.x, origin.x + extent.x
    y0, y1 = origin.y - extent.y, origin.y + extent.y
    top_z  = origin.z + extent.z
    z_lo   = origin.z - extent.z - 200.0
    z_hi   = top_z + 200.0
    W, H   = x1 - x0, y1 - y0

    # Small actor (≤ 1.5 cells): one patch only — probe the centre
    if W <= CELL_SIZE_CM * 1.5 and H <= CELL_SIZE_CM * 1.5:
        hit = _trace(world, (x0 + x1) * 0.5, (y0 + y1) * 0.5,
                     top_z, z_lo, z_hi,
                     source_actor=actor, material_path=material_path)
        if hit is not None:
            yield (x0, x1, y0, y1, top_z, z_lo, z_hi, actor)
        return

    # Large actor: subdivide into uniform cells
    nx = max(1, int(math.ceil(W / CELL_SIZE_CM)))
    ny = max(1, int(math.ceil(H / CELL_SIZE_CM)))
    cw = W / nx
    ch = H / ny

    for ix in range(nx):
        for iy in range(ny):
            cx0 = x0 + ix * cw
            cx1 = cx0 + cw
            cy0 = y0 + iy * ch
            cy1 = cy0 + ch
            hit = _trace(world,
                         (cx0 + cx1) * 0.5, (cy0 + cy1) * 0.5,
                         top_z, z_lo, z_hi,
                         source_actor=actor, material_path=material_path)
            if hit is not None:
                yield (cx0, cx1, cy0, cy1, top_z, z_lo, z_hi, actor)

# ══════════════════════════════════════════════════════════════════════════════
#  TRACE  — landscape snap with per-point actor-bounds Z filter
# ══════════════════════════════════════════════════════════════════════════════

def _trace(world, x, y, top_z, z_lo, z_hi, source_actor=None, material_path=None):
    """
    Step-through complex-collision downward trace.

    Why step-through:
      A single trace from above hits the FIRST blocking surface — which for a
      compound mesh like a pool/plaza is often the RAILING TOP, not the floor.
      Even though the railing top is horizontal (passes a normal check), it is
      not the intended planting surface.

    Algorithm:
      Descend from top_z+100 toward z_lo in up to MAX_STEPS iterations.
      At each step a single trace fires.  The hit is evaluated against four gates:

        1. Z-range gate   — hit must be inside [z_lo, z_hi].  Hits above z_hi
                            (high railings, rooftops, ceilings) are stepped through.
        2. Normal gate    — impact normal Z ≥ 0.70 (≈ cos 45°).  Rejects walls,
                            vertical fence faces, and steep slopes.
        3. Actor gate     — the hit actor must be the source actor we're planting
                            on.  Rejects fence/bench/bollard actors whose bounding
                            boxes happen to overlap the surface actor's AABB.
        4. Material gate  — the hit component must carry the target material.
                            Rejects railing/fence sections that share the same mesh
                            actor but use a different material slot.

      If a hit fails any gate it is STEPPED THROUGH (start_z moves to 1 cm below
      the hit) and the next iteration tries for a surface further down.

      The first hit that passes ALL four gates is returned as a valid planting
      location.  If no valid surface is found after MAX_STEPS, None is returned
      and that grid point is skipped entirely (no bounding-box fallback).
    """
    MIN_NORMAL_Z = 0.70   # cos(45°) — steeper faces are not plantable
    MAX_STEPS    = 8      # guard against infinite loops in stacked geometry

    start_z = top_z + 100.0

    for _ in range(MAX_STEPS):
        if start_z <= z_lo:
            break
        try:
            hit = unreal.SystemLibrary.line_trace_single(
                world,
                unreal.Vector(x, y, start_z),
                unreal.Vector(x, y, z_lo),
                unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                True,    # trace_complex — test actual mesh triangles
                [], unreal.DrawDebugTrace.NONE, True,
            )
            if hit is None:
                break
            t = hit.to_tuple()
            if not t[0]:
                break    # no blocking hit — nothing more below this point

            hit_z      = t[4].z
            hit_normal = t[7]
            hit_actor  = t[9]
            hit_comp   = t[10]

            # Gate 1 — Z range
            if hit_z > z_hi:
                # Above our window (high railing, roof) — step through
                start_z = hit_z - 1.0
                continue
            if hit_z < z_lo:
                break    # fell below the valid range

            # Gate 2 — Normal (must be mostly upward-facing)
            if hit_normal.z < MIN_NORMAL_Z:
                start_z = hit_z - 1.0
                continue

            # Gate 3 — Actor (must be the surface we're planting on)
            if source_actor is not None and hit_actor != source_actor:
                start_z = hit_z - 1.0
                continue

            # Gate 4 — Material (hit component must carry the target material)
            if source_actor is not None and material_path and hit_comp:
                if not _material_matches(hit_comp, material_path):
                    start_z = hit_z - 1.0
                    continue

            return t[4], t[7]    # ✓ all gates passed — valid planting surface

        except Exception:
            break

    return None    # no valid surface found — skip this grid point

# ══════════════════════════════════════════════════════════════════════════════
#  CANOPY COLLISION  — sphere overlap check before spawning
# ══════════════════════════════════════════════════════════════════════════════

def _canopy_overlaps_scene(world, x, y, ground_z, canopy_radius_cm,
                           ignore_actors=None):
    """
    Return True if a sphere of canopy_radius_cm placed at (x, y) above
    ground_z would overlap any WorldStatic scene object.

    Why sphere, not trace:
      A downward trace only finds the surface below the trunk.  A canopy can
      still clip a wall, overhead beam, pergola, or adjacent structure even
      when the trunk placement is valid.  Sphere overlap catches these cases.

    Centre of the sphere is placed at ground_z + canopy_radius so the bottom
    of the sphere sits at ground level — this covers the full canopy volume
    from trunk base to crown tip.

    Actors in ignore_actors (e.g. the source surface actor) are excluded so
    the ground plane itself does not veto every placement.

    Returns False (allow placement) on any exception so a misconfigured
    collision setup never silently stops all vegetation from spawning.
    """
    try:
        center = unreal.Vector(x, y, ground_z + canopy_radius_cm)
        hits = unreal.SystemLibrary.sphere_overlap_actors(
            world,
            center,
            canopy_radius_cm,
            [unreal.ObjectTypeQuery.OBJECT_TYPE_QUERY1],  # WorldStatic
            None,           # no class filter — check all static meshes
            ignore_actors or [],
        )
        return len(hits) > 0
    except Exception:
        return False

# ══════════════════════════════════════════════════════════════════════════════
#  BUILDING CLEARANCE  — AABB-based, no collision required
# ══════════════════════════════════════════════════════════════════════════════

def _collect_obstacle_aabbs(world, exclude_actors=None):
    """
    Return a list of (min_x, max_x, min_y, max_y) bounding rectangles for
    every StaticMesh actor in the level that is tall enough to be a wall or
    building (vertical half-extent > 150 cm, i.e. total height > 3 m).

    WHY AABB INSTEAD OF TRACES:
      Archviz building meshes typically have Collision Preset = NoCollision
      (no physics at all) because they are render-only assets.  Any approach
      that uses line_trace, sphere_overlap, or sweep will silently pass through
      them.  get_actor_bounds() always returns the mesh's world-space bounding
      box regardless of collision settings, so it is the only reliable method
      for scenes where collision is not set up on buildings.

    exclude_actors: set of actors that are the grass/surface patches — we must
      not count those as obstacles or every trunk location would be rejected.
    """
    exclude_ids = {id(a) for a in (exclude_actors or [])}
    result = []
    try:
        for actor in unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors():
            if id(actor) in exclude_ids:
                continue
            if actor.get_component_by_class(unreal.StaticMeshComponent) is None:
                continue
            try:
                origin, extent = actor.get_actor_bounds(False)
                # Skip thin/flat actors (ground planes, decals, tiny props).
                # 150 cm half-height means the actor is at least 3 m tall —
                # walls, building facades, stairwells, pergola columns, etc.
                if extent.z < 150:
                    continue
                # Store full 3D AABB — Z bounds are used for vertical clearance
                # checks (detecting ceilings, overhangs, balconies above grass).
                result.append((
                    origin.x - extent.x, origin.x + extent.x,
                    origin.y - extent.y, origin.y + extent.y,
                    origin.z - extent.z, origin.z + extent.z,   # z_min, z_max
                ))
            except Exception:
                pass
    except Exception:
        pass
    return result


def _point_clear_of_obstacles(x, y, clearance_cm, obstacle_aabbs):
    """
    Return False if point (x, y) is within clearance_cm of any obstacle AABB wall.
    Accepts 3D AABBs (bx0, bx1, by0, by1, bz0, bz1) — Z bounds are ignored here.

    OUTSIDE the AABB: standard nearest-edge 2D distance.
    INSIDE the AABB: distance from point to nearest XY wall face.
      This handles U-shaped buildings whose AABB covers the interior courtyard —
      a point deep inside the AABB (far from all walls) is allowed.
    """
    for aabb in obstacle_aabbs:
        bx0, bx1, by0, by1 = aabb[0], aabb[1], aabb[2], aabb[3]
        inside_x = bx0 < x < bx1
        inside_y = by0 < y < by1

        if inside_x and inside_y:
            dist_to_wall = min(x - bx0, bx1 - x, y - by0, by1 - y)
            if dist_to_wall < clearance_cm:
                return False
        else:
            cx = max(bx0, min(x, bx1))
            cy = max(by0, min(y, by1))
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy < clearance_cm * clearance_cm:
                return False

    return True


def _point_has_vertical_clearance(x, y, ground_z, required_height_cm, obstacle_aabbs):
    """
    Return False if a true OVERHEAD structure (balcony, pergola, ceiling) blocks
    the vertical growth column above (x, y).

    KEY DISTINCTION — wall vs. overhang:
      A building wall spans ground_z to roof_z.  Its AABB Z-min is at or below
      ground level.  It should NOT be treated as a ceiling — trees grow next to
      walls all the time.

      An overhang (balcony slab, pergola beam, parking canopy) has its AABB
      Z-min well ABOVE the ground.  That is what we want to reject.

    Rule: an AABB is treated as an overhead obstacle only if its BOTTOM (bz0) is
    at least OVERHEAD_MIN_CM above the planting ground — meaning it is a floating
    structure, not a ground-anchored wall.

    OVERHEAD_MIN_CM = 250 cm (2.5 m) — higher than a fence, lower than a typical
    first-floor balcony (≈3 m).  Adjust if your scene has lower canopies.
    """
    OVERHEAD_MIN_CM = 250          # obstacle bottom must be this high above ground
    top_z = ground_z + required_height_cm

    for aabb in obstacle_aabbs:
        bx0, bx1, by0, by1 = aabb[0], aabb[1], aabb[2], aabb[3]
        bz0, bz1 = aabb[4], aabb[5]

        # Only floating structures count — skip ground-anchored walls
        if bz0 < ground_z + OVERHEAD_MIN_CM:
            continue

        # XY: point must be under this structure's footprint
        if not (bx0 < x < bx1 and by0 < y < by1):
            continue

        # Z: the structure must sit below the canopy top (otherwise the tree
        # grows past it and it is not a real obstruction)
        if bz0 < top_z:
            return False   # genuine overhang/ceiling — reject this spot

    return True

# ══════════════════════════════════════════════════════════════════════════════
#  POINT GENERATION  — XY grid from actor bounding box
# ══════════════════════════════════════════════════════════════════════════════

def _grid_points_for_patch(x0, x1, y0, y1, top_z, z_lo, z_hi, actor,
                           spacing, jitter, rng):
    """
    Return candidate (x, y, top_z, z_lo, z_hi, actor) grid points covering
    the XY footprint of a single surface patch.
    """
    cols = max(1, int((x1 - x0) / spacing))
    rows = max(1, int((y1 - y0) / spacing))
    if cols * rows > MAX_POINTS_PER_CATEGORY:
        spacing = spacing * math.sqrt(cols * rows / MAX_POINTS_PER_CATEGORY)

    jr  = spacing * jitter
    pts = []
    x   = x0 + spacing / 2
    while x <= x1:
        y = y0 + spacing / 2
        while y <= y1:
            pts.append((
                x + rng.uniform(-jr, jr),
                y + rng.uniform(-jr, jr),
                top_z, z_lo, z_hi,
                actor,
            ))
            y += spacing
        x += spacing
    return pts

# ══════════════════════════════════════════════════════════════════════════════
#  BORDER ROW HELPERS  — ordered, fence-following planting for narrow strips
# ══════════════════════════════════════════════════════════════════════════════

def _nearest_wall_info(cx, cy, obstacle_aabbs):
    """
    Return (dist_cm, par_x, par_y) for the nearest obstacle wall face.

    par_x / par_y is the unit vector PARALLEL to the nearest wall — used to
    align border rows so they run flush with the fence line rather than at an
    arbitrary angle.

    Algorithm:
      For each obstacle AABB, determine whether (cx, cy) is inside or outside.
      Compute distance to the nearest wall face and the face's parallel direction.
    """
    best_dist = float("inf")
    best_par  = (1.0, 0.0)

    for aabb in obstacle_aabbs:
        bx0, bx1, by0, by1 = aabb[0], aabb[1], aabb[2], aabb[3]
        inside_x = bx0 <= cx <= bx1
        inside_y = by0 <= cy <= by1

        if inside_x and inside_y:
            # Point is inside AABB → distance = distance to nearest wall face
            d_left   = cx - bx0
            d_right  = bx1 - cx
            d_bottom = cy - by0
            d_top    = by1 - cy
            face_dists = [d_left, d_right, d_bottom, d_top]
            pars       = [(0.0, 1.0), (0.0, 1.0), (1.0, 0.0), (1.0, 0.0)]
            i   = face_dists.index(min(face_dists))
            dist = face_dists[i]
            par  = pars[i]
        else:
            # Point is outside AABB → nearest point on AABB boundary
            nx_pt = max(bx0, min(cx, bx1))
            ny_pt = max(by0, min(cy, by1))
            dx = cx - nx_pt
            dy = cy - ny_pt
            dist = math.sqrt(dx * dx + dy * dy)
            # Parallel direction: along whichever axis the nearest face runs
            x_clamped = (cx < bx0 or cx > bx1)
            y_clamped = (cy < by0 or cy > by1)
            if x_clamped and not y_clamped:
                par = (0.0, 1.0)   # wall is a vertical X-face → rows run in Y
            elif y_clamped and not x_clamped:
                par = (1.0, 0.0)   # wall is a horizontal Y-face → rows run in X
            else:
                # Corner: align with the longer wall of the obstacle
                wx = bx1 - bx0
                wy = by1 - by0
                par = (0.0, 1.0) if wx < wy else (1.0, 0.0)

        if dist < best_dist:
            best_dist = dist
            best_par  = par

    return best_dist, best_par


def _border_row_points(cx0, cx1, cy0, cy1, top_z, z_lo, z_hi, actor,
                       par_x, par_y, offset_cm, spacing_cm, n_rows):
    """
    Generate an ordered grid of points inside this cell arranged in straight
    rows parallel to the nearest wall (direction par_x, par_y).

    Returns list of (x, y, top_z, z_lo, z_hi, actor) tuples.
    Each point's list index modulo len(border_sequence) selects which mesh to
    plant — giving the repeating A-B-A-B or A-B-C-A-B-C pattern the user
    configures.

    par_x ≥ par_y  →  wall runs in X  →  rows also run in X, stacked in Y
    par_y > par_x  →  wall runs in Y  →  rows run in Y, stacked in X
    """
    pts = []
    if abs(par_x) >= abs(par_y):
        # Rows run in X direction (parallel to X wall)
        for r in range(n_rows):
            y = cy0 + offset_cm + r * spacing_cm
            if y > cy1 - offset_cm * 0.5:
                break
            x = cx0 + spacing_cm * 0.5
            while x <= cx1:
                pts.append((x, y, top_z, z_lo, z_hi, actor))
                x += spacing_cm
    else:
        # Rows run in Y direction (parallel to Y wall)
        for r in range(n_rows):
            x = cx0 + offset_cm + r * spacing_cm
            if x > cx1 - offset_cm * 0.5:
                break
            y = cy0 + spacing_cm * 0.5
            while y <= cy1:
                pts.append((x, y, top_z, z_lo, z_hi, actor))
                y += spacing_cm
    return pts


# ── Cluster placement ─────────────────────────────────────────────────────────

def _cluster_points_for_patch(x0, x1, y0, y1, top_z, z_lo, z_hi, actor,
                               spacing, rng,
                               plants_per_cluster=4,
                               cluster_radius_cm=None):
    """
    Cluster-based placement for trees: generate loose cluster centres on a
    coarse grid, then scatter N plants around each centre.

    Why clusters (plant_planning.pdf + Israeli courtyard research):
      • Residential courtyards use informal groupings of 3–5 trees, not rows.
      • Clusters create natural dappled shade zones and visual interest.
      • Shrubs are planted in masses/drifts — use _grid_points_for_patch instead
        (high jitter on a fine grid approximates a drift well enough).

    Algorithm:
      1. Cluster centres are placed on a grid with spacing = tree_spacing × 1.8.
         Each centre is then jittered by ±30 % of cluster_spacing for variety.
      2. Around each centre, place 2–plants_per_cluster trees within cluster_radius_cm.
         If cluster_radius_cm is None, defaults to spacing × 0.55 which keeps
         intra-cluster separation at roughly half the inter-cluster distance.
      3. Points outside the patch AABB are discarded (edge patches stay clean).

    plants_per_cluster and cluster_radius_cm are driven by the per-category
    sliders in foliage_settings.py / foliage_config.json["category_settings"].
    """
    cluster_spacing = spacing * 1.8
    cluster_r       = cluster_radius_cm if cluster_radius_cm is not None else spacing * 0.55
    jitter          = cluster_spacing * 0.30

    pts = []
    cx = x0 + cluster_spacing / 2.0
    while cx <= x1 + cluster_spacing / 2.0:
        cy = y0 + cluster_spacing / 2.0
        while cy <= y1 + cluster_spacing / 2.0:
            # Jitter the cluster centre
            ccx = cx + rng.uniform(-jitter, jitter)
            ccy = cy + rng.uniform(-jitter, jitter)

            n = rng.randint(2, max(2, plants_per_cluster))
            for _ in range(n):
                angle = rng.uniform(0.0, 2.0 * math.pi)
                r     = rng.uniform(0.0, cluster_r)
                px    = ccx + r * math.cos(angle)
                py    = ccy + r * math.sin(angle)
                if x0 <= px <= x1 and y0 <= py <= y1:
                    pts.append((px, py, top_z, z_lo, z_hi, actor))

            cy += cluster_spacing
        cx += cluster_spacing
    return pts

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def generate_foliage():
    t0     = time.time()
    widget = _get_running_widget()

    # ── 1. Get config ─────────────────────────────────────────────────────────
    if widget:
        cfg = _read_widget_config(widget)
    else:
        cfg = _load_config() or {}

        # ── Material: always use last_material.txt (most recent pick) ─────────
        try:
            if os.path.exists(LAST_MATERIAL_FILE):
                with open(LAST_MATERIAL_FILE) as f:
                    last_mat = f.read().strip()
                if last_mat:
                    old = cfg.get("material_path", "")
                    if old and old != last_mat:
                        print(f"[Foliage] Material overridden from last_material.txt:")
                        print(f"[Foliage]   was : {old}")
                        print(f"[Foliage]   now : {last_mat}")
                    cfg["material_path"] = last_mat
        except Exception:
            pass

        if not cfg.get("material_path"):
            print("[Foliage] ⚠  No material set.")
            print("          Select a surface actor → run foliage_pick_material.py first.")
            return

        # ── Meshes: prefer Content Browser selection over saved config ────────
        cat_lookup = {}
        for row in cfg.get("mesh_list", []):
            cat_lookup[row[0]] = row[1]

        cb_list = _mesh_list_from_cb_selection(cat_lookup)
        if cb_list:
            cfg["mesh_list"] = [[p, c] for p, c in cb_list]
            print(f"[Foliage] Widget not running — "
                  f"using {len(cb_list)} mesh(es) from Content Browser selection.")
        elif cfg.get("mesh_list"):
            print(f"[Foliage] Widget not running — "
                  f"loaded config from foliage_config.json "
                  f"({len(cfg['mesh_list'])} mesh(es)).")
        else:
            print("[Foliage] ⚠  No meshes found.")
            print("          Select tree/shrub assets in the Content Browser, then re-run.")
            return

        cfg.setdefault("seed", 42)
        cfg.setdefault("mesh_folder", "/Game/")

    if cfg is None:
        return

    # category_settings and canopy_collision are written by foliage_settings.py
    # and live in the JSON independently of the widget/no-widget config path.
    # Always merge them in so slider changes take effect regardless of how
    # the generator was launched.
    _saved = _load_config() or {}
    cfg.setdefault("category_settings",    _saved.get("category_settings",    {}))
    cfg.setdefault("canopy_collision",     _saved.get("canopy_collision",     False))
    cfg.setdefault("building_clearance_cm", _saved.get("building_clearance_cm", 0.0))

    material_path = cfg["material_path"]
    seed          = cfg["seed"]
    mesh_list     = [(row[0], row[1]) for row in cfg["mesh_list"]]

    rng   = random.Random(seed)
    world = unreal.get_editor_subsystem(
        unreal.UnrealEditorSubsystem
    ).get_editor_world()

    print(f"\n{'─'*52}")
    print(f"  Foliage Generator")
    print(f"  Material : {material_path}")
    print(f"  Meshes   : {len(mesh_list)}")
    print(f"  Seed     : {seed}")
    print(f"{'─'*52}")
    _set_status(f"Scanning…\nMaterial: {material_path}\nMeshes: {len(mesh_list)}", widget)

    # ── 2. Find surface actors ────────────────────────────────────────────────
    matching = _find_matching_actors(world, material_path)
    if not matching:
        _set_status(
            f"⚠  No actors found using:\n{material_path}\n\n"
            "Pick material again or check the path.", widget
        )
        return
    # Subdivide each actor into 10 m cells; probe each cell centre to confirm grass.
    # This fixes the root cause: huge actors (450 m bbox) previously spread 500 points
    # across the entire area, statistically missing small courtyards (15 m = 0.1%).
    # Each confirmed cell becomes an independent planting patch.
    all_patches = []
    for actor, comp in matching:
        for patch in _cell_patches_for_surface(actor, comp, world, material_path):
            all_patches.append(patch)
    print(f"[Foliage] {len(matching)} matching actor(s) → {len(all_patches)} confirmed grass cell(s).")

    # ── 3. Load all meshes, measure canopy diameters, group by category ──────
    #
    # Category assignment order:
    #   a) Explicit category from config/widget (user override).
    #   b) Auto-detect from bounding-box diameter (National Guide Section 5.1).
    #
    # active_categories filter: set in foliage_config.json or CategoriesInput widget.

    active_cats = set()
    if cfg.get("active_categories"):
        active_cats = {c.strip().upper() for c in cfg["active_categories"] if c.strip()}
    if widget:
        raw = _widget_text(widget, "CategoriesInput", "")
        if raw:
            active_cats = {c.strip().upper() for c in raw.split(",") if c.strip()}

    # Load assets + measure canopy diameters
    loaded_meshes   = {}   # sm_path → StaticMesh asset
    canopy_diameter = {}   # sm_path → diameter in cm
    by_category     = {}   # category → [sm_path, ...]

    for sm_path, explicit_cat in mesh_list:
        m = unreal.load_asset(sm_path)
        if m is None:
            print(f"[Foliage]   ⚠ Could not load: {sm_path.split('/')[-1]}")
            continue
        m = _extract_static_mesh(m)          # unwrap FoliageType if needed
        if m is None:
            print(f"[Foliage]   ⚠ Not a StaticMesh (or FoliageType with no mesh): {sm_path.split('/')[-1]}")
            continue
        loaded_meshes[sm_path] = m

        d = _canopy_diameter_cm(m)
        canopy_diameter[sm_path] = d

        # Auto-detect category from diameter if not explicitly set
        if explicit_cat.upper() == "AUTO":
            cat = _classify_by_diameter(d)
        else:
            cat = explicit_cat.upper()

        if active_cats and cat not in active_cats:
            continue

        by_category.setdefault(cat, []).append(sm_path)

    if not by_category:
        _set_status(
            "⚠  No mesh categories to place.\n"
            "Select meshes in the Content Browser, or check foliage_config.json.\n"
            f"Available categories: {', '.join(sorted(CATEGORY_RULES.keys()))}",
            widget
        )
        return

    # Log what was detected
    print(f"[Foliage] Detected categories:")
    for cat in ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]:
        paths = by_category.get(cat, [])
        if paths:
            diams = [canopy_diameter[p] for p in paths]
            avg_d = sum(diams) / len(diams)
            spacing = _spacing_for_coverage(avg_d, category=cat)
            mode = "cluster" if cat in ("LARGE_TREE", "MEDIUM_TREE") else "grid"
            print(f"[Foliage]   {cat}: {len(paths)} mesh(es), "
                  f"avg canopy {avg_d/100:.1f} m, "
                  f"spacing {spacing/100:.1f} m [{mode}]")

    available_cats = set(by_category.keys())

    # ── Per-category settings from foliage_settings.py / config JSON ─────────
    # Written by the settings UI, consumed here.  Each key overrides the
    # auto-computed default so the sliders are live without touching this file.
    cat_settings_all   = cfg.get("category_settings", {})
    do_canopy_check    = cfg.get("canopy_collision", False)
    building_clearance = float(cfg.get("building_clearance_cm", 0.0))

    # ── Garden design config (written by foliage_settings.py Garden Design tab) ─
    _gd              = cfg.get("garden_design", {})
    gd_enabled       = bool(_gd.get("enabled", False))
    gd_border_width  = float(_gd.get("border_width_cm",   300.0))
    gd_border_offset = float(_gd.get("border_offset_cm",   40.0))
    gd_border_spacing= float(_gd.get("border_spacing_cm", 150.0))
    gd_border_rows   = max(1, int(_gd.get("border_rows", 1)))
    gd_sequence_paths= [p.strip() for p in _gd.get("border_sequence", []) if str(p).strip()]

    # Load border sequence meshes (order preserved — cycling A-B-A-B in rows)
    border_mesh_map  = {}   # path → StaticMesh
    border_sequence  = []   # ordered list of paths (may repeat)
    if gd_enabled and gd_sequence_paths:
        for p in gd_sequence_paths:
            m = unreal.load_asset(p)
            if m is None:
                print(f"[Foliage] ⚠ Border sequence: could not load '{p.split('/')[-1]}'")
                continue
            m = _extract_static_mesh(m)      # unwrap FoliageType if needed
            if m is None:
                print(f"[Foliage] ⚠ Border sequence: not a StaticMesh: '{p.split('/')[-1]}'")
                continue
            border_mesh_map[p] = m
            border_sequence.append(p)
        if border_sequence:
            print(f"[Foliage] Garden design: border rows ON — "
                  f"{len(border_sequence)}-step sequence, "
                  f"spacing {gd_border_spacing/100:.1f} m, "
                  f"width {gd_border_width/100:.1f} m, "
                  f"{gd_border_rows} row(s)")
        else:
            print("[Foliage] Garden design: enabled but no valid border meshes — "
                  "fill in the Border Sequence in foliage_settings.py")
            gd_enabled = False

    # Confirm active filters so misconfiguration is immediately visible in the log
    _filters = []
    if do_canopy_check:
        _filters.append("canopy-sphere")
    if building_clearance > 0:
        _filters.append(f"building-clearance {building_clearance/100:.1f} m (AABB)")
    print(f"[Foliage] Active filters: {', '.join(_filters) or 'none'}")

    # Pre-compute per-category base clearances.
    # When building_clearance > 0, enforce a minimum of ½ the average canopy diameter
    # so that large trees (e.g. 13 m canopy) are always kept ≥6.5 m from any wall —
    # even if the user configured a smaller value like 3 m.
    # This prevents the clearance rays from being too short to ever reach building walls.
    # Pre-collect obstacle AABBs once for the entire run.
    # Uses get_actor_bounds() — works even when buildings have NoCollision.
    # Excludes source grass actors so the planting surface doesn't self-block.
    # Always collected — needed for both building clearance AND garden border detection.
    cat_base_clearance = {}
    source_actors  = {actor for actor, comp in matching}
    obstacle_aabbs = _collect_obstacle_aabbs(world, exclude_actors=source_actors)
    print(f"[Foliage] Obstacles: {len(obstacle_aabbs)} tall actor(s) found "
          f"(AABB scan — no collision required)")
    if building_clearance > 0:
        print(f"[Foliage] Building clearance: {building_clearance/100:.1f} m from any wall")

    editor_subs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    total             = 0
    skipped_canopy    = 0
    skipped_clearance = 0
    lines = [f"Material: {material_path}", f"Seed: {seed}", ""]
    placed_by_cat   = {}   # category → count
    # Per-patch diagnostics: generated / trace-miss / canopy-skip / clearance-skip / placed
    diag_gen = diag_trace = diag_canopy = diag_clr = diag_placed = 0

    # ── 4. Place foliage — all categories per patch ───────────────────────────
    #
    # Every patch runs ALL available categories (large → small), each at its
    # own spacing.  A minimum patch area per category prevents, e.g., putting
    # a 16 m canopy tree in a 5 m² planter.
    #
    # Placement order: LARGE_TREE first so trees claim their space, then
    # MEDIUM_TREE, SMALL_TREE, SHRUB fill the remaining gaps.  The canopy
    # collision check (if enabled) prevents smaller plants from spawning
    # inside already-placed tree canopies.

    # Minimum patch area (m²) AND minimum short-side width (cm) per category.
    #
    # Area alone is not enough: a 2 m × 100 m strip = 200 m² would qualify
    # for LARGE_TREE by area, but a 16 m canopy tree physically cannot fit in a
    # 2 m wide border.  The short-side check prevents this:
    #   short_side = min(patch_width, patch_height)
    #   if short_side < CAT_MIN_SHORT_CM → skip this category for this patch
    #
    # Narrow strips (building borders, fence lines) therefore only receive
    # SHRUB, which fits in 1.5–3 m of width and lines up naturally near fences.
    CAT_MIN_AREA_M2 = {
        "LARGE_TREE":  30,    # at least ~5×6 m — clearance + traces handle the rest
        "MEDIUM_TREE": 10,
        "SMALL_TREE":  4,
        "SHRUB":       0.5,
    }
    # Short-side gate: prevents large trees in narrow strips regardless of area.
    # A 2 m × 100 m strip = 200 m² area but short-side = 200 cm → only SHRUB.
    # Trees may overhang walls so canopy > short-side is intentionally allowed.
    CAT_MIN_SHORT_CM = {
        "LARGE_TREE":  700,   # ≥7 m wide — avoids planting 16 m trees in 2 m borders
        "MEDIUM_TREE": 400,   # ≥4 m wide
        "SMALL_TREE":  200,   # ≥2 m wide
        "SHRUB":       50,    # ≥50 cm wide
    }
    PLACEMENT_ORDER = ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]

    # ── Shared spawn helper ───────────────────────────────────────────────────
    def _spawn(mesh, loc, yaw, scale_val, z_off, src_actor):
        """Spawn one StaticMeshActor, snap bottom to surface, apply Z offset."""
        nonlocal total, diag_placed
        s = scale_val
        a = editor_subs.spawn_actor_from_class(
            unreal.StaticMeshActor,
            unreal.Vector(loc.x, loc.y, loc.z),
            unreal.Rotator(pitch=0.0, yaw=yaw, roll=0.0),
        )
        if a is None:
            return
        smc = a.get_component_by_class(unreal.StaticMeshComponent)
        if smc is not None:
            smc.set_editor_property("static_mesh", mesh)
        a.set_actor_scale3d(unreal.Vector(s, s, s))
        final_z = loc.z
        try:
            bb = mesh.get_bounding_box()
            lb = bb.min.z * s
            if abs(lb) > 0.5:
                final_z = loc.z - lb
        except Exception:
            pass
        final_z += z_off
        a.set_actor_location(unreal.Vector(loc.x, loc.y, final_z), False, False)
        diag_placed += 1
        total += 1

    border_placed = 0   # track border-row placements separately

    with unreal.ScopedEditorTransaction("Foliage Generator"):
        for (px0, px1, py0, py1, ptop, pz_lo, pz_hi, pactor) in all_patches:

            cell_w        = px1 - px0
            cell_h        = py1 - py0
            actual_short_cm = min(cell_w, cell_h)   # cells are already small — no probe needed
            actual_area_m2  = cell_w * cell_h / 10_000.0
            cell_cx         = (px0 + px1) * 0.5
            cell_cy         = (py0 + py1) * 0.5

            # ── Classify cell: BORDER vs INTERIOR ─────────────────────────────
            # Border cells are within gd_border_width of a building wall.
            # They receive ordered fence-following rows from the user sequence.
            # Interior cells receive naturalistic cluster/grid planting.
            is_border = False
            border_par = (1.0, 0.0)
            if gd_enabled and border_sequence and obstacle_aabbs:
                wall_dist, border_par = _nearest_wall_info(cell_cx, cell_cy,
                                                            obstacle_aabbs)
                is_border = wall_dist < gd_border_width

            # ══════════════════════════════════════════════════════════════════
            #  BORDER ROW BRANCH — ordered, fence-parallel planting
            # ══════════════════════════════════════════════════════════════════
            if is_border:
                row_pts = _border_row_points(
                    px0, px1, py0, py1, ptop, pz_lo, pz_hi, pactor,
                    border_par[0], border_par[1],
                    gd_border_offset, gd_border_spacing, gd_border_rows,
                )
                diag_gen += len(row_pts)
                for idx, (bx, by, bz, bz_lo, bz_hi, bactor) in enumerate(row_pts):
                    hit = _trace(world, bx, by, bz, bz_lo, bz_hi,
                                 source_actor=bactor, material_path=material_path)
                    if hit is None:
                        diag_trace += 1
                        continue
                    loc, _ = hit
                    # Cycle through user sequence A-B-C-A-B-C…
                    sm_path = border_sequence[idx % len(border_sequence)]
                    mesh    = border_mesh_map.get(sm_path)
                    if mesh is None:
                        continue
                    # Orderly look: tight scale (±5%) and minimal yaw variation (±8°)
                    s   = rng.uniform(0.95, 1.05)
                    yaw = rng.uniform(-8.0, 8.0)
                    _spawn(mesh, loc, yaw, s, 0.0, bactor)
                    border_placed += 1
                continue   # border cells do NOT also get interior planting

            # ══════════════════════════════════════════════════════════════════
            #  INTERIOR BRANCH — multi-category naturalistic planting
            # ══════════════════════════════════════════════════════════════════
            for cat in PLACEMENT_ORDER:
                if cat not in by_category:
                    continue
                if actual_area_m2 < CAT_MIN_AREA_M2.get(cat, 0):
                    continue
                if actual_short_cm < CAT_MIN_SHORT_CM.get(cat, 0):
                    continue

                paths_in_cat = by_category[cat]
                rules        = CATEGORY_RULES.get(cat, CATEGORY_RULES["MEDIUM_TREE"])
                diams        = [canopy_diameter[p] for p in paths_in_cat]
                avg_d        = sum(diams) / len(diams)
                scale        = rules["scale"]

                cs               = cat_settings_all.get(cat, {})
                spacing_override = cs.get("spacing_cm")
                spacing = (float(spacing_override) if spacing_override
                           else _spacing_for_coverage(avg_d, category=cat))
                cluster_count  = int(cs.get("cluster_count",
                                            4 if cat in ("LARGE_TREE", "MEDIUM_TREE") else 1))
                cluster_radius = (float(cs["cluster_radius_cm"])
                                  if cs.get("cluster_radius_cm") is not None else None)
                z_offset_cm = float(cs.get("z_offset_cm", 0.0))
                jitter      = rules["jitter"]

                # Narrow cell (< 2× spacing): neat row with low jitter
                is_narrow = actual_short_cm < spacing * 2
                if is_narrow:
                    pts = _grid_points_for_patch(
                        px0, px1, py0, py1, ptop, pz_lo, pz_hi, pactor,
                        spacing, min(jitter, 0.10), rng,
                    )
                elif cluster_count >= 2:
                    pts = _cluster_points_for_patch(
                        px0, px1, py0, py1, ptop, pz_lo, pz_hi, pactor,
                        spacing, rng,
                        plants_per_cluster=cluster_count,
                        cluster_radius_cm=cluster_radius,
                    )
                else:
                    pts = _grid_points_for_patch(
                        px0, px1, py0, py1, ptop, pz_lo, pz_hi, pactor,
                        spacing, jitter, rng,
                    )

                if len(pts) > MAX_POINTS_PER_CATEGORY:
                    rng.shuffle(pts)
                    pts = pts[:MAX_POINTS_PER_CATEGORY]

                diag_gen += len(pts)

                for (cx, cy, cz, z_lo, z_hi, src_actor) in pts:
                    result = _trace(world, cx, cy, cz, z_lo, z_hi,
                                    source_actor=src_actor,
                                    material_path=material_path)
                    if result is None:
                        diag_trace += 1
                        continue

                    loc, normal = result

                    # Canopy collision check (sphere overlap)
                    if do_canopy_check and avg_d > 0:
                        if _canopy_overlaps_scene(world, loc.x, loc.y, loc.z,
                                                   avg_d / 2.0, [src_actor]):
                            skipped_canopy += 1
                            diag_canopy += 1
                            continue

                    # Building clearance (per-category AABB check)
                    if building_clearance > 0 and obstacle_aabbs:
                        cat_clr = {
                            "LARGE_TREE":  building_clearance,
                            "MEDIUM_TREE": building_clearance,
                            "SMALL_TREE":  building_clearance * 0.5,
                            "SHRUB":       0.0,
                        }.get(cat, building_clearance)
                        if cat_clr > 0 and not _point_clear_of_obstacles(
                            loc.x, loc.y, cat_clr, obstacle_aabbs
                        ):
                            skipped_clearance += 1
                            diag_clr += 1
                            continue

                    # Vertical clearance (rejects spots under overhangs/pergolas)
                    if obstacle_aabbs and avg_d > 0:
                        if not _point_has_vertical_clearance(
                            loc.x, loc.y, loc.z, avg_d, obstacle_aabbs
                        ):
                            diag_clr += 1
                            continue

                    sm_path = rng.choice(paths_in_cat)
                    mesh    = loaded_meshes[sm_path]
                    s       = rng.uniform(*scale)
                    yaw     = rng.uniform(0.0, 360.0)
                    _spawn(mesh, loc, yaw, s, z_offset_cm, src_actor)
                    placed_by_cat[cat] = placed_by_cat.get(cat, 0) + 1

    # ── Placement diagnostics ─────────────────────────────────────────────────
    print(f"[Foliage] Points: {diag_gen} generated  "
          f"| {diag_trace} trace-miss  "
          f"| {diag_canopy} canopy-blocked  "
          f"| {diag_clr} clearance-blocked  "
          f"| {diag_placed} placed")
    if diag_gen > 0 and diag_placed == 0:
        if diag_trace == diag_gen:
            print("[Foliage] ⚠  All points failed the surface trace.")
            print("          Check that the material path is correct and the surface")
            print("          has complex collision enabled.")
        elif diag_clr == diag_gen - diag_trace:
            print(f"[Foliage] ⚠  Building clearance rejected every point.")
            print(f"          Configured: {building_clearance/100:.1f} m — may have been "
                  f"auto-raised to ½ canopy diameter per category (see log above).")
            print("          Reduce 'Building clearance' in foliage_settings.py "
                  "or increase canopy in a narrower courtyard.")
        elif diag_canopy == diag_gen - diag_trace:
            print("[Foliage] ⚠  Canopy collision rejected every point.")
            print("          Disable 'Canopy collision check' in foliage_settings.py")

    # ── 5. Summary ────────────────────────────────────────────────────────────
    if border_placed:
        border_names = " → ".join(p.split("/")[-1] for p in border_sequence[:4])
        if len(border_sequence) > 4:
            border_names += f" … (+{len(border_sequence)-4})"
        line = f"✓ BORDER ROWS [{border_names}] → {border_placed} instances"
        print(f"[Foliage]   {line}")
        lines.append(line)

    for cat in ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]:
        n = placed_by_cat.get(cat, 0)
        if n or cat in by_category:
            paths = by_category.get(cat, [])
            diams = [canopy_diameter[p] for p in paths] if paths else []
            avg_d = sum(diams) / len(diams) if diams else 0
            spacing = _spacing_for_coverage(avg_d, category=cat) if avg_d else 0
            line = (f"✓ {cat} ({len(paths)} mesh{'es' if len(paths)!=1 else ''}, "
                    f"canopy ~{avg_d/100:.1f} m, "
                    f"spacing ~{spacing/100:.1f} m) → {n} instances")
            print(f"[Foliage]   {line}")
            lines.append(line)

    elapsed = time.time() - t0
    summary = f"\n✓ Done — {total} instances in {elapsed:.1f}s"
    print(f"[Foliage] {summary}")
    lines.append(summary)
    _set_status("\n".join(lines), widget)


generate_foliage()
