"""
Foliage Generator — Material Eyedropper
=========================================
Called by the "Pick Material" button in EUW_FoliageGenerator.

WORKFLOW:
  1. Click on any surface in the UE5 viewport to select it
  2. Click the eyedropper / "Pick" button in the widget
  3. This script reads the material from the selected actor and
     writes it back into the widget's MaterialPathInput field

HOW IT WORKS:
  - Reads the first selected StaticMeshActor in the viewport
  - Resolves the base material (strips material instance layers)
  - Finds the running EUW_FoliageGenerator widget via EditorUtilitySubsystem
  - Sets the MaterialPathInput text to the resolved path
"""

import unreal

WIDGET_ASSET_PATH = "/Game/FoliageGenerator/EUW_FoliageGenerator"


def _resolve_base_material_path(mat):
    """
    Walk up the material instance chain to find the root Material asset path.
    Returns the clean content-browser path, e.g. /Game/Materials/M_Ground
    """
    # Unwrap material instances to get the base material
    current = mat
    for _ in range(10):   # safety limit for deep instance chains
        if isinstance(current, unreal.MaterialInstance):
            parent = current.get_editor_property("parent")
            if parent is not None:
                current = parent
                continue
        break

    path = current.get_path_name()

    # Strip sub-object suffix:  /Game/Mat.Mat:SomeSub  →  /Game/Mat.Mat
    if ":" in path:
        path = path.split(":")[0]

    # Strip asset-name suffix:  /Game/Mat.Mat  →  /Game/Mat
    if "." in path:
        path = path.rsplit(".", 1)[0]

    return path


def pick_material_from_selection():
    """
    Main entry point.  Reads selected viewport actor → material →
    updates EUW_FoliageGenerator's MaterialPathInput.
    """
    # ── 1. Get selected actors ────────────────────────────────────────────────
    selected = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_selected_level_actors()
    if not selected:
        print("[Pick Material] ⚠  Nothing selected in the viewport.")
        print("               Click on a surface first, then press Pick.")
        _set_widget_status("⚠  Nothing selected.\nClick on a surface in the viewport first,\nthen press Pick Material.")
        return

    actor = selected[0]

    # ── 2. Get material from the first mesh component ─────────────────────────
    mesh_comp = actor.get_component_by_class(unreal.StaticMeshComponent)
    if mesh_comp is None:
        print(f"[Pick Material] ⚠  '{actor.get_actor_label()}' has no StaticMeshComponent.")
        _set_widget_status(f"⚠  Selected actor has no mesh:\n{actor.get_actor_label()}")
        return

    materials = mesh_comp.get_materials()
    mat = next((m for m in materials if m is not None), None)
    if mat is None:
        print(f"[Pick Material] ⚠  No material found on '{actor.get_actor_label()}'.")
        _set_widget_status(f"⚠  No material on:\n{actor.get_actor_label()}")
        return

    # ── 3. Resolve base material path ────────────────────────────────────────
    mat_path = _resolve_base_material_path(mat)

    print(f"[Pick Material] Actor   : {actor.get_actor_label()}")
    print(f"[Pick Material] Material: {mat_path}")

    # ── 4. Update the widget ──────────────────────────────────────────────────
    try:
        subsystem    = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        widget_asset = unreal.load_object(None, WIDGET_ASSET_PATH)

        if widget_asset is None:
            print(f"[Pick Material] ⚠  Widget not found at {WIDGET_ASSET_PATH}.")
            return

        widget = subsystem.find_utility_widget_from_blueprint(widget_asset)
        if widget is None:
            print("[Pick Material] ⚠  EUW_FoliageGenerator is not open.")
            print("               Run Editor Utility Widget first.")
            return

        mat_input = widget.get_widget_from_name("MaterialPathInput")
        if mat_input is None:
            print("[Pick Material] ⚠  MaterialPathInput widget not found.")
            return

        mat_input.set_text(unreal.Text.cast(mat_path))
        print(f"[Pick Material] ✓ Set material path in widget.")

        _set_widget_status(f"Material picked:\n{mat_path}\n\nFrom actor: {actor.get_actor_label()}")

    except Exception as e:
        print(f"[Pick Material] Error: {e}")


def _set_widget_status(message):
    """Write a status message to the widget's StatusLog if it's running."""
    try:
        subsystem    = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
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


pick_material_from_selection()
