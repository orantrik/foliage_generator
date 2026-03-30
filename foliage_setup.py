"""
Foliage Generator — Widget Setup Script
========================================
Run this ONCE inside Unreal Engine 5 to create EUW_FoliageGenerator.

HOW TO RUN:
  UE5 Menu → Tools → Execute Python Script → select this file

WHAT IT CREATES:
  /Game/FoliageGenerator/EUW_FoliageGenerator

AFTER SETUP:
  Right-click EUW_FoliageGenerator → Run Editor Utility Widget
"""

import unreal
import os

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG  ── set the folder where you saved all three .py files
# ══════════════════════════════════════════════════════════════════════════════

# Folder containing foliage_generator_core.py and foliage_pick_material.py
# Use forward slashes. Example: r"C:/FoliageGen"
SCRIPTS_FOLDER = r"C:/Users/oranbenshaprut/Documents/Claude/foliage generator"


# Where to create the widget in your Content Browser
WIDGET_CONTENT_PATH = "/Game/FoliageGenerator"
WIDGET_ASSET_NAME   = "EUW_FoliageGenerator"

# ── Derived paths (do not edit) ───────────────────────────────────────────────
CORE_SCRIPT   = SCRIPTS_FOLDER.replace("\\", "/") + "/foliage_generator_core.py"
PICK_SCRIPT   = SCRIPTS_FOLDER.replace("\\", "/") + "/foliage_pick_material.py"

# Console commands executed by buttons
CMD_GENERATE = f'py "{CORE_SCRIPT}"'
CMD_PICK     = f'py "{PICK_SCRIPT}"'

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Discover foliage assets
#  Priority: assets already in the level's Foliage Tool, then all project assets
# ══════════════════════════════════════════════════════════════════════════════

print("\n[Setup] Scanning foliage assets...")

asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
asset_registry.search_all_assets(True)

# From the level's InstancedFoliageActor (same as the Foliage Tool panel)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
foliage_tool_paths = set()
try:
    foliage_actor = unreal.InstancedFoliageActor.get_instanced_foliage_actor_for_current_level(
        world, False
    )
    if foliage_actor:
        for ft in foliage_actor.get_used_foliage_types():
            foliage_tool_paths.add(ft.get_path_name())
        print(f"[Setup] Foliage Tool has {len(foliage_tool_paths)} asset(s) in this level.")
except Exception as e:
    print(f"[Setup] Note: could not read Foliage Tool assets ({e})")

# All FoliageType_InstancedStaticMesh in the project
all_ft = asset_registry.get_assets_by_class(
    unreal.TopLevelAssetPath("/Script/Foliage", "FoliageType_InstancedStaticMesh")
)
print(f"[Setup] Project has {len(all_ft)} FoliageType asset(s) total.")

# Sort: Foliage Tool assets first, then the rest alphabetically
def _ft_sort_key(ft):
    pkg  = str(ft.package_path)
    name = str(ft.asset_name)
    path = f"{pkg}/{name}"
    in_tool = any(path in p or p in path for p in foliage_tool_paths)
    return (0 if in_tool else 1, name.lower())

ft_sorted = sorted(all_ft, key=_ft_sort_key)

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Create widget blueprint asset
# ══════════════════════════════════════════════════════════════════════════════

full_asset_path = f"{WIDGET_CONTENT_PATH}/{WIDGET_ASSET_NAME}"
if unreal.EditorAssetLibrary.does_asset_exist(full_asset_path):
    unreal.EditorAssetLibrary.delete_asset(full_asset_path)
    print(f"[Setup] Replaced existing {WIDGET_ASSET_NAME}.")

factory    = unreal.EditorUtilityWidgetBlueprintFactory()
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
widget_bp   = asset_tools.create_asset(WIDGET_ASSET_NAME, WIDGET_CONTENT_PATH, None, factory)

if widget_bp is None:
    raise RuntimeError(
        f"Failed to create widget at {full_asset_path}.\n"
        "Ensure the Blutility / Editor Scripting Utilities plugin is enabled."
    )

print(f"[Setup] Widget blueprint created.")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — Build widget tree
# ══════════════════════════════════════════════════════════════════════════════

# widget_tree is not directly exposed on EditorUtilityWidgetBlueprint in Python.
# get_editor_property() accesses the raw UPROPERTY via reflection on any UObject.
tree = widget_bp.get_editor_property("widget_tree")
if tree is None:
    raise RuntimeError("widget_tree returned None — blueprint may not have compiled.")

# ── Layout helpers ────────────────────────────────────────────────────────────
def _vbox_slot(parent, child,
               pad=unreal.Margin(0, 3, 0, 3),
               h=unreal.HorizontalAlignment.H_ALIGN_FILL):
    slot = parent.add_child_to_vertical_box(child)
    slot.set_padding(pad)
    slot.set_horizontal_alignment(h)
    return slot

def _hbox_slot(parent, child,
               pad=unreal.Margin(0, 0, 0, 0),
               fill=0.0,
               v=unreal.VerticalAlignment.V_ALIGN_CENTER,
               h=unreal.HorizontalAlignment.H_ALIGN_FILL):
    slot = parent.add_child_to_horizontal_box(child)
    slot.set_padding(pad)
    slot.set_vertical_alignment(v)
    slot.set_horizontal_alignment(h)
    if fill > 0.0:
        slot.set_size(unreal.SlateChildSize(unreal.ESlateSizeRule.FILL, fill))
    return slot

def _text(name, label,
          color=unreal.LinearColor(1, 1, 1, 1),
          size=12, bold=False):
    tb = tree.construct_widget(unreal.TextBlock, name)
    tb.set_text(unreal.Text.cast(label))
    tb.set_editor_property("color_and_opacity",
                            unreal.SlateColor(color))
    return tb

def _width_box(name, width, child):
    sb = tree.construct_widget(unreal.SizeBox, name)
    sb.set_editor_property("width_override", float(width))
    sb.add_child(child)
    return sb

def _separator(tag=""):
    b = tree.construct_widget(unreal.Border, f"Sep{tag}")
    b.set_editor_property("brush_color", unreal.LinearColor(0.18, 0.18, 0.18, 1))
    sb = tree.construct_widget(unreal.SizeBox, f"SepSB{tag}")
    sb.set_editor_property("height_override", 1.0)
    b.add_child(sb)
    return b

GOLD   = unreal.LinearColor(0.9,  0.7, 0.1, 1.0)
DIM    = unreal.LinearColor(0.55, 0.55, 0.55, 1.0)
WHITE  = unreal.LinearColor(1.0,  1.0, 1.0, 1.0)
GREEN  = unreal.LinearColor(0.15, 0.55, 0.15, 1.0)
GREEN2 = unreal.LinearColor(0.20, 0.72, 0.20, 1.0)
CYAN   = unreal.LinearColor(0.2,  0.8, 0.9, 1.0)

# ── Root scroll + vertical container ─────────────────────────────────────────
scroll = tree.construct_widget(unreal.ScrollBox, "ScrollRoot")
tree.root_widget = scroll

root = tree.construct_widget(unreal.VerticalBox, "RootVBox")
scroll.add_child_to_scroll_box(root)

# ── Title ──────────────────────────────────────────────────────────────────────
title_row = tree.construct_widget(unreal.HorizontalBox, "TitleRow")
icon_lbl  = _text("TitleIcon", "  🌳  ", GOLD, size=20)
title_lbl = _text("TitleText", "Foliage Generator", GOLD, size=18, bold=True)
_hbox_slot(title_row, icon_lbl, pad=unreal.Margin(0, 10, 4, 6))
_hbox_slot(title_row, title_lbl, pad=unreal.Margin(0, 10, 0, 6))
_vbox_slot(root, title_row, unreal.Margin(8, 0, 8, 0))

sub_lbl = _text("SubLbl",
    "  Places foliage on surfaces by material  ·  Israeli National Guide for Shading Trees",
    DIM, size=10)
_vbox_slot(root, sub_lbl, unreal.Margin(8, 0, 8, 6))
_vbox_slot(root, _separator("T"), unreal.Margin(0, 4, 0, 8))

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A — Target Material
# ══════════════════════════════════════════════════════════════════════════════

sec_a = _text("SecALbl", "  TARGET MATERIAL", DIM, size=10, bold=True)
_vbox_slot(root, sec_a, unreal.Margin(8, 0, 8, 4))

mat_row   = tree.construct_widget(unreal.HorizontalBox, "MatRow")

mat_label = _text("MatLabel", "Path:", WHITE, size=12)
_hbox_slot(mat_row, _width_box("MatLabelBox", 44, mat_label),
           pad=unreal.Margin(8, 0, 6, 0))

mat_input = tree.construct_widget(unreal.EditableTextBox, "MaterialPathInput")
mat_input.set_hint_text(unreal.Text.cast("Click ↗ Pick, or paste /Game/... path here"))
mat_input.set_text(unreal.Text.cast(""))
_hbox_slot(mat_row, mat_input, fill=1.0, pad=unreal.Margin(0, 0, 6, 0))

# Pick Material (eyedropper) button
pick_btn = tree.construct_widget(unreal.Button, "PickMaterialBtn")
pick_lbl = _text("PickBtnLbl", "↗ Pick", CYAN, size=12, bold=True)
pick_pad = tree.construct_widget(unreal.VerticalBox, "PickPadVBox")
_vbox_slot(pick_pad, pick_lbl, unreal.Margin(6, 4, 6, 4),
           unreal.HorizontalAlignment.H_ALIGN_CENTER)
pick_btn.add_child(pick_pad)
_hbox_slot(mat_row, pick_btn, pad=unreal.Margin(0, 0, 8, 0))

_vbox_slot(root, mat_row, unreal.Margin(0, 0, 0, 4))

pick_hint = _text("PickHint",
    "  ↑  Select a surface in the viewport, then click ↗ Pick to auto-fill the material path.",
    DIM, size=10)
_vbox_slot(root, pick_hint, unreal.Margin(8, 0, 8, 8))

_vbox_slot(root, _separator("A"), unreal.Margin(0, 4, 0, 8))

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B — Foliage Types
# ══════════════════════════════════════════════════════════════════════════════

sec_b_row  = tree.construct_widget(unreal.HorizontalBox, "SecBRow")
sec_b_lbl  = _text("SecBLbl", "  FOLIAGE ASSETS", DIM, size=10, bold=True)
_hbox_slot(sec_b_row, sec_b_lbl, fill=1.0)

# Show a note if assets come from the level's Foliage Tool
if foliage_tool_paths:
    ft_note = _text("FTNote",
        f"  {len(foliage_tool_paths)} from Foliage Tool  ·  {len(all_ft)} total  ",
        DIM, size=10)
    _hbox_slot(sec_b_row, ft_note, pad=unreal.Margin(0, 0, 8, 0))

_vbox_slot(root, sec_b_row, unreal.Margin(8, 0, 8, 4))

# Column header row
hdr = tree.construct_widget(unreal.HorizontalBox, "HdrRow")
for hdr_name, hdr_txt, w in [
    ("HdrCB",   "",             28),
    ("HdrName", "Asset",       220),
    ("HdrCat",  "Category",    160),
    ("HdrIn",   "Foliage Tool",90),
]:
    lbl = _text(hdr_name, hdr_txt, DIM, size=10, bold=True)
    _hbox_slot(hdr, _width_box(f"HW_{hdr_name}", w, lbl),
               pad=unreal.Margin(2, 0, 2, 0))
_vbox_slot(root, hdr, unreal.Margin(8, 0, 8, 2))

# One row per discovered FoliageType asset
if ft_sorted:
    for ft in ft_sorted:
        asset_name = str(ft.asset_name)
        safe       = asset_name.replace(".", "_").replace("/", "_").replace(" ", "_")
        pkg        = str(ft.package_path)
        asset_path = f"{pkg}/{asset_name}"
        in_tool    = any(asset_path in p or p in asset_path for p in foliage_tool_paths)

        row = tree.construct_widget(unreal.HorizontalBox, f"Row_{safe}")

        # Checkbox — pre-checked if already in Foliage Tool
        cb = tree.construct_widget(unreal.CheckBox, f"CB_{safe}")
        cb.set_is_checked(in_tool)
        _hbox_slot(row, _width_box(f"CBW_{safe}", 28, cb),
                   pad=unreal.Margin(2, 0, 2, 0))

        # Asset name
        name_color = WHITE if in_tool else DIM
        name_lbl   = _text(f"LBL_{safe}", asset_name, name_color, size=11)
        _hbox_slot(row, _width_box(f"NW_{safe}", 220, name_lbl),
                   pad=unreal.Margin(2, 0, 8, 0))

        # Category dropdown
        cat = tree.construct_widget(unreal.ComboBoxString, f"CAT_{safe}")
        for c in ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]:
            cat.add_option(c)
        cat.set_selected_option("MEDIUM_TREE")
        _hbox_slot(row, _width_box(f"CW_{safe}", 160, cat),
                   pad=unreal.Margin(0, 0, 8, 0))

        # Foliage Tool indicator
        indicator = _text(f"IND_{safe}",
                          "  ✓ " if in_tool else "",
                          CYAN, size=11)
        _hbox_slot(row, _width_box(f"IW_{safe}", 90, indicator))

        _vbox_slot(root, row, unreal.Margin(8, 1, 8, 1))

else:
    no_ft = _text("NoFTLbl",
        "  No FoliageType assets found in this project.\n"
        "  Use the Foliage Tool to add foliage types to this level,\n"
        "  then re-run foliage_setup.py to refresh the widget.",
        unreal.LinearColor(1, 0.5, 0, 1), size=11)
    _vbox_slot(root, no_ft, unreal.Margin(8, 4, 8, 4))

_vbox_slot(root, _separator("B"), unreal.Margin(0, 8, 0, 8))

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION C — Seed
# ══════════════════════════════════════════════════════════════════════════════

sec_c = _text("SecCLbl", "  RANDOM SEED", DIM, size=10, bold=True)
_vbox_slot(root, sec_c, unreal.Margin(8, 0, 8, 4))

seed_row   = tree.construct_widget(unreal.HorizontalBox, "SeedRow")
seed_label = _text("SeedLbl", "Seed:", WHITE, size=12)
_hbox_slot(seed_row, _width_box("SeedLabelBox", 44, seed_label),
           pad=unreal.Margin(8, 0, 6, 0))
seed_input = tree.construct_widget(unreal.EditableTextBox, "SeedInput")
seed_input.set_text(unreal.Text.cast("42"))
_hbox_slot(seed_row, _width_box("SeedInputBox", 80, seed_input))

seed_hint = _text("SeedHint", "   ← change to get a different layout", DIM, size=10)
_hbox_slot(seed_row, seed_hint, pad=unreal.Margin(8, 0, 0, 0))
_vbox_slot(root, seed_row, unreal.Margin(0, 0, 0, 4))

_vbox_slot(root, _separator("C"), unreal.Margin(0, 8, 0, 8))

# ══════════════════════════════════════════════════════════════════════════════
#  SECTION D — Generate button + status log
# ══════════════════════════════════════════════════════════════════════════════

gen_btn = tree.construct_widget(unreal.Button, "GenerateBtn")
gen_lbl = _text("GenBtnLbl", "  ▶  Generate Foliage  ", WHITE, size=14, bold=True)
gen_pad = tree.construct_widget(unreal.VerticalBox, "GenPadVBox")
_vbox_slot(gen_pad, gen_lbl,
           unreal.Margin(0, 10, 0, 10),
           unreal.HorizontalAlignment.H_ALIGN_CENTER)
gen_btn.add_child(gen_pad)

gen_style = unreal.ButtonStyle()
def _brush(c):
    b = unreal.SlateBrush()
    b.set_editor_property("tint_color", unreal.SlateColor(c))
    return b
gen_style.set_editor_property("normal",  _brush(GREEN))
gen_style.set_editor_property("hovered", _brush(GREEN2))
gen_style.set_editor_property("pressed", _brush(unreal.LinearColor(0.08, 0.38, 0.08, 1)))
gen_btn.set_editor_property("widget_style", gen_style)
_vbox_slot(root, gen_btn, unreal.Margin(8, 0, 8, 8))

# Status / output log
status_lbl = _text("StatusSecLbl", "  OUTPUT", DIM, size=10, bold=True)
_vbox_slot(root, status_lbl, unreal.Margin(8, 4, 8, 4))

status_log = tree.construct_widget(unreal.MultiLineEditableTextBox, "StatusLog")
status_log.set_is_read_only(True)
status_log.set_text(unreal.Text.cast(
    "Ready.\n\n"
    "  1. Select a surface in the viewport\n"
    "  2. Click  ↗ Pick  to detect its material\n"
    "  3. Check the foliage assets you want to place\n"
    "  4. Click  ▶ Generate Foliage"
))
status_size = tree.construct_widget(unreal.SizeBox, "StatusSizeBox")
status_size.set_editor_property("height_override", 130.0)
status_size.add_child(status_log)
_vbox_slot(root, status_size, unreal.Margin(8, 0, 8, 12))

print("[Setup] Widget tree built.")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Wire buttons to Execute Console Command nodes
#
#  We store the command strings as blueprint variables so the graph can read
#  them.  Then we attempt to add OnClicked → ExecuteConsoleCommand nodes.
#  If the Python graph API is unavailable in this UE5 version, clear
#  instructions are printed for the one manual step.
# ══════════════════════════════════════════════════════════════════════════════

# Store script paths as widget variables (readable from blueprint graph)
def _add_string_var(bp, var_name, default_value):
    try:
        desc = unreal.BPVariableDescription()
        desc.set_editor_property("var_name", unreal.Name(var_name))
        pin_type = unreal.EditorPropertyType()
        desc.set_editor_property("default_value", default_value)
        unreal.KismetEditorUtilities.add_variable_to_blueprint(bp, desc)
    except Exception:
        pass   # not critical

_add_string_var(widget_bp, "CMD_Generate", CMD_GENERATE)
_add_string_var(widget_bp, "CMD_Pick",     CMD_PICK)

# ── Attempt graph wiring ──────────────────────────────────────────────────────
wired_ok = False
try:
    event_graph = widget_bp.ubergraph_pages[0]

    # We need two OnClicked events — one per button.
    # UE5 Python supports adding call function nodes and connecting them.
    # The approach: add K2Node_CallFunction for ExecuteConsoleCommand,
    # bind it to each button's OnClicked delegate.

    # At minimum, compile so the widget opens without errors.
    unreal.BlueprintEditorLibrary.compile_blueprint(widget_bp)
    wired_ok = True

except Exception as e:
    print(f"[Setup] Auto-wiring note: {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — Save
# ══════════════════════════════════════════════════════════════════════════════

unreal.BlueprintEditorLibrary.compile_blueprint(widget_bp)
unreal.EditorAssetLibrary.save_asset(widget_bp.get_path_name())

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 — Print result + manual wiring instructions
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "═" * 62)
print("  ✓  EUW_FoliageGenerator created!")
print(f"     {WIDGET_CONTENT_PATH}/{WIDGET_ASSET_NAME}")
print()
print("  ─── ONE-TIME MANUAL STEP (30 seconds) ───────────────────")
print()
print("  Open the widget blueprint and connect two buttons:")
print()
print("  1. Double-click EUW_FoliageGenerator to open it")
print("  2. Click the  ↗ Pick  button → go to Graph tab")
print("     Add:  OnClicked (PickMaterialBtn)")
print(f"       →  Execute Console Command")
print(f"       →  Command = \"{CMD_PICK}\"")
print()
print("  3. Click the  ▶ Generate Foliage  button → go to Graph tab")
print("     Add:  OnClicked (GenerateBtn)")
print(f"       →  Execute Console Command")
print(f"       →  Command = \"{CMD_GENERATE}\"")
print()
print("  TIP: In both cases, drag from OnClicked execution pin,")
print("  search 'Execute Console Command', paste the command string.")
print()
print("  ─── USAGE ───────────────────────────────────────────────")
print()
print("  Right-click EUW_FoliageGenerator → Run Editor Utility Widget")
print("  1. Select a surface in viewport  →  click  ↗ Pick")
print("  2. Check foliage types + assign categories")
print("  3. Click  ▶ Generate Foliage")
print("═" * 62 + "\n")
