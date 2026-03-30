"""
Foliage Generator Core — Unreal Engine 5
=========================================
Scans the current level for StaticMesh surfaces that use the target material,
then places foliage instances on those surfaces according to spacing rules
derived from the Israeli National Guide for Shading Trees (2020).

HOW TO USE (standalone):
  In UE5 Output Log → Python:
    exec(open(r"C:/FoliageGen/foliage_generator_core.py").read())

HOW TO USE (from widget):
  The EUW_FoliageGenerator widget calls this file automatically.
  Edit USER CONFIG below before running the widget.
"""

import unreal
import random
import math
import time

# ══════════════════════════════════════════════════════════════════════════════
#  USER CONFIG  ── only section you need to edit
# ══════════════════════════════════════════════════════════════════════════════

# Path to the material whose surfaces will receive foliage
TARGET_MATERIAL_PATH = "/Game/Materials/M_YourMaterial"  # TODO: replace

# List of FoliageType assets + their planting category
# Use the same asset paths you see in the UE5 Foliage Tool panel
FOLIAGE_TYPES = [
    # (content_path,                       category)
    ("/Game/Foliage/FT_LargeTree",  "LARGE_TREE"),   # TODO: replace
    ("/Game/Foliage/FT_MediumTree", "MEDIUM_TREE"),  # TODO: replace
    ("/Game/Foliage/FT_SmallTree",  "SMALL_TREE"),   # TODO: replace
    ("/Game/Foliage/FT_Shrub",      "SHRUB"),         # TODO: replace
]

# Seed for reproducible random jitter — change to get a different layout
PLACEMENT_SEED = 42

# Height above surface to start line traces (cm)
TRACE_HEIGHT_OFFSET = 5000

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY RULES  ── from Israeli National Guide for Shading Trees (2020)
# ══════════════════════════════════════════════════════════════════════════════
#
#  spacing      : average distance between plants (cm), mid-point of guide range
#  jitter       : max random offset as fraction of spacing (adds natural variation)
#  scale        : (min, max) random uniform scale applied to each instance
#  align_normal : True  → tilt instance to match surface normal (shrubs/groundcover)
#                 False → keep instance upright (trees)
#
CATEGORY_RULES = {
    # Large trees  (10 m+) — spacing 10–15 m (guide §4.1, table 1)
    "LARGE_TREE": {
        "spacing":      1250,
        "jitter":       0.20,
        "scale":        (0.90, 1.10),
        "align_normal": False,
    },
    # Medium trees (7–9 m) — spacing 7–10 m (guide §4.1, table 1)
    "MEDIUM_TREE": {
        "spacing":      850,
        "jitter":       0.20,
        "scale":        (0.85, 1.15),
        "align_normal": False,
    },
    # Small trees  (5–6 m) — spacing 4–7 m (guide §4.1, table 1)
    "SMALL_TREE": {
        "spacing":      550,
        "jitter":       0.20,
        "scale":        (0.80, 1.20),
        "align_normal": True,
    },
    # Shrubs       (<3 m)  — spacing 1.5–3 m (guide §5.2)
    "SHRUB": {
        "spacing":      225,
        "jitter":       0.25,
        "scale":        (0.70, 1.30),
        "align_normal": True,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _material_matches(component, target_path):
    """Return True if any material slot on this component matches target_path."""
    target_path_clean = target_path.rstrip("_C").split(".")[0]
    try:
        mats = component.get_materials()
    except Exception:
        return False
    for mat in mats:
        if mat is None:
            continue
        mat_path = mat.get_path_name()
        # Check base path, parent, and instance parent
        if target_path_clean in mat_path:
            return True
        # Check if it's a material instance and compare parent
        if hasattr(mat, "parent"):
            parent = mat.parent
            if parent and target_path_clean in parent.get_path_name():
                return True
    return False


def _normal_to_rotator(normal):
    """Convert a surface normal vector to a Rotator aligned with that normal."""
    # Z-up world to surface normal rotation
    up = unreal.Vector(0.0, 0.0, 1.0)
    nx, ny, nz = normal.x, normal.y, normal.z

    # Pitch: angle between surface normal and world-up projected onto XZ plane
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, ny))))
    # Roll: angle around forward axis
    roll  = math.degrees(math.atan2(nx, nz))

    return unreal.Rotator(pitch, 0.0, roll)


def _find_matching_actors(world, target_material_path):
    """Return all StaticMeshActors whose meshes use the target material."""
    matching = []
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for actor in actors:
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        mesh_comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if mesh_comp and _material_matches(mesh_comp, target_material_path):
            matching.append(actor)
    return matching


def _generate_candidate_points(origin, extent, spacing, jitter_frac, rng):
    """
    Generate a uniform grid of XY candidate points within the actor bounding box,
    with seeded random jitter applied to each point.

    Returns list of (x, y) tuples in world space.
    """
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


def _line_trace_to_surface(world, x, y, top_z, target_material_path):
    """
    Cast a ray straight down from (x, y, top_z + offset) and return
    (hit_location, hit_normal) if the hit surface uses the target material,
    or None otherwise.
    """
    start = unreal.Vector(x, y, top_z + TRACE_HEIGHT_OFFSET)
    end   = unreal.Vector(x, y, top_z - TRACE_HEIGHT_OFFSET * 2)

    hit_result = unreal.SystemLibrary.line_trace_single(
        world,
        start,
        end,
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
        False,    # trace complex
        [],       # actors to ignore
        unreal.DrawDebugTrace.NONE,
        True,     # ignore self
    )

    if not hit_result:
        return None

    # Verify the hit component uses our target material
    hit_component = hit_result.component
    if hit_component is None:
        return None
    if not _material_matches(hit_component, target_material_path):
        return None

    return hit_result.location, hit_result.normal


def _build_transform(location, normal, scale_range, align_normal, rng):
    """Build a placement Transform from hit data."""
    scale_val = rng.uniform(*scale_range)
    scale = unreal.Vector(scale_val, scale_val, scale_val)

    if align_normal:
        rotation = _normal_to_rotator(normal)
    else:
        # Upright, but random yaw so each tree faces a different direction
        yaw = rng.uniform(0.0, 360.0)
        rotation = unreal.Rotator(0.0, yaw, 0.0)

    return unreal.Transform(location, rotation, scale)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def generate_foliage(
    target_material_path=TARGET_MATERIAL_PATH,
    foliage_types=FOLIAGE_TYPES,
    seed=PLACEMENT_SEED,
):
    """
    Main entry point.  Can be called directly or invoked by the EUW widget.

    Args:
        target_material_path : content path of the material to detect
        foliage_types        : list of (asset_path, category) tuples
        seed                 : random seed for jitter reproducibility
    """
    t0 = time.time()
    rng = random.Random(seed)
    world = unreal.EditorLevelLibrary.get_editor_world()

    print("\n─────────────────────────────────────────")
    print("  Foliage Generator")
    print(f"  Material : {target_material_path}")
    print(f"  Seed     : {seed}")
    print("─────────────────────────────────────────")

    # ── 1. Find actors using target material ──────────────────────────────────
    matching_actors = _find_matching_actors(world, target_material_path)
    if not matching_actors:
        print(f"\n⚠  No StaticMeshActors found using material: {target_material_path}")
        print("   Check TARGET_MATERIAL_PATH and try again.")
        return

    print(f"\n✓ Found {len(matching_actors)} actor(s) using the target material.")

    # ── 2. Get the foliage actor for the current level ────────────────────────
    foliage_actor = unreal.InstancedFoliageActor.get_instanced_foliage_actor_for_current_level(
        world, True
    )

    total_placed = 0

    # ── 3. For each foliage type, generate and place instances ────────────────
    with unreal.ScopedEditorTransaction("Generate Foliage on Material Surface"):
        for ft_path, category in foliage_types:
            # Load the FoliageType asset
            ft_asset = unreal.load_object(None, ft_path)
            if ft_asset is None:
                print(f"\n⚠  FoliageType not found: {ft_path}  (skipped)")
                continue

            rules   = CATEGORY_RULES.get(category, CATEGORY_RULES["MEDIUM_TREE"])
            spacing = rules["spacing"]
            jitter  = rules["jitter"]
            sc_min, sc_max = rules["scale"]
            align   = rules["align_normal"]

            transforms = []

            for actor in matching_actors:
                origin, extent = actor.get_actor_bounds(False)
                top_z = origin.z + extent.z

                candidates = _generate_candidate_points(
                    origin, extent, spacing, jitter, rng
                )

                for cx, cy in candidates:
                    result = _line_trace_to_surface(
                        world, cx, cy, top_z, target_material_path
                    )
                    if result is None:
                        continue
                    hit_loc, hit_normal = result
                    xf = _build_transform(
                        hit_loc, hit_normal, (sc_min, sc_max), align, rng
                    )
                    transforms.append(xf)

            if transforms:
                foliage_actor.add_instances(ft_asset, transforms, True)
                print(f"  ✓ {ft_path.split('/')[-1]:30s}  [{category:12s}]  →  {len(transforms):>5} instances")
                total_placed += len(transforms)
            else:
                print(f"  –  {ft_path.split('/')[-1]:30s}  [{category:12s}]  →  no valid points")

    elapsed = time.time() - t0
    print(f"\n✓ Done — {total_placed} total instances placed in {elapsed:.1f}s")
    print("─────────────────────────────────────────\n")


# Run immediately when executed as a standalone script
if __name__ != "__import__":
    generate_foliage()
