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
    "LARGE_TREE":  {"spacing": 1250, "jitter": 0.20, "scale": (0.90, 1.10), "align_normal": False},
    "MEDIUM_TREE": {"spacing":  850, "jitter": 0.20, "scale": (0.85, 1.15), "align_normal": False},
    "SMALL_TREE":  {"spacing":  550, "jitter": 0.20, "scale": (0.80, 1.20), "align_normal": True},
    "SHRUB":       {"spacing":  225, "jitter": 0.25, "scale": (0.70, 1.30), "align_normal": True},
}

MAX_POINTS_PER_CATEGORY = 500   # hard cap on total spawned actors per category

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

def _guess_category(name):
    """Fallback category from mesh/asset name when not in config."""
    n = name.upper()
    # Ground-cover and low vegetation first (broad keyword set)
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
    cat_lookup: dict {sm_path: category} from the saved JSON config.
    Returns [] if nothing relevant is selected.
    """
    try:
        selected = unreal.EditorUtilityLibrary.get_selected_assets()
    except Exception:
        return []

    result = []
    for asset in selected:
        sm_path = None
        name    = ""
        if isinstance(asset, unreal.StaticMesh):
            p = asset.get_path_name()
            sm_path = p.rsplit(".", 1)[0] if "." in p else p
            name    = asset.get_name()
        elif isinstance(asset, unreal.FoliageType_InstancedStaticMesh):
            try:
                mesh = asset.get_editor_property("mesh")
                if mesh:
                    p       = mesh.get_path_name()
                    sm_path = p.rsplit(".", 1)[0] if "." in p else p
                    name    = mesh.get_name()
            except Exception:
                pass
        if sm_path:
            category = cat_lookup.get(sm_path, _guess_category(name))
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

    cfg = {
        "material_path": material_path,
        "seed":          seed,
        "mesh_folder":   mesh_folder,
        "mesh_list":     [[p, c] for p, c in mesh_list],
    }
    _save_config(cfg)
    return cfg

# ══════════════════════════════════════════════════════════════════════════════
#  SURFACE MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def _material_matches(component, target_path):
    target = target_path
    if "." in target:
        target = target.rsplit(".", 1)[0]
    target = target.rstrip("_C")
    try:
        mats = component.get_materials()
    except Exception:
        return False
    for mat in mats:
        if mat is None:
            continue
        # Walk instance chain to base
        current = mat
        for _ in range(8):
            p = current.get_path_name()
            if "." in p:
                p = p.rsplit(".", 1)[0]
            if target in p or p in target:
                return True
            if isinstance(current, unreal.MaterialInstance):
                parent = current.get_editor_property("parent")
                if parent is not None:
                    current = parent
                    continue
            break
    return False


def _find_matching_actors(material_path):
    actors = []
    for actor in unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp and _material_matches(comp, material_path):
            actors.append(actor)
    return actors

# ══════════════════════════════════════════════════════════════════════════════
#  TRACE  — landscape snap with per-point actor-bounds Z filter
# ══════════════════════════════════════════════════════════════════════════════

def _trace(world, x, y, ref_z, z_lo, z_hi, offset=20000):
    """
    Trace straight down from above ref_z against whatever has collision
    (landscape, roads, etc.).  Returns hit Z if the result lands within
    [z_lo, z_hi], else None.

    We rely on the XY already being constrained to a matching actor's bounding
    box footprint (from _grid_points_for_actor), so any hit within the actor's
    Z band is on the correct surface.  No material filter needed — and no
    async collision-cooking required.
    """
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, ref_z + offset),
        unreal.Vector(x, y, ref_z - offset),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False, [], unreal.DrawDebugTrace.NONE, True,
    )
    t = hit.to_tuple()
    if not t[0]:                   # bBlockingHit
        return None
    loc = t[4]                     # Location
    if not (z_lo <= loc.z <= z_hi):
        return None
    return loc, t[7]               # Location, ImpactNormal

# ══════════════════════════════════════════════════════════════════════════════
#  POINT GENERATION  — XY grid from actor bounding box
# ══════════════════════════════════════════════════════════════════════════════

def _grid_points_for_actor(actor, spacing, jitter, rng):
    """
    Return list of (x, y, ref_z, z_lo, z_hi) candidate positions across the
    top face of this actor's AABB.
    z_lo / z_hi are the per-actor Z bounds passed to _trace() so only
    hits at the correct height are accepted (filters underground/elevated
    actors that share the same material).
    """
    origin, extent = actor.get_actor_bounds(False)
    x0, x1 = origin.x - extent.x, origin.x + extent.x
    y0, y1 = origin.y - extent.y, origin.y + extent.y
    top_z  = origin.z + extent.z
    # Accept landscape hits within ±200 cm of the actor's Z extents
    z_lo   = origin.z - extent.z - 200
    z_hi   = origin.z + extent.z + 200

    cols = max(1, int((x1 - x0) / spacing))
    rows = max(1, int((y1 - y0) / spacing))
    if cols * rows > MAX_POINTS_PER_CATEGORY:
        spacing *= math.sqrt(cols * rows / MAX_POINTS_PER_CATEGORY)

    jr  = spacing * jitter
    pts = []
    x   = x0 + spacing / 2
    while x <= x1:
        y = y0 + spacing / 2
        while y <= y1:
            pts.append((
                x + rng.uniform(-jr, jr),
                y + rng.uniform(-jr, jr),
                top_z,
                z_lo,
                z_hi,
            ))
            y += spacing
        x += spacing
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
        cfg = _load_config()
        if cfg:
            print("[Foliage] Widget not running — loaded config from foliage_config.json")
        else:
            print("[Foliage] ⚠  Widget not running and no saved config found.")
            print("          Right-click EUW_FoliageGenerator → Run Editor Utility Widget")
            return

    if cfg is None:
        return

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
    _set_status(f"Running…\nMaterial: {material_path}\nMeshes: {len(mesh_list)}", widget)

    # ── 2. Find surface actors ────────────────────────────────────────────────
    matching = _find_matching_actors(material_path)
    if not matching:
        _set_status(
            f"⚠  No actors found using:\n{material_path}\n\n"
            "Pick material again or check the path.", widget
        )
        return
    print(f"[Foliage] {len(matching)} matching surface actor(s).")

    # ── 3. Group mesh list by category, apply active_categories filter ────────
    by_category = {}
    for sm_path, category in mesh_list:
        by_category.setdefault(category, []).append(sm_path)

    # active_categories: set in foliage_config.json as
    #   "active_categories": ["MEDIUM_TREE", "SHRUB"]
    # Leave empty list or omit to run all categories.
    # Also checked in widget field "CategoriesInput" (comma-separated).
    active_cats = set()
    if cfg.get("active_categories"):
        active_cats = {c.strip().upper() for c in cfg["active_categories"] if c.strip()}
    if widget:
        raw = _widget_text(widget, "CategoriesInput", "")
        if raw:
            active_cats = {c.strip().upper() for c in raw.split(",") if c.strip()}
    if active_cats:
        by_category = {k: v for k, v in by_category.items() if k in active_cats}
        print(f"[Foliage] Category filter: {', '.join(sorted(active_cats))}")

    if not by_category:
        _set_status(
            "⚠  No categories to place.\n"
            "Check active_categories in foliage_config.json or CategoriesInput widget field.\n"
            f"Available: {', '.join(sorted(CATEGORY_RULES.keys()))}",
            widget
        )
        return

    editor_subs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    total = 0
    lines = [f"Material: {material_path}", f"Seed: {seed}", ""]

    # ── 4. Place foliage ──────────────────────────────────────────────────────
    with unreal.ScopedEditorTransaction("Foliage Generator"):
        for category, paths in sorted(by_category.items()):
            rules = CATEGORY_RULES.get(category, CATEGORY_RULES["MEDIUM_TREE"])

            # Pre-load all meshes for this category
            loaded = {}
            for sm_path in paths:
                m = unreal.load_asset(sm_path)
                if m is not None:
                    loaded[sm_path] = m
            valid_paths = list(loaded.keys())
            if not valid_paths:
                lines.append(f"⚠ {category} — no meshes loaded, skipped")
                continue

            # Collect candidate points across all matching surfaces.
            # Each point carries per-actor Z bounds so _trace() can
            # reject landscape hits that belong to the wrong surface.
            all_points = []
            for actor in matching:
                all_points.extend(
                    _grid_points_for_actor(actor, rules["spacing"], rules["jitter"], rng)
                )

            # Cap total per category
            if len(all_points) > MAX_POINTS_PER_CATEGORY:
                rng.shuffle(all_points)
                all_points = all_points[:MAX_POINTS_PER_CATEGORY]

            count  = 0
            misses = 0
            for (cx, cy, cz, z_lo, z_hi) in all_points:
                result = _trace(world, cx, cy, cz, z_lo, z_hi)
                if result is None:
                    misses += 1
                    continue

                    loc, normal = result
                    sm_path = rng.choice(valid_paths)
                    mesh    = loaded[sm_path]
                    s       = rng.uniform(*rules["scale"])
                    yaw     = rng.uniform(0.0, 360.0)

                    placed = editor_subs.spawn_actor_from_class(
                        unreal.StaticMeshActor,
                        unreal.Vector(loc.x, loc.y, loc.z),
                        unreal.Rotator(pitch=0.0, yaw=yaw, roll=0.0),
                    )
                    if placed is None:
                        continue

                    placed_smc = placed.get_component_by_class(unreal.StaticMeshComponent)
                    if placed_smc is not None:
                        placed_smc.set_editor_property("static_mesh", mesh)

                    placed.set_actor_scale3d(unreal.Vector(s, s, s))

                    # Snap bottom of mesh bounds to surface Z.
                    # Many tree/shrub assets have their pivot above or below the
                    # visible mesh base, which causes floating or burying.
                    # After setting the mesh + scale, get the real world bounds and
                    # shift the actor so its bottom face sits exactly on loc.z.
                    try:
                        b_origin, b_extent = placed.get_actor_bounds(False)
                        if b_extent.z > 1.0:
                            bottom_z = b_origin.z - b_extent.z
                            adjustment = loc.z - bottom_z
                            if abs(adjustment) > 0.5:
                                placed.set_actor_location(
                                    unreal.Vector(loc.x, loc.y, loc.z + adjustment),
                                    False, False,
                                )
                    except Exception:
                        pass

                    count += 1

                total += count
                tested = len(all_points)
                if count == 0 and tested > 0:
                    line = (f"⚠ {category} ({len(valid_paths)} meshes) → 0 instances "
                            f"({tested} points tested, all missed surface)")
                    print(f"[Foliage]   {line}")
                    print(f"[Foliage]     Tip: spacing={rules['spacing']}cm — "
                          f"try re-classifying these meshes as SHRUB in foliage_config.json")
                else:
                    line = f"✓ {category} ({len(valid_paths)} meshes) → {count} instances"
                    if misses:
                        line += f"  ({misses} skipped: no hit / out of Z range)"
                    print(f"[Foliage]   {line}")
                lines.append(line)

    elapsed = time.time() - t0
    summary = f"\n✓ Done — {total} instances in {elapsed:.1f}s"
    print(f"[Foliage] {summary}")
    lines.append(summary)
    _set_status("\n".join(lines), widget)


generate_foliage()
