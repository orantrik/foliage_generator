// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "UObject/WeakObjectPtr.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Text/SMultiLineEditableText.h"
#include "AssetRegistry/AssetData.h"

// Forward declarations — heavy includes stay in the .cpp
class FAssetThumbnailPool;
class FAssetThumbnail;
class SWidgetSwitcher;
class AActor;

// ─── Data types ───────────────────────────────────────────────────────────────

/**
 * Foliage category — drives spacing / scale / alignment defaults.
 *
 * Based on:
 *  • Israeli National Guide for Shading Trees in Built Environments (Nov 2020)
 *  • plant_planning.pdf Table 3 spacing bounds
 *
 * Category  |  Plant height |  Spacing   | Alignment
 * ----------|---------------|------------|----------
 * LargeTree |  > 10 m       | 10–12 m    | Z-upright
 * MediumTree|  6–10 m       |  7–10 m    | Z-upright
 * SmallTree |  3– 6 m       |  4– 6 m    | align-to-slope
 * Shrub     |  1– 3 m       | 1.5– 3 m   | align-to-slope
 * Flower    |  < 1 m        | 0.5– 1 m   | align-to-slope
 */
enum class EFoliageCategory : uint8
{
    LargeTree  = 0,
    MediumTree = 1,
    SmallTree  = 2,
    Shrub      = 3,
    Flower     = 4,
};

/** Per-category placement rules. */
struct FCategoryRules
{
    float Spacing;          // base grid spacing (cm)
    float Jitter;           // ± fraction of spacing
    float ScaleMin;
    float ScaleMax;
    bool  bAlignToNormal;   // false = Z-upright, true = slope-following

    // ── Spear collision height ────────────────────────────────────────────────
    // SpearHalfHeight — half the expected plant height (cm).
    // The sphere is swept from GroundSkip above the hit to SpearHalfHeight*2,
    // tracing a capsule-shaped volume the full height of the plant.
    // SpearRadius is now a per-widget user setting (see widget State below).
    float SpearHalfHeight;   // cm
};

/** One row in the foliage-type list view. */
struct FFoliageEntry
{
    bool             bEnabled    = true;
    FString          AssetPath;           // full object path
    FString          AssetName;           // raw asset name  (e.g. FT_Rosemary_vgvoacmia_Var1)
    FString          CommonName;          // extracted common name (e.g. "Rosemary")
    FAssetData       AssetData;           // full asset data (for thumbnail creation)
    EFoliageCategory Category    = EFoliageCategory::MediumTree;

    // Per-entry spacing + scale (pre-filled from category defaults)
    float OverrideSpacing  = 0.f;
    float OverrideScaleMin = 0.f;
    float OverrideScaleMax = 0.f;

    // Per-entry patch-size allowance.
    // Defaults mirror the cumulative rule (large plants only on large patches).
    // The user can override freely — e.g. force a shrub onto large patches only.
    bool bAllowOnLargePatch  = true;   // patch with longest dim ≥ PatchThresholdLarge
    bool bAllowOnMediumPatch = true;   // patch with longest dim ≥ PatchThresholdMedium
    bool bAllowOnSmallPatch  = true;   // patch with longest dim ≥ PatchThresholdSmall
    bool bAllowOnShrubPatch  = true;   // patch below PatchThresholdSmall

    // Thumbnail — created lazily in GenerateFoliageRow()
    TSharedPtr<FAssetThumbnail> Thumbnail;
};

// ─── Widget ───────────────────────────────────────────────────────────────────

class SFoliageGeneratorWidget : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SFoliageGeneratorWidget) {}
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);

private:
    // ── UI build helpers ─────────────────────────────────────────────────────
    TSharedRef<SWidget> BuildMaterialSection();
    TSharedRef<SWidget> BuildFoliageListSection();
    TSharedRef<SWidget> BuildSelectedTab();
    TSharedRef<SWidget> BuildSettingsSection();
    TSharedRef<SWidget> BuildKeepOutSection();
    TSharedRef<SWidget> BuildButtonRow();
    TSharedRef<SWidget> BuildLogSection();

    // ── Filter / sort ────────────────────────────────────────────────────────
    /** Rebuild FoliageEntries + EnabledEntries from AllFoliageEntries,
     *  applying the current name filter and sort order. */
    void ApplyFilterAndSort();

    TSharedRef<ITableRow> GenerateFoliageRow(
        TSharedPtr<FFoliageEntry>         Entry,
        const TSharedRef<STableViewBase>& OwnerTable);

    // ── Actions ──────────────────────────────────────────────────────────────
    FReply OnRefreshClicked();
    FReply OnGenerateClicked();
    FReply OnClearClicked();
    FReply OnDebugPointsClicked();

    void RefreshFoliageList();
    void RunGenerate();
    void RunClear();

    // ── Category combo helpers ────────────────────────────────────────────────
    TSharedRef<SWidget> MakeCategoryWidget(TSharedPtr<FString> Item);
    FText GetCategoryText(TSharedPtr<FFoliageEntry> Entry) const;

    /**
     * Infer the most appropriate category from keyword patterns in the asset name.
     * Based on plant_planning.pdf Table 3 and the Israeli National Shading Guide.
     */
    static EFoliageCategory AutoCategorize(const FString& AssetName);

    // ── Logging ──────────────────────────────────────────────────────────────
    void AppendLog(const FString& Line);
    void ClearLog();

    // ── Category rules table ─────────────────────────────────────────────────
    static const FCategoryRules& GetRules(EFoliageCategory Cat);

    // ── State ────────────────────────────────────────────────────────────────
    FString                                           MaterialPath;

    /** Complete list — all discovered FoliageType assets (never filtered). */
    TArray<TSharedPtr<FFoliageEntry>>                 AllFoliageEntries;
    /** Filtered + sorted view — source for the "All Plants" list view. */
    TArray<TSharedPtr<FFoliageEntry>>                 FoliageEntries;
    /** Only the currently enabled entries — source for the "Selected" tab list. */
    TArray<TSharedPtr<FFoliageEntry>>                 EnabledEntries;

    TSharedPtr<SListView<TSharedPtr<FFoliageEntry>>>  FoliageListView;
    TSharedPtr<SListView<TSharedPtr<FFoliageEntry>>>  SelectedListView;

    // Tab switcher
    TSharedPtr<SWidgetSwitcher>                       TabSwitcher;
    int32                                             ActiveTab = 0;

    // Filter / sort state
    FString PlantNameFilter;      // substring match against CommonName or AssetName
    bool    bSortByCategory = false;
    bool    bSortByName     = false;

    // Settings
    int32 Seed              = 42;
    bool  bCanopyCheck      = true;
    bool  bSpearCollision   = true;   // capsule sweep to detect buildings above each point
    bool  bUseSelection     = false;  // restrict to viewport-selected actors only
    int32 MaxInstancesPerType = 500;

    // Per-category building clearance (cm).
    // Added on top of SpearRadius* as an extra buffer from building walls.
    float ClearanceLargeTree  = 300.f;
    float ClearanceMediumTree = 200.f;
    float ClearanceSmallTree  = 100.f;
    float ClearanceShrub      =  50.f;
    float ClearanceFlower     =  20.f;

    // Per-category spear sphere radius (cm).
    // Sphere is swept from just above the ground to the canopy tip.
    // Wider = catches walls further away; narrower = tighter fit to trunk.
    float SpearRadiusLarge  = 120.f;
    float SpearRadiusMedium =  90.f;
    float SpearRadiusSmall  =  60.f;
    float SpearRadiusShrub  =  35.f;
    float SpearRadiusFlower =  15.f;

    // Per-category canopy radius for building-detection capsule (cm).
    // The capsule wraps the FULL plant volume (trunk + leaves + canopy spread).
    // Shrubs/Flowers skip building detection entirely, so no field needed.
    float CanopyRadiusLarge  = 300.f;
    float CanopyRadiusMedium = 200.f;
    float CanopyRadiusSmall  = 120.f;

    // Minimum actor Z half-extent (cm) to be considered a building.
    // Hit actors shorter than this are treated as flat ground meshes
    // (roads, sidewalks, kerbs) and do NOT block placement.
    float SpearFlatThreshold = 25.f;

    // Per-category slope-avoidance range (degrees from horizontal).
    // If SlopeMax > SlopeMin and the triangle's slope falls within
    // [SlopeMin, SlopeMax], the candidate is rejected for that category.
    // Default [0, 0] = feature inert. Example: Large Trees [25, 90]
    // keeps big trees off steep hillsides.
    float SlopeBlockMinLarge  = 0.f,  SlopeBlockMaxLarge  = 0.f;
    float SlopeBlockMinMedium = 0.f,  SlopeBlockMaxMedium = 0.f;
    float SlopeBlockMinSmall  = 0.f,  SlopeBlockMaxSmall  = 0.f;
    float SlopeBlockMinShrub  = 0.f,  SlopeBlockMaxShrub  = 0.f;
    float SlopeBlockMinFlower = 0.f,  SlopeBlockMaxFlower = 0.f;

    // ── Keep-out actors ──────────────────────────────────────────────────────
    // User-marked meshes that foliage should stay away from.  Placement is
    // rejected when a candidate point is within KeepOutBufferRadius (cm) of
    // any listed actor's world-space AABB.
    bool  bKeepOutEnabled     = true;
    float KeepOutBufferRadius = 100.f;
    TArray<TWeakObjectPtr<AActor>> KeepOutActors;
    TSharedPtr<SListView<TWeakObjectPtr<AActor>>> KeepOutListView;

    // Handlers
    FReply OnAddSelectedKeepOut();
    FReply OnClearKeepOut();
    FReply OnVisualizeKeepOut();
    FReply OnRemoveKeepOutRow(TWeakObjectPtr<AActor> Actor);
    TSharedRef<ITableRow> GenerateKeepOutRow(
        TWeakObjectPtr<AActor>              Actor,
        const TSharedRef<STableViewBase>&   OwnerTable);

    // Patch-size filtering
    bool  bPatchSizeFilter     = true;
    float PatchThresholdLarge  = 1000.f;  // cm  (≈ 10 m)
    float PatchThresholdMedium =  700.f;  // cm  (≈  7 m)
    float PatchThresholdSmall  =  300.f;  // cm  (≈  3 m)

    // Category combo options (same array reused across all rows)
    TArray<TSharedPtr<FString>> CategoryOptions;

    // Shared thumbnail pool — used for both the material picker and list rows
    TSharedPtr<FAssetThumbnailPool> ThumbnailPool;

    // Log
    TSharedPtr<SMultiLineEditableText> LogText;
    FString                            LogBuffer;
};
