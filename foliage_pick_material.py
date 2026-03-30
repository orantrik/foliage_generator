"""
Foliage Generator — Material Eyedropper
=========================================
Called by the "Pick Material" button in EUW_FoliageGenerator.

WORKFLOW:
  1. Click on any surface in the UE5 viewport to select it
  2. Click  ↗ Pick Material from Selection  in the widget
  3. The material path is written into MaterialPathInput automatically.
     If that fails, it is copied to the clipboard — just Ctrl+V.
"""

import unreal
import subprocess

WIDGET_ASSET_PATH = "/Game/FoliageGenerator/EUW_FoliageGenerator"


# ── Widget child access ───────────────────────────────────────────────────────

def _get_widget(parent, name):
    """
    Get a named child widget.
    EditorUtilityWidget's Python binding omits get_widget_from_name,
    so we fall back to calling it on the UserWidget parent binding.
    """
    try:
        w = parent.get_widget_from_name(name)
        if w is not None:
            return w
    except AttributeError:
        pass
    try:
        w = unreal.UserWidget.get_widget_from_name(parent, name)
        if w is not None:
            return w
    except Exception:
        pass
    return None


def _set_widget_text(parent, name, text):
    w = _get_widget(parent, name)
    if w:
        try:
            w.set_text(unreal.Text.cast(text))
            return True
        except Exception:
            pass
    return False


def _copy_to_clipboard(text):
    """Copy text to Windows clipboard via PowerShell."""
    try:
        subprocess.run(
            ["powershell", "-command", f"Set-Clipboard -Value '{text}'"],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        return False


# ── Material resolution ───────────────────────────────────────────────────────

def _resolve_base_material_path(mat):
    """Walk material instance chain → return clean /Game/... path."""
    current = mat
    for _ in range(10):
        if isinstance(current, unreal.MaterialInstance):
            parent = current.get_editor_property("parent")
            if parent is not None:
                current = parent
                continue
        break

    path = current.get_path_name()
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

    # 3. Resolve base path
    mat_path = _resolve_base_material_path(mat)
    print(f"[Pick Material] Actor   : {actor.get_actor_label()}")
    print(f"[Pick Material] Material: {mat_path}")

    # 4. Write into widget — with clipboard fallback
    subsystem    = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
    widget_asset = unreal.load_object(None, WIDGET_ASSET_PATH)
    widget       = subsystem.find_utility_widget_from_blueprint(widget_asset) if widget_asset else None

    wrote_to_widget = False
    if widget:
        wrote_to_widget = _set_widget_text(widget, "MaterialPathInput", mat_path)
        if wrote_to_widget:
            print("[Pick Material] ✓ MaterialPathInput updated.")
            _set_widget_text(
                widget, "StatusLog",
                f"Material picked:\n{mat_path}\n\nFrom actor: {actor.get_actor_label()}"
            )

    if not wrote_to_widget:
        # Fallback: copy to clipboard so user can Ctrl+V into the field
        if _copy_to_clipboard(mat_path):
            print("[Pick Material] ✓ Path copied to clipboard — Ctrl+V into the material field.")
        else:
            print(f"[Pick Material] ✓ Copy this path manually:\n  {mat_path}")


pick_material_from_selection()
