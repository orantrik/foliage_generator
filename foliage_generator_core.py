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
        if saved and saved.get("mesh_list"):
            mesh_list = [(row[0], row[1]) for row in saved["mesh_list"]]
            print(f"[Foliage] FoliageConfig empty — using {len(mesh_list)} mesh(es) from foliage_config.json")
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
                "Edit foliage_config.json: delete non-foliage rows, set categories.\n"
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
#  COLLISION HELPERS  — temporarily enable complex collision so traces hit mesh
# ══════════════════════════════════════════════════════════════════════════════

def _enable_complex_collision(matching):
    """
    For each matching actor, save and then set:
      • component CollisionEnabled → QueryOnly  (so traces can hit it)
      • mesh body_setup flag       → CTF_USE_COMPLEX_AS_SIMPLE  (use render mesh)
    Returns a restore list passed back to _restore_complex_collision().
    Does NOT save assets — changes are in-memory only for this session.
    """
    restore = []
    for actor in matching:
        smc = actor.get_component_by_class(unreal.StaticMeshComponent)
        if not smc:
            restore.append(None)
            continue

        # ── component collision ───────────────────────────────────────────────
        old_ce = None
        try:
            old_ce = smc.get_collision_enabled()
            smc.set_collision_enabled(unreal.CollisionEnabled.QUERY_ONLY)
        except Exception:
            old_ce = None

        # ── mesh body_setup ───────────────────────────────────────────────────
        body     = None
        old_flag = None
        try:
            mesh = smc.get_editor_property("static_mesh")
            if mesh:
                body     = mesh.get_editor_property("body_setup")
                old_flag = body.get_editor_property("collision_trace_flag")
                body.set_editor_property(
                    "collision_trace_flag",
                    unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
                )
        except Exception:
            body = None

        restore.append((smc, old_ce, body, old_flag))
    return restore


def _restore_complex_collision(restore):
    for item in restore:
        if item is None:
            continue
        smc, old_ce, body, old_flag = item
        try:
            if old_ce is not None:
                smc.set_collision_enabled(old_ce)
        except Exception:
            pass
        try:
            if body is not None and old_flag is not None:
                body.set_editor_property("collision_trace_flag", old_flag)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
#  TRACE  — hits the actual selected surface, rejects everything else
# ══════════════════════════════════════════════════════════════════════════════

def _trace(world, x, y, ref_z, material_path, offset=20000):
    """
    Trace straight down from above ref_z.
    Accepts the hit only if the struck component uses material_path.
    Returns (Location, ImpactNormal) or None.
    """
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, ref_z + offset),
        unreal.Vector(x, y, ref_z - offset),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False, [], unreal.DrawDebugTrace.NONE, True,
    )
    t = hit.to_tuple()
    if not t[0]:        # bBlockingHit
        return None
    comp = t[10]        # Component
    if comp is None or not _material_matches(comp, material_path):
        return None
    return t[4], t[7]  # Location, ImpactNormal

# ══════════════════════════════════════════════════════════════════════════════
#  POINT GENERATION  — XY grid from actor bounding box
# ══════════════════════════════════════════════════════════════════════════════

def _grid_points_for_actor(actor, spacing, jitter, rng):
    """
    Return list of (x, y, ref_z) candidate positions across the
    top face of this actor's AABB.  ref_z is used as the trace midpoint.
    """
    origin, extent = actor.get_actor_bounds(False)
    x0, x1 = origin.x - extent.x, origin.x + extent.x
    y0, y1 = origin.y - extent.y, origin.y + extent.y
    top_z  = origin.z + extent.z

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

    # ── 4. Enable mesh collision so traces can hit the selected surfaces ──────
    collision_restore = _enable_complex_collision(matching)

    try:
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

                # Collect candidate XY points across all matching surfaces
                all_points = []
                for actor in matching:
                    all_points.extend(
                        _grid_points_for_actor(actor, rules["spacing"], rules["jitter"], rng)
                    )

                # Cap total per category
                if len(all_points) > MAX_POINTS_PER_CATEGORY:
                    rng.shuffle(all_points)
                    all_points = all_points[:MAX_POINTS_PER_CATEGORY]

                count = 0
                for (cx, cy, cz) in all_points:
                    # Trace hits only the selected material surface — rejects
                    # landscape, dirt, paths, and anything outside the mesh footprint
                    result = _trace(world, cx, cy, cz, material_path)
                    if result is None:
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
                line = f"✓ {category} ({len(valid_paths)} meshes) → {count} instances"
                print(f"[Foliage]   {line}")
                lines.append(line)

    finally:
        # Always restore collision settings, even if an error occurs mid-run
        _restore_complex_collision(collision_restore)

    elapsed = time.time() - t0
    summary = f"\n✓ Done — {total} instances in {elapsed:.1f}s"
    print(f"[Foliage] {summary}")
    lines.append(summary)
    _set_status("\n".join(lines), widget)


generate_foliage()
