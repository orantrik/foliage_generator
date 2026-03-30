"""
Foliage Generator — Widget Setup Script
========================================
Run this ONCE inside Unreal Engine 5 to create EUW_FoliageGenerator.

HOW TO RUN:
  UE5 Menu → Tools → Execute Python Script → select this file

WHAT IT CREATES:
  /Game/FoliageGenerator/EUW_FoliageGenerator  (opens automatically)

AFTER SETUP:
  Follow the printed instructions to add 7 named widgets in the
  Widget Designer — takes about 5 minutes, done once.
"""

import unreal

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

SCRIPTS_FOLDER = r"C:/Users/oranbenshaprut/Documents/Claude/foliage generator"

WIDGET_CONTENT_PATH = "/Game/FoliageGenerator"
WIDGET_ASSET_NAME   = "EUW_FoliageGenerator"

# ── Derived (do not edit) ─────────────────────────────────────────────────────
SCRIPTS_FOLDER  = SCRIPTS_FOLDER.replace("\\", "/")
CORE_SCRIPT     = f"{SCRIPTS_FOLDER}/foliage_generator_core.py"
PICK_SCRIPT     = f"{SCRIPTS_FOLDER}/foliage_pick_material.py"
CMD_PICK        = f'py "{PICK_SCRIPT}"'
CMD_GENERATE    = f'py "{CORE_SCRIPT}"'
FULL_ASSET_PATH = f"{WIDGET_CONTENT_PATH}/{WIDGET_ASSET_NAME}"

# ══════════════════════════════════════════════════════════════════════════════
#  CREATE WIDGET BLUEPRINT ASSET
# ══════════════════════════════════════════════════════════════════════════════

print("\n[Setup] Creating EUW_FoliageGenerator...")

if unreal.EditorAssetLibrary.does_asset_exist(FULL_ASSET_PATH):
    unreal.EditorAssetLibrary.delete_asset(FULL_ASSET_PATH)
    print("[Setup] Deleted previous version.")

factory    = unreal.EditorUtilityWidgetBlueprintFactory()
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
widget_bp   = asset_tools.create_asset(
    WIDGET_ASSET_NAME, WIDGET_CONTENT_PATH, None, factory
)

if widget_bp is None:
    raise RuntimeError(
        "Failed to create widget blueprint.\n"
        "Enable: Edit → Plugins → Blutility  and  Editor Scripting Utilities"
    )

unreal.EditorAssetLibrary.save_asset(widget_bp.get_path_name())

# Open the widget in the editor so the user can start building right away
unreal.AssetEditorSubsystem().open_editor_for_assets([widget_bp])

# ══════════════════════════════════════════════════════════════════════════════
#  PRINT SETUP INSTRUCTIONS
# ══════════════════════════════════════════════════════════════════════════════

W = 66
print("\n" + "═" * W)
print("  ✓  Widget created:  " + FULL_ASSET_PATH)
print("  (The Widget Designer should now be open)")
print("═" * W)
print("""
  ── STEP 1: Build the UI in the Designer tab (~5 min) ──────────

  In the Widget Designer, drag these from the Palette and
  NAME each widget exactly as shown (use the Details panel):

  ┌─ Vertical Box  (drag to canvas, set as root)
  │   ├─ EditableTextBox     → name: "MaterialPathInput"
  │   │    hint text: "Click Pick or paste /Game/... path"
  │   │
  │   ├─ Button              → name: "PickMaterialBtn"
  │   │    └─ TextBlock         text: "↗ Pick Material from Selection"
  │   │
  │   ├─ EditableTextBox     → name: "SeedInput"
  │   │    default text: "42"
  │   │
  │   ├─ MultiLineEditableTextBox  → name: "FoliageConfig"
  │   │    hint: "Click Generate once to auto-fill this list"
  │   │    height: ~120 px
  │   │
  │   ├─ Button              → name: "GenerateBtn"
  │   │    └─ TextBlock         text: "▶  Generate Foliage"
  │   │
  │   └─ MultiLineEditableTextBox  → name: "StatusLog"
  │        ✓ check "Is Read Only"
  │        height: ~120 px
  └─────────────────────────────────────────────────────────────

  ── STEP 2: Wire buttons in the Graph tab (~1 min) ─────────────

  Click the Designer's "Graph" tab.

  Button 1 — PickMaterialBtn:
    OnClicked (PickMaterialBtn)
      → Execute Console Command
""")
print(f'        Command = {CMD_PICK}')
print("""
  Button 2 — GenerateBtn:
    OnClicked (GenerateBtn)
      → Execute Console Command
""")
print(f'        Command = {CMD_GENERATE}')
print("""
  (Drag from the OnClicked exec pin → search "Execute Console
   Command" → paste the command string in the Command field)

  ── STEP 3: Compile & Save ─────────────────────────────────────

  Click "Compile" then "Save" in the widget blueprint toolbar.

  ── STEP 4: Use it ─────────────────────────────────────────────

  Right-click EUW_FoliageGenerator → Run Editor Utility Widget

  First run:
    • Leave FoliageConfig empty, click ▶ Generate Foliage
    • The StatusLog will print a ready-made list of all
      FoliageType assets found in your project
    • Copy that list into the FoliageConfig box
    • Edit categories if needed (LARGE_TREE / MEDIUM_TREE /
      SMALL_TREE / SHRUB), then generate again
""")
print("═" * W + "\n")
