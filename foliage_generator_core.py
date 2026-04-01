"""
Foliage Generator Core — Unreal Engine 5
=========================================
Accepts StaticMesh paths directly — no pre-existing FoliageType assets needed.
FoliageType assets are created automatically under /Game/FoliageGenerator/AutoTypes/.

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
AUTO_FT_FOLDER     = "/Game/FoliageGenerator/AutoTypes"

# Config file written next to this script — lets you re-run without widget open
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE         = os.path.join(_THIS_DIR, "foliage_config.json")
LAST_MATERIAL_FILE  = os.path.join(_THIS_DIR, "last_material.txt")

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY RULES  — Israeli National Guide for Shading Trees (2020)
# ══════════════════════════════════════════════════════════════════════════════

CATEGORY_RULES = {
    "LARGE_TREE":  {"spacing": 1250, "jitter": 0.20, "scale": (0.90, 1.10), "align_normal": False},
    "MEDIUM_TREE": {"spacing":  850, "jitter": 0.20, "scale": (0.85, 1.15), "align_normal": False},
    "SMALL_TREE":  {"spacing":  550, "jitter": 0.20, "scale": (0.80, 1.20), "align_normal": True},
    "SHRUB":       {"spacing":  225, "jitter": 0.25, "scale": (0.70, 1.30), "align_normal": True},
}

TRACE_HEIGHT_OFFSET  = 5000
MAX_POINTS_PER_ACTOR = 500   # raise carefully — each point = one line trace

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
    """Get a named child widget — tries direct call then parent-class binding."""
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
#  CONFIG FILE  (written by widget, read as fallback)
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
    """Return all StaticMesh asset paths under folder (no heavy sync load)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    filter_  = unreal.ARFilter(
        class_names        = ["StaticMesh"],
        package_paths      = [folder],
        recursive_paths    = True,
        recursive_classes  = False,
    )
    assets = registry.get_assets(filter_)
    paths  = []
    for a in assets:
        pkg  = str(a.package_path)
        name = str(a.asset_name)
        paths.append(f"{pkg}/{name}")
    return sorted(paths)

# ══════════════════════════════════════════════════════════════════════════════
#  FOLIAGETYPE AUTO-CREATION
# ══════════════════════════════════════════════════════════════════════════════

def _get_or_create_foliage_type(mesh_path):
    """
    Return a FoliageType_InstancedStaticMesh for the given StaticMesh path.
    Creates and saves the asset under AUTO_FT_FOLDER if it doesn't exist yet.
    """
    mesh = unreal.load_asset(mesh_path)
    if mesh is None:
        print(f"[Foliage]   ⚠  StaticMesh not found: {mesh_path}")
        return None

    mesh_name = mesh_path.split("/")[-1]
    ft_name   = f"FT_Auto_{mesh_name}"
    ft_path   = f"{AUTO_FT_FOLDER}/{ft_name}"
    ft_obj    = f"{ft_path}.{ft_name}"

    # Return existing asset if already created
    existing = unreal.find_object(None, ft_obj)
    if existing:
        return existing
    if unreal.EditorAssetLibrary.does_asset_exist(ft_path):
        return unreal.load_object(None, ft_obj)

    # Create new
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    ft = asset_tools.create_asset(
        ft_name, AUTO_FT_FOLDER,
        unreal.FoliageType_InstancedStaticMesh, None
    )
    if ft is None:
        print(f"[Foliage]   ⚠  Could not create FoliageType for {mesh_name}")
        return None

    ft.set_editor_property("mesh", mesh)
    unreal.EditorAssetLibrary.save_asset(ft.get_path_name())
    print(f"[Foliage]   Created FoliageType: {ft_name}")
    return ft

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG PARSING
# ══════════════════════════════════════════════════════════════════════════════

def _parse_mesh_config(text):
    """
    Parse FoliageConfig text box.  Each line:
      /Game/Trees/SM_Oak   LARGE_TREE
    Lines starting with # are skipped.
    Returns list of (sm_path, category) tuples.
    """
    valid = set(CATEGORY_RULES.keys())
    result = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
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
    """
    Read material path, seed, mesh scan folder, and mesh list from widget.
    Returns config dict or None on failure.
    Saves config to JSON file for future fallback use.
    """
    material_path = _widget_text(widget, "MaterialPathInput")

    # Fallback: read from file written by foliage_pick_material.py
    if not material_path:
        try:
            if os.path.exists(LAST_MATERIAL_FILE):
                with open(LAST_MATERIAL_FILE) as f:
                    material_path = f.read().strip()
                if material_path:
                    # Write it back into the widget field so the user can see it
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

    # Mesh scan folder (optional widget field — falls back to /Game/)
    mesh_folder = _widget_text(widget, "MeshFolderInput", "/Game/").rstrip("/") or "/Game/"

    cfg_text  = _widget_text(widget, "FoliageConfig", "")
    mesh_list = _parse_mesh_config(cfg_text)

    if not mesh_list:
        # Check if a previously saved config already has a mesh list
        # (user may have edited foliage_config.json after the first scan)
        saved = _load_config()
        if saved and saved.get("mesh_list"):
            mesh_list = [(row[0], row[1]) for row in saved["mesh_list"]]
            print(f"[Foliage] FoliageConfig widget empty — using {len(mesh_list)} mesh(es) from foliage_config.json")
        else:
            # First run: scan and save for the user to edit, then stop
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

            msg = (
                f"Found {len(paths)} mesh(es). Config saved to:\n"
                f"{CONFIG_FILE}\n\n"
                f"First 8 meshes:\n  {preview}\n\n"
                "Open foliage_config.json in a text editor:\n"
                "  • Delete lines for non-foliage meshes (roads, buildings, etc.)\n"
                "  • Change MEDIUM_TREE → LARGE_TREE / SMALL_TREE / SHRUB\n\n"
                "Then click ▶ Generate Foliage again."
            )
            _set_status(msg, widget)
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
#  PLACEMENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _material_matches(component, target_path):
    target = target_path.rstrip("_C")
    if "." in target:
        target = target.rsplit(".", 1)[0]
    try:
        mats = component.get_materials()
    except Exception:
        return False
    for mat in mats:
        if mat is None:
            continue
        p = mat.get_path_name()
        if "." in p:
            p = p.rsplit(".", 1)[0]
        if target in p or p in target:
            return True
        if hasattr(mat, "parent") and mat.parent:
            pp = mat.parent.get_path_name()
            if "." in pp:
                pp = pp.rsplit(".", 1)[0]
            if target in pp or pp in target:
                return True
    return False


def _find_matching_actors(world, material_path):
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


def _candidate_points(origin, extent, spacing, jitter, rng):
    x0, x1 = origin.x - extent.x, origin.x + extent.x
    y0, y1 = origin.y - extent.y, origin.y + extent.y
    cols = max(1, int((x1 - x0) / spacing))
    rows = max(1, int((y1 - y0) / spacing))
    if cols * rows > MAX_POINTS_PER_ACTOR:
        spacing *= math.sqrt(cols * rows / MAX_POINTS_PER_ACTOR)
    jr = spacing * jitter
    pts = []
    x = x0 + spacing / 2
    while x <= x1:
        y = y0 + spacing / 2
        while y <= y1:
            pts.append((x + rng.uniform(-jr, jr), y + rng.uniform(-jr, jr)))
            y += spacing
        x += spacing
    return pts


def _trace(world, x, y, top_z, material_path):
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        unreal.Vector(x, y, top_z + TRACE_HEIGHT_OFFSET),
        unreal.Vector(x, y, top_z - TRACE_HEIGHT_OFFSET * 2),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False, [], unreal.DrawDebugTrace.NONE, True,
    )
    if not hit:
        return None
    if hit.component is None or not _material_matches(hit.component, material_path):
        return None
    return hit.location, hit.normal


def _make_transform(loc, normal, scale_range, align_normal, rng):
    s = rng.uniform(*scale_range)
    if align_normal:
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, normal.y))))
        roll  = math.degrees(math.atan2(normal.x, normal.z))
        rot   = unreal.Rotator(pitch, 0.0, roll)
    else:
        rot = unreal.Rotator(0.0, rng.uniform(0.0, 360.0), 0.0)
    return unreal.Transform(loc, rot, unreal.Vector(s, s, s))

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
        return   # error already reported inside _read_widget_config

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

    # ── 2. Find surfaces ──────────────────────────────────────────────────────
    matching = _find_matching_actors(world, material_path)
    if not matching:
        _set_status(
            f"⚠  No actors found using:\n{material_path}\n\n"
            "Pick material again or check the path.", widget
        )
        return
    print(f"[Foliage] {len(matching)} matching actor(s).")

    # ── 3. Get foliage actor ──────────────────────────────────────────────────
    try:
        foliage_actor = unreal.InstancedFoliageActor.get_instanced_foliage_actor_for_current_level(
            world, True
        )
    except Exception:
        # Fallback: find existing or let UE create one on first add_instances call
        foliage_actor = None
        for a in unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors():
            if isinstance(a, unreal.InstancedFoliageActor):
                foliage_actor = a
                break

    total = 0
    lines = [f"Material: {material_path}", f"Seed: {seed}", ""]

    # ── 4. Place foliage ──────────────────────────────────────────────────────
    with unreal.ScopedEditorTransaction("Foliage Generator"):
        for sm_path, category in mesh_list:
            ft = _get_or_create_foliage_type(sm_path)
            if ft is None:
                continue

            rules      = CATEGORY_RULES.get(category, CATEGORY_RULES["MEDIUM_TREE"])
            transforms = []

            for actor in matching:
                origin, extent = actor.get_actor_bounds(False)
                top_z = origin.z + extent.z
                for cx, cy in _candidate_points(
                    origin, extent, rules["spacing"], rules["jitter"], rng
                ):
                    hit = _trace(world, cx, cy, top_z, material_path)
                    if hit:
                        transforms.append(
                            _make_transform(hit[0], hit[1], rules["scale"],
                                            rules["align_normal"], rng)
                        )

            label = sm_path.split("/")[-1]
            if transforms and foliage_actor:
                foliage_actor.add_instances(ft, transforms, True)
                line = f"✓ {label} [{category}] → {len(transforms)}"
                total += len(transforms)
            elif transforms:
                line = f"⚠ {label} — foliage actor unavailable, skipped"
            else:
                line = f"–  {label} [{category}] → no hits"

            print(f"[Foliage]   {line}")
            lines.append(line)

    elapsed = time.time() - t0
    summary = f"\n✓ Done — {total} instances in {elapsed:.1f}s"
    print(f"[Foliage] {summary}")
    lines.append(summary)
    _set_status("\n".join(lines), widget)


generate_foliage()
