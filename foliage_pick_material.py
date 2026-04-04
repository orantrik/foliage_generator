"""
Foliage Generator — Material Eyedropper
=========================================
Called by the "Pick Material" button in EUW_FoliageGenerator.

WORKFLOW:
  1. Click on any surface in the UE5 viewport to select it
  2. Click  ↗ Pick Material from Selection  in the widget
  3. The material path is written into MaterialPathInput automatically.
     If widget write fails, the path is saved to last_material.txt next
     to these scripts — the Generator reads it from there automatically.
"""

import unreal
import os

WIDGET_ASSET_PATH  = "/Game/FoliageGenerator/EUW_FoliageGenerator"
WIDGET_OBJECT_PATH = WIDGET_ASSET_PATH + "." + WIDGET_ASSET_PATH.split("/")[-1]

_THIS_DIR         = os.path.dirname(os.path.abspath(__file__))
LAST_MATERIAL_FILE = os.path.join(_THIS_DIR, "last_material.txt")


# ── File-based fallback ───────────────────────────────────────────────────────

def _save_material_path(path):
    """Always write to file — reliable even when widget write fails."""
    try:
        with open(LAST_MATERIAL_FILE, "w") as f:
            f.write(path)
    except Exception as e:
        print(f"[Pick Material] ⚠  Could not save last_material.txt: {e}")


# ── Widget child access ───────────────────────────────────────────────────────

def _get_widget(parent, name):
    for fn in [
        lambda: parent.get_widget_from_name(name),
        lambda: unreal.UserWidget.get_widget_from_name(parent, name),
    ]:
        try:
            w = fn()
            if w is not None:
                return w
        except Exception:
            pass
    return None


def _set_widget_text(parent, name, text):
    w = _get_widget(parent, name)
    if w is None:
        return False
    # Try multiple text representations — UE5 Python binding varies by version
    for val in [text, unreal.Text(text)]:
        try:
            w.set_text(val)
            return True
        except Exception:
            continue
    return False


# ── Material resolution ───────────────────────────────────────────────────────

def _clean_material_path(mat):
    """Return the clean /Game/... path of this specific material (no chain walking).
    Using the instance directly lets the generator distinguish MI_TennisGreen
    from MI_Grass even though both share the same master material."""
    path = mat.get_path_name()
    if ":" in path:
        path = path.split(":")[0]
    if "." in path:
        path = path.rsplit(".", 1)[0]
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

def pick_material_from_selection():
    # 1. Get selected actor
    selected = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_selected_level_actors()

    if not selected:
        print("[Pick Material] ⚠  Nothing selected — click a surface first.")
        return

    actor = selected[0]

    # 2. Get material
    mesh_comp = actor.get_component_by_class(unreal.StaticMeshComponent)
    if mesh_comp is None:
        print(f"[Pick Material] ⚠  '{actor.get_actor_label()}' has no StaticMeshComponent.")
        return

    mat = next((m for m in mesh_comp.get_materials() if m is not None), None)
    if mat is None:
        print(f"[Pick Material] ⚠  No material on '{actor.get_actor_label()}'.")
        return

    # 3. Get the instance path directly (not the master)
    mat_path = _clean_material_path(mat)
    print(f"[Pick Material] Actor   : {actor.get_actor_label()}")
    print(f"[Pick Material] Material: {mat_path}")

    # 4. Always save to file first (reliable fallback)
    _save_material_path(mat_path)
    print(f"[Pick Material] ✓ Saved to last_material.txt")

    # 5. Try to write into running widget
    subsystem    = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
    widget_asset = unreal.find_object(None, WIDGET_OBJECT_PATH)
    if not widget_asset:
        widget_asset = unreal.load_object(None, WIDGET_OBJECT_PATH)
    widget = subsystem.find_utility_widget_from_blueprint(widget_asset) if widget_asset else None

    if widget:
        ok = _set_widget_text(widget, "MaterialPathInput", mat_path)
        if ok:
            print("[Pick Material] ✓ MaterialPathInput updated in widget.")
            _set_widget_text(
                widget, "StatusLog",
                f"Material picked:\n{mat_path}\n\nFrom: {actor.get_actor_label()}"
            )
        else:
            print(
                "[Pick Material] ⚠  Could not write to MaterialPathInput.\n"
                "                   Paste this path into the field manually:\n"
                f"                   {mat_path}\n"
                "                   (also saved to last_material.txt)"
            )
    else:
        print(
            "[Pick Material] ⚠  Widget not running.\n"
            "                   Path saved to last_material.txt — Generator will use it."
        )


pick_material_from_selection()
