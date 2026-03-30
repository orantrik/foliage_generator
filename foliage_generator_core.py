"""
Foliage Generator Core — Unreal Engine 5
=========================================
Reads all settings from the running EUW_FoliageGenerator widget (material path,
selected foliage types, categories, seed) and places foliage instances on every
surface in the level that uses that material.

Spacing / density rules follow the Israeli National Guide for Shading Trees (2020).

HOW TO RUN:
  Called automatically by the widget's Generate button.
  Can also be run standalone from Output Log:
    exec(open(r"C:/FoliageGen/foliage_generator_core.py").read())
"""

import unreal
import random
import math
import time

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET ASSET PATH  ── only change if you moved the widget in Content Browser
# ══════════════════════════════════════════════════════════════════════════════

WIDGET_ASSET_PATH = "/Game/FoliageGenerator/EUW_FoliageGenerator"

# ══════════════════════════════════════════════════════════════════════════════
#  STANDALONE FALLBACKS  (used only when no widget is running)
# ══════════════════════════════════════════════════════════════════════════════

FALLBACK_MATERIAL_PATH = "/Game/Materials/M_YourMaterial"
FALLBACK_FOLIAGE_TYPES = []   # populate if running without the widget
FALLBACK_SEED          = 42

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY RULES  ── Israeli National Guide for Shading Trees (2020)
# ══════════════════════════════════════════════════════════════════════════════
#
#  spacing      : average plant-to-plant distance (cm), mid-point of guide range
#  jitter       : random offset as fraction of spacing (natural variation)
#  scale        : (min, max) uniform scale applied per instance
#  align_normal : True  → tilt to match surface normal  (shrubs / groundcover)
#                 False → keep upright with random yaw   (trees)
#
CATEGORY_RULES = {
    # Large trees  (10 m+)  — guide §4.1 table 1 : spacing 10–15 m
    "LARGE_TREE": {
        "spacing":      1250,
        "jitter":       0.20,
        "scale":        (0.90, 1.10),
        "align_normal": False,
    },
    # Medium trees (7–9 m)  — guide §4.1 table 1 : spacing 7–10 m
    "MEDIUM_TREE": {
        "spacing":      850,
        "jitter":       0.20,
        "scale":        (0.85, 1.15),
        "align_normal": False,
    },
    # Small trees  (5–6 m)  — guide §4.1 table 1 : spacing 4–7 m
    "SMALL_TREE": {
        "spacing":      550,
        "jitter":       0.20,
        "scale":        (0.80, 1.20),
        "align_normal": True,
    },
    # Shrubs       (<3 m)   — guide §5.2 : spacing 1.5–3 m
    "SHRUB": {
        "spacing":      225,
        "jitter":       0.25,
        "scale":        (0.70, 1.30),
        "align_normal": True,
    },
}

TRACE_HEIGHT_OFFSET = 5000   # cm above top of actor to start line traces

# ══════════════════════════════════════════════════════════════════════════════
#  READ CONFIG FROM RUNNING WIDGET
# ══════════════════════════════════════════════════════════════════════════════

def _read_widget_config():
    """
    Connect to the running EUW_FoliageGenerator widget and read:
      - material path from MaterialPathInput
      - seed from SeedInput
      - enabled foliage types + categories from each foliage row
    Returns a dict, or None if the widget is not open.
    """
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        widget_asset = unreal.load_object(None, WIDGET_ASSET_PATH)
        if widget_asset is None:
            return None

        widget = subsystem.find_utility_widget_from_blueprint(widget_asset)
        if widget is None:
            return None

        # ── Material path ─────────────────────────────────────────────────
        mat_input = widget.get_widget_from_name("MaterialPathInput")
        material_path = str(mat_input.get_text()) if mat_input else ""
        material_path = material_path.strip()
        if not material_path:
            print("[Foliage] ⚠  Material path is empty — set it in the widget.")
            return None

        # ── Seed ──────────────────────────────────────────────────────────
        seed_input = widget.get_widget_from_name("SeedInput")
        seed = FALLBACK_SEED
        if seed_input:
            try:
                seed = int(str(seed_input.get_text()).strip())
            except ValueError:
                pass

        # ── Foliage types — scan every row in the widget ──────────────────
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        ft_assets = asset_registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Foliage", "FoliageType_InstancedStaticMesh")
        )

        foliage_types = []
        for ft in ft_assets:
            asset_name = str(ft.asset_name)
            safe_name  = asset_name.replace(".", "_").replace("/", "_").replace(" ", "_")

            cb  = widget.get_widget_from_name(f"CB_{safe_name}")
            cat = widget.get_widget_from_name(f"CAT_{safe_name}")

            if cb is None or not cb.get_is_checked():
                continue

            category = cat.get_selected_option() if cat else "MEDIUM_TREE"
            # Build loadable asset path:  /PackagePath/AssetName
            pkg  = str(ft.package_path)
            name = str(ft.asset_name)
            asset_path = f"{pkg}/{name}"
            foliage_types.append((asset_path, category))

        return {
            "material_path": material_path,
            "seed":          seed,
            "foliage_types": foliage_types,
        }

    except Exception as e:
        print(f"[Foliage] Widget read error: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _material_matches(component, target_path):
    """Return True if any material slot on the component matches target_path."""
    target_clean = target_path.rstrip("_C")
    if "." in target_clean:
        target_clean = target_clean.rsplit(".", 1)[0]
    try:
        mats = component.get_materials()
    except Exception:
        return False
    for mat in mats:
        if mat is None:
            continue
        mat_path = mat.get_path_name()
        if "." in mat_path:
            mat_path = mat_path.rsplit(".", 1)[0]
        if target_clean in mat_path or mat_path in target_clean:
            return True
        # Also check material instance parent
        if hasattr(mat, "parent") and mat.parent:
            parent_path = mat.parent.get_path_name()
            if "." in parent_path:
                parent_path = parent_path.rsplit(".", 1)[0]
            if target_clean in parent_path or parent_path in target_clean:
                return True
    return False


def _normal_to_rotator(normal):
    """Surface normal vector → Rotator aligned with that normal."""
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, normal.y))))
    roll  = math.degrees(math.atan2(normal.x, normal.z))
    return unreal.Rotator(pitch, 0.0, roll)


def _find_matching_actors(world, target_material_path):
    matching = []
    for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp and _material_matches(comp, target_material_path):
            matching.append(actor)
    return matching


def _generate_candidate_points(origin, extent, spacing, jitter_frac, rng):
    """Uniform grid with seeded random jitter within actor bounding box."""
    x_min = origin.x - extent.x
    x_max = origin.x + extent.x
    y_min = origin.y - extent.y
    y_max = origin.y + extent.y

    jitter_range = spacing * jitter_frac
    points = []
    x = x_min + spacing / 2.0
    while x <= x_max:
        y = y_min + spacing / 2.0
        while y <= y_max:
            jx = rng.uniform(-jitter_range, jitter_range)
            jy = rng.uniform(-jitter_range, jitter_range)
            points.append((x + jx, y + jy))
            y += spacing
        x += spacing
    return points


def _trace_to_surface(world, x, y, top_z, target_material_path):
    """Line trace downward; return (location, normal) or None."""
    start = unreal.Vector(x, y, top_z + TRACE_HEIGHT_OFFSET)
    end   = unreal.Vector(x, y, top_z - TRACE_HEIGHT_OFFSET * 2)

    hit = unreal.SystemLibrary.line_trace_single(
        world, start, end,
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False, [], unreal.DrawDebugTrace.NONE, True,
    )
    if not hit:
        return None
    comp = hit.component
    if comp is None or not _material_matches(comp, target_material_path):
        return None
    return hit.location, hit.normal


def _build_transform(location, normal, scale_range, align_normal, rng):
    scale_val = rng.uniform(*scale_range)
    if align_normal:
        rotation = _normal_to_rotator(normal)
    else:
        rotation = unreal.Rotator(0.0, rng.uniform(0.0, 360.0), 0.0)
    return unreal.Transform(location, rotation, unreal.Vector(scale_val, scale_val, scale_val))

# ══════════════════════════════════════════════════════════════════════════════
#  UPDATE WIDGET STATUS LOG
# ══════════════════════════════════════════════════════════════════════════════

def _set_widget_status(message):
    """Write message to the widget's StatusLog text box if it's open."""
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        widget_asset = unreal.load_object(None, WIDGET_ASSET_PATH)
        if not widget_asset:
            return
        widget = subsystem.find_utility_widget_from_blueprint(widget_asset)
        if not widget:
            return
        log = widget.get_widget_from_name("StatusLog")
        if log:
            log.set_text(unreal.Text.cast(message))
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def generate_foliage():
    t0 = time.time()

    # ── Read config: widget first, then fallback ──────────────────────────────
    cfg = _read_widget_config()
    if cfg:
        material_path = cfg["material_path"]
        foliage_types = cfg["foliage_types"]
        seed          = cfg["seed"]
        print("[Foliage] Config read from widget.")
    else:
        print("[Foliage] Widget not found — using standalone fallback config.")
        material_path = FALLBACK_MATERIAL_PATH
        foliage_types = FALLBACK_FOLIAGE_TYPES
        seed          = FALLBACK_SEED

    rng   = random.Random(seed)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    header = (
        f"\n{'─'*52}\n"
        f"  Foliage Generator\n"
        f"  Material : {material_path}\n"
        f"  Seed     : {seed}\n"
        f"  Types    : {len(foliage_types)}\n"
        f"{'─'*52}"
    )
    print(header)
    _set_widget_status(f"Running...\nMaterial: {material_path}\nSeed: {seed}")

    if not foliage_types:
        msg = "⚠  No foliage types selected.\nCheck at least one foliage asset in the widget."
        print(f"[Foliage] {msg}")
        _set_widget_status(msg)
        return

    # ── Find matching actors ──────────────────────────────────────────────────
    matching_actors = _find_matching_actors(world, material_path)
    if not matching_actors:
        msg = f"⚠  No actors found using:\n{material_path}\n\nSelect an actor with that material\nand check the path is correct."
        print(f"[Foliage] {msg}")
        _set_widget_status(msg)
        return

    print(f"[Foliage] Found {len(matching_actors)} matching actor(s).")

    # ── Get / create foliage actor ────────────────────────────────────────────
    foliage_actor = unreal.InstancedFoliageActor.get_instanced_foliage_actor_for_current_level(
        world, True
    )

    total_placed = 0
    log_lines    = [f"Material: {material_path}", f"Seed: {seed}", ""]

    with unreal.ScopedEditorTransaction("Foliage Generator — place foliage"):
        for ft_path, category in foliage_types:
            ft_asset = unreal.load_object(None, ft_path)
            if ft_asset is None:
                print(f"[Foliage] ⚠  Could not load: {ft_path}")
                continue

            rules     = CATEGORY_RULES.get(category, CATEGORY_RULES["MEDIUM_TREE"])
            transforms = []

            for actor in matching_actors:
                origin, extent = actor.get_actor_bounds(False)
                top_z = origin.z + extent.z

                for cx, cy in _generate_candidate_points(
                    origin, extent, rules["spacing"], rules["jitter"], rng
                ):
                    result = _trace_to_surface(world, cx, cy, top_z, material_path)
                    if result is None:
                        continue
                    hit_loc, hit_normal = result
                    transforms.append(
                        _build_transform(
                            hit_loc, hit_normal,
                            rules["scale"], rules["align_normal"], rng,
                        )
                    )

            if transforms:
                foliage_actor.add_instances(ft_asset, transforms, True)
                asset_label = ft_path.split("/")[-1]
                line = f"✓ {asset_label} [{category}] → {len(transforms)} instances"
                print(f"[Foliage]   {line}")
                log_lines.append(line)
                total_placed += len(transforms)
            else:
                asset_label = ft_path.split("/")[-1]
                line = f"–  {asset_label} [{category}] → no valid points"
                print(f"[Foliage]   {line}")
                log_lines.append(line)

    elapsed = time.time() - t0
    summary = f"\n✓ Done — {total_placed} instances in {elapsed:.1f}s"
    print(f"[Foliage] {summary}")
    log_lines.append(summary)
    _set_widget_status("\n".join(log_lines))


generate_foliage()
