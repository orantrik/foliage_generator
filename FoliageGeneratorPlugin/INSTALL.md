# Foliage Generator Plugin — Installation & Usage

## Requirements
- Unreal Engine 5.0 or later (C++ project, not Blueprints-only)
- Python scripts are no longer needed after this plugin is installed

---

## Installation

1. **Copy the plugin folder** into your UE5 project:
   ```
   YourProject/Plugins/FoliageGenerator/
   ├── FoliageGenerator.uplugin
   └── Source/
       └── FoliageGenerator/
           ├── FoliageGenerator.Build.cs
           ├── Public/
           │   ├── FoliageGeneratorModule.h
           │   └── SFoliageGeneratorWidget.h
           └── Private/
               ├── FoliageGeneratorModule.cpp
               └── SFoliageGeneratorWidget.cpp
   ```

2. **Right-click your `.uproject` file** → "Generate Visual Studio project files"

3. **Build in Visual Studio** (or Rider): Build → Build Solution
   (or open the `.uproject` — UE5 will offer to compile automatically)

4. **Open the level** you want to place foliage on.

5. **Open the panel**: Look for the **"Foliage Generator"** button in the Level Editor
   toolbar (right side), or use
   `Window → Foliage Generator`

---

## Workflow

### Step 1 — Set the target material
Paste the material's Content Browser Reference into the **Material Path** field.
To get it: right-click the material in Content Browser → **Copy Reference**.

Example: `/Game/Materials/M_GroundSurface.M_GroundSurface`

### Step 2 — Check foliage types
The list is auto-populated from all `FoliageType_InstancedStaticMesh` assets in your project.
Click **Refresh List** after importing new FT_ assets.

For each entry:
- **Checkbox** — enable/disable this type
- **Category** — controls spacing, scale, and surface alignment:
  | Category    | Spacing | Scale       | Alignment |
  |-------------|---------|-------------|-----------|
  | Large Tree  | 12.5 m  | 0.90 – 1.10 | Z-upright |
  | Medium Tree | 8.5 m   | 0.85 – 1.15 | Z-upright |
  | Small Tree  | 5.5 m   | 0.80 – 1.20 | Normal    |
  | Shrub       | 2.25 m  | 0.70 – 1.30 | Normal    |
- **Spacing / Scale overrides** — leave at 0 to use category defaults

### Step 3 — Adjust settings
- **Seed** — change to get a different random layout
- **Building Clearance** — reject points too close to walls (cm)
- **Canopy Collision Check** — skip points already covered by another plant

### Step 4 — Click Generate Foliage
Plants are placed **directly into the Foliage Mode palette** — this is the key
advantage over the Python version. After generation:
- Switch to Foliage Mode (Shift+4) to see all types in the palette
- Use the Foliage paint brush to add/remove instances interactively

### Clear Foliage
Removes **all** instances from the level's `InstancedFoliageActor`.
`FoliageType` assets are preserved. This cannot be undone.

---

## Compilation Notes

### UE5.0 vs 5.1+ API difference
`FFoliageInfo::AddInstances` signature is compatible across both versions.
If you see a compile error on `AddInstances`, try adding the `EAddInstanceFlags::NoFlags` argument:
```cpp
FoliageInfo->AddInstances(IFA, Instances, FFoliageInfo::EAddInstanceFlags::NoFlags);
```

### `FAppStyle` vs `FEditorStyle`
The widget uses `FAppStyle` (UE5.1+). On UE5.0 it falls back to `FEditorStyle`
via the `FG_STYLE` define in `SFoliageGeneratorWidget.cpp`. If you see a compile
error, ensure your UE5 version is correct.

### Missing `WorkspaceMenuStructure` module
If compilation fails on `WorkspaceMenuStructure`, remove it from `Build.cs` and
remove the matching `#include` in `FoliageGeneratorModule.cpp`.
