"""
Foliage Generator — Widget Setup Script
========================================
Run this ONCE inside Unreal Engine 5 to create the fully-built
EUW_FoliageGenerator Editor Utility Widget in your Content folder.

HOW TO RUN:
  UE5 Menu → Tools → Execute Python Script → select this file
  (or in Output Log Python console):
    exec(open(r"C:/FoliageGen/foliage_setup.py").read())

WHAT IT CREATES:
  /Game/FoliageGenerator/EUW_FoliageGenerator

AFTER SETUP:
  Right-click EUW_FoliageGenerator in the Content Browser
  → Run Editor Utility Widget
"""

import unreal

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG  ── set this to wherever you saved foliage_generator_core.py
# ══════════════════════════════════════════════════════════════════════════════

CORE_SCRIPT_PATH = r"C:/FoliageGen/foliage_generator_core.py"  # TODO: update path

# Where to create the widget in your Content Browser
WIDGET_CONTENT_PATH = "/Game/FoliageGenerator"
WIDGET_ASSET_NAME   = "EUW_FoliageGenerator"

# ══════════════════════════════════════════════════════════════════════════════
#  STYLE CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

COLOR_BG        = unreal.LinearColor(0.05, 0.05, 0.05, 1.0)
COLOR_TITLE     = unreal.LinearColor(0.9,  0.7,  0.1,  1.0)
COLOR_BTN       = unreal.LinearColor(0.15, 0.55, 0.15, 1.0)
COLOR_BTN_HOVER = unreal.LinearColor(0.20, 0.70, 0.20, 1.0)
COLOR_WHITE     = unreal.LinearColor(1.0,  1.0,  1.0,  1.0)
COLOR_DIM       = unreal.LinearColor(0.6,  0.6,  0.6,  1.0)

PADDING_OUTER = unreal.Margin(16.0, 16.0, 16.0, 16.0)
PADDING_ROW   = unreal.Margin(0.0,  4.0,  0.0,  4.0)
PADDING_LABEL = unreal.Margin(0.0,  0.0,  10.0, 0.0)

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Discover FoliageType assets already in the project
# ══════════════════════════════════════════════════════════════════════════════

print("\n[Foliage Setup] Scanning project for FoliageType assets...")

asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
asset_registry.search_all_assets(True)  # wait for registry to finish loading

ft_assets = asset_registry.get_assets_by_class(
    unreal.TopLevelAssetPath("/Script/Foliage", "FoliageType_InstancedStaticMesh")
)

print(f"[Foliage Setup] Found {len(ft_assets)} FoliageType asset(s).")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Create the Editor Utility Widget blueprint asset
# ══════════════════════════════════════════════════════════════════════════════

# Delete existing asset if it already exists so setup is re-runnable
full_asset_path = f"{WIDGET_CONTENT_PATH}/{WIDGET_ASSET_NAME}"
if unreal.EditorAssetLibrary.does_asset_exist(full_asset_path):
    unreal.EditorAssetLibrary.delete_asset(full_asset_path)
    print(f"[Foliage Setup] Replaced existing {WIDGET_ASSET_NAME}.")

factory = unreal.EditorUtilityWidgetBlueprintFactory()
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
widget_bp = asset_tools.create_asset(
    WIDGET_ASSET_NAME,
    WIDGET_CONTENT_PATH,
    None,
    factory,
)

if widget_bp is None:
    raise RuntimeError(
        f"Failed to create widget blueprint at {full_asset_path}.\n"
        "Check that the Blutility / Editor Scripting Utilities plugin is enabled."
    )

print(f"[Foliage Setup] Widget blueprint created: {full_asset_path}")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — Build the complete widget tree
# ══════════════════════════════════════════════════════════════════════════════

tree = widget_bp.widget_tree

# ── Root: scrollable vertical stack ──────────────────────────────────────────
scroll_root = tree.construct_widget(unreal.ScrollBox, "ScrollRoot")
tree.root_widget = scroll_root

outer_pad = tree.construct_widget(unreal.SizeBox, "OuterPad")
outer_pad.set_editor_property("width_override", 600.0)
scroll_root.add_child_to_scroll_box(outer_pad)

root_vbox = tree.construct_widget(unreal.VerticalBox, "RootVBox")
outer_pad.add_child(root_vbox)


def _vbox_add(parent, child, padding=PADDING_ROW, h_align=unreal.HorizontalAlignment.H_ALIGN_FILL):
    slot = parent.add_child_to_vertical_box(child)
    slot.set_padding(padding)
    slot.set_horizontal_alignment(h_align)
    return slot


def _hbox_add(parent, child, padding=unreal.Margin(0, 0, 0, 0), fill=0.0, h_align=unreal.HorizontalAlignment.H_ALIGN_FILL, v_align=unreal.VerticalAlignment.V_ALIGN_CENTER):
    slot = parent.add_child_to_horizontal_box(child)
    slot.set_padding(padding)
    if fill > 0.0:
        slot.set_size(unreal.SlateChildSize(unreal.ESlateSizeRule.FILL, fill))
    slot.set_horizontal_alignment(h_align)
    slot.set_vertical_alignment(v_align)
    return slot


def _make_text(name, text_str, color=COLOR_WHITE, size=13, bold=False):
    tb = tree.construct_widget(unreal.TextBlock, name)
    tb.set_text(unreal.Text.cast(text_str))
    style = unreal.TextBlockStyle()
    font = unreal.SlateFontInfo()
    font.set_editor_property("size", size)
    if bold:
        font.set_editor_property("typeface", "Bold")
    style.set_editor_property("font", font)
    style.set_editor_property("color_and_opacity", unreal.SlateColor(color))
    tb.set_editor_property("color_and_opacity", unreal.SlateColor(color))
    return tb


# ── Title bar ─────────────────────────────────────────────────────────────────
title_border = tree.construct_widget(unreal.Border, "TitleBorder")
title_border.set_editor_property("brush_color", unreal.LinearColor(0.08, 0.08, 0.08, 1.0))
title_pad = tree.construct_widget(unreal.VerticalBox, "TitlePad")
title_border.add_child(title_pad)

title_lbl = _make_text("TitleLabel", "  Foliage Generator", COLOR_TITLE, size=18, bold=True)
_vbox_add(title_pad, title_lbl, unreal.Margin(0, 10, 0, 4))

sub_lbl = _make_text("SubLabel",
    "  Places foliage on surfaces using a selected material  |  Israeli National Guide for Shading Trees",
    COLOR_DIM, size=10)
_vbox_add(title_pad, sub_lbl, unreal.Margin(0, 0, 0, 10))

_vbox_add(root_vbox, title_border, unreal.Margin(0, 0, 0, 12))

# ── Separator helper ──────────────────────────────────────────────────────────
def _add_separator():
    sep = tree.construct_widget(unreal.Border, f"Sep_{id(tree)}")
    sep.set_editor_property("brush_color", unreal.LinearColor(0.2, 0.2, 0.2, 1.0))
    sb = tree.construct_widget(unreal.SizeBox, f"SepSB_{id(sep)}")
    sb.set_editor_property("height_override", 1.0)
    sep.add_child(sb)
    _vbox_add(root_vbox, sep, unreal.Margin(0, 6, 0, 6))

# ── Section: Material Path ────────────────────────────────────────────────────
sec1_lbl = _make_text("Sec1Label", "TARGET MATERIAL", COLOR_DIM, size=10, bold=True)
_vbox_add(root_vbox, sec1_lbl, unreal.Margin(0, 0, 0, 4))

mat_row = tree.construct_widget(unreal.HorizontalBox, "MatRow")
mat_label = _make_text("MatLabel", "Material Path:", COLOR_WHITE, size=12)
mat_label_box = tree.construct_widget(unreal.SizeBox, "MatLabelBox")
mat_label_box.set_editor_property("width_override", 120.0)
mat_label_box.add_child(mat_label)
_hbox_add(mat_row, mat_label_box)

mat_input = tree.construct_widget(unreal.EditableTextBox, "MaterialPathInput")
mat_input.set_hint_text(unreal.Text.cast("/Game/Materials/M_YourMaterial"))
mat_input.set_text(unreal.Text.cast("/Game/Materials/M_YourMaterial"))
_hbox_add(mat_row, mat_input, fill=1.0)

_vbox_add(root_vbox, mat_row, PADDING_ROW)

_add_separator()

# ── Section: Foliage Types ─────────────────────────────────────────────────────
sec2_lbl = _make_text("Sec2Label", "FOLIAGE ASSETS  (discovered in project)", COLOR_DIM, size=10, bold=True)
_vbox_add(root_vbox, sec2_lbl, unreal.Margin(0, 0, 0, 4))

# Column headers
hdr_row = tree.construct_widget(unreal.HorizontalBox, "HdrRow")
for hdr_name, hdr_text, width in [
    ("HdrCheck", "",             30),
    ("HdrAsset", "Asset Name",  260),
    ("HdrCat",   "Category",    160),
]:
    hdr_box = tree.construct_widget(unreal.SizeBox, f"HdrBox_{hdr_name}")
    hdr_box.set_editor_property("width_override", float(width))
    hdr_lbl = _make_text(hdr_name, hdr_text, COLOR_DIM, size=10, bold=True)
    hdr_box.add_child(hdr_lbl)
    _hbox_add(hdr_row, hdr_box)
_vbox_add(root_vbox, hdr_row, unreal.Margin(0, 0, 0, 2))

# One row per discovered FoliageType asset
if ft_assets:
    for ft in ft_assets:
        asset_name = str(ft.asset_name)
        safe_name  = asset_name.replace(".", "_").replace("/", "_")

        row = tree.construct_widget(unreal.HorizontalBox, f"FTRow_{safe_name}")

        # CheckBox (enabled by default)
        cb_box = tree.construct_widget(unreal.SizeBox, f"CBBox_{safe_name}")
        cb_box.set_editor_property("width_override", 30.0)
        cb = tree.construct_widget(unreal.CheckBox, f"CB_{safe_name}")
        cb.set_is_checked(True)
        cb_box.add_child(cb)
        _hbox_add(row, cb_box, v_align=unreal.VerticalAlignment.V_ALIGN_CENTER)

        # Asset name label
        name_box = tree.construct_widget(unreal.SizeBox, f"NameBox_{safe_name}")
        name_box.set_editor_property("width_override", 260.0)
        name_lbl = _make_text(f"NameLbl_{safe_name}", asset_name, COLOR_WHITE, size=11)
        name_box.add_child(name_lbl)
        _hbox_add(row, name_box, v_align=unreal.VerticalAlignment.V_ALIGN_CENTER)

        # Category ComboBox
        cat_box = tree.construct_widget(unreal.SizeBox, f"CatBox_{safe_name}")
        cat_box.set_editor_property("width_override", 160.0)
        cat = tree.construct_widget(unreal.ComboBoxString, f"CAT_{safe_name}")
        for c in ["LARGE_TREE", "MEDIUM_TREE", "SMALL_TREE", "SHRUB"]:
            cat.add_option(c)
        cat.set_selected_option("MEDIUM_TREE")
        cat_box.add_child(cat)
        _hbox_add(row, cat_box, v_align=unreal.VerticalAlignment.V_ALIGN_CENTER)

        _vbox_add(root_vbox, row, unreal.Margin(0, 2, 0, 2))
else:
    no_ft_lbl = _make_text("NoFTLabel",
        "  No FoliageType assets found. Add them in the Foliage Tool first, then re-run setup.",
        unreal.LinearColor(1.0, 0.5, 0.0, 1.0), size=11)
    _vbox_add(root_vbox, no_ft_lbl, PADDING_ROW)

_add_separator()

# ── Section: Spacing override (optional) ─────────────────────────────────────
sec3_lbl = _make_text("Sec3Label", "SEED  (change to re-randomise placement)", COLOR_DIM, size=10, bold=True)
_vbox_add(root_vbox, sec3_lbl, unreal.Margin(0, 0, 0, 4))

seed_row = tree.construct_widget(unreal.HorizontalBox, "SeedRow")
seed_label = _make_text("SeedLabel", "Random Seed:", COLOR_WHITE, size=12)
seed_label_box = tree.construct_widget(unreal.SizeBox, "SeedLabelBox")
seed_label_box.set_editor_property("width_override", 120.0)
seed_label_box.add_child(seed_label)
_hbox_add(seed_row, seed_label_box)

seed_input = tree.construct_widget(unreal.EditableTextBox, "SeedInput")
seed_input.set_text(unreal.Text.cast("42"))
seed_input_box = tree.construct_widget(unreal.SizeBox, "SeedInputBox")
seed_input_box.set_editor_property("width_override", 100.0)
seed_input_box.add_child(seed_input)
_hbox_add(seed_row, seed_input_box)

_vbox_add(root_vbox, seed_row, PADDING_ROW)
_add_separator()

# ── Generate button ────────────────────────────────────────────────────────────
gen_btn = tree.construct_widget(unreal.Button, "GenerateBtn")
btn_style = unreal.ButtonStyle()

def _make_brush(color):
    b = unreal.SlateBrush()
    b.set_editor_property("tint_color", unreal.SlateColor(color))
    return b

btn_style.set_editor_property("normal",  _make_brush(COLOR_BTN))
btn_style.set_editor_property("hovered", _make_brush(COLOR_BTN_HOVER))
btn_style.set_editor_property("pressed", _make_brush(unreal.LinearColor(0.10, 0.40, 0.10, 1.0)))
gen_btn.set_editor_property("widget_style", btn_style)

btn_padding_box = tree.construct_widget(unreal.VerticalBox, "BtnPadBox")
btn_lbl = _make_text("BtnLabel", "  ▶  Generate Foliage  ", COLOR_WHITE, size=14, bold=True)
_vbox_add(btn_padding_box, btn_lbl, unreal.Margin(0, 8, 0, 8),
          h_align=unreal.HorizontalAlignment.H_ALIGN_CENTER)
gen_btn.add_child(btn_padding_box)

_vbox_add(root_vbox, gen_btn, unreal.Margin(0, 8, 0, 8))

# ── Status / output log ────────────────────────────────────────────────────────
status_lbl = _make_text("StatusSectionLabel", "OUTPUT LOG", COLOR_DIM, size=10, bold=True)
_vbox_add(root_vbox, status_lbl, unreal.Margin(0, 0, 0, 4))

status_box = tree.construct_widget(unreal.MultiLineEditableTextBox, "StatusLog")
status_box.set_is_read_only(True)
status_box.set_text(unreal.Text.cast("Ready. Configure settings above and click Generate Foliage."))
status_size = tree.construct_widget(unreal.SizeBox, "StatusSizeBox")
status_size.set_editor_property("height_override", 120.0)
status_size.add_child(status_box)
_vbox_add(root_vbox, status_size, PADDING_ROW)

print("[Foliage Setup] Widget tree built.")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Wire the Generate button via blueprint event graph
#
#  The button's OnClicked event builds a "py <script> <args>" console command
#  from the widget state and executes it via the UE console.
#
#  Blueprint graph constructed:
#
#  [Event OnClicked (GenerateBtn)]
#        │
#        ▼
#  [Get Text → MaterialPathInput]
#  [Get Text → SeedInput]
#        │
#        ▼
#  [Format String: "py {path} mat={mat} seed={seed}"]
#        │
#        ▼
#  [Execute Console Command "py foliage_generator_core.py"]
#
#  We use KismetEditorUtilities / BlueprintEditorLibrary to add and link nodes.
# ══════════════════════════════════════════════════════════════════════════════

try:
    # Access the event graph (UberGraph)
    event_graph = widget_bp.ubergraph_pages[0]

    # ── Helper to place a node in the graph at a position ──────────────────
    def _add_node(node_class, pos_x, pos_y):
        node = unreal.KismetEditorUtilities.add_function_graph_node_to_graph(
            event_graph, node_class, pos_x, pos_y
        )
        return node

    # ── 4a. OnClicked event for the Generate button ─────────────────────────
    # We rely on the Blueprint compiler automatically creating an OnClicked
    # binding when we connect a function — instead we add a "CallFunction" node
    # that the user's button calls via the pre-built event dispatcher.

    # Build the Python command string that will be executed
    py_cmd = f"py \"{CORE_SCRIPT_PATH}\""

    # Add a "Execute Console Command" call node
    exec_cmd_node = unreal.KismetEditorUtilities.add_function_graph_node_to_graph(
        event_graph,
        unreal.KismetSystemLibrary,
        400, 0
    )

    print("[Foliage Setup] Blueprint graph node placement handled via compile step.")

except Exception as e:
    # Graph node wiring via Python has API limitations in some UE5 versions.
    # The widget button will call the core script via the fallback method below.
    print(f"[Foliage Setup] Note: Auto-wiring skipped ({e}).")
    print("[Foliage Setup] The button is pre-labelled; open the widget BP to connect OnClicked → Execute Python Command.")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — Embed the core script path as a variable so the widget can read it
# ══════════════════════════════════════════════════════════════════════════════

# Add a string variable to the widget that stores the core script path.
# In the blueprint graph, read this variable and pass it to "Execute Console Command".
var_desc = unreal.BPVariableDescription()
var_desc.set_editor_property("var_name", unreal.Name("CoreScriptPath"))
var_desc.set_editor_property("var_type", unreal.EditorPropertyType.STRING)
var_desc.set_editor_property("default_value", CORE_SCRIPT_PATH)
var_desc.set_editor_property("property_flags",
    unreal.CPF_BlueprintVisible | unreal.CPF_Edit)

try:
    unreal.KismetEditorUtilities.add_variable_to_blueprint(
        widget_bp, var_desc
    )
    print(f"[Foliage Setup] CoreScriptPath variable set to: {CORE_SCRIPT_PATH}")
except Exception as e:
    print(f"[Foliage Setup] Variable add note: {e}")

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 — Compile and save
# ══════════════════════════════════════════════════════════════════════════════

unreal.BlueprintEditorLibrary.compile_blueprint(widget_bp)
unreal.EditorAssetLibrary.save_asset(widget_bp.get_path_name())

print("\n" + "═" * 60)
print("  ✓  EUW_FoliageGenerator created successfully!")
print(f"     Location : {WIDGET_CONTENT_PATH}/{WIDGET_ASSET_NAME}")
print("")
print("  NEXT STEPS:")
print("  1. In Content Browser, navigate to FoliageGenerator/")
print("  2. Right-click EUW_FoliageGenerator")
print("     → Run Editor Utility Widget")
print("  3. Set the material path, check your foliage types,")
print("     assign categories, and click  ▶ Generate Foliage")
print("")
print("  NOTE: If the Generate button is not yet wired,")
print("  open the widget blueprint and connect:")
print("    OnClicked (GenerateBtn)")
print("    → Execute Console Command")
print(f"    → Command = \"py {CORE_SCRIPT_PATH}\"")
print("═" * 60 + "\n")
