// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Text/SMultiLineEditableText.h"

// ─── Data types ───────────────────────────────────────────────────────────────

/**
 * Foliage category that drives spacing / scale / alignment rules.
 * Plain C++ enum — NOT a UENUM (this header is not processed by UHT).
 */
enum class EFoliageCategory : uint8
{
    LargeTree  = 0,
    MediumTree = 1,
    SmallTree  = 2,
    Shrub      = 3,
};

/** Per-category placement rules (Israeli National Shading Tree Guide). */
struct FCategoryRules
{
    float Spacing;        // grid spacing (cm)
    float Jitter;         // ± fraction of spacing
    float ScaleMin;
    float ScaleMax;
    bool  bAlignToNormal; // false = Z-upright trees, true = slope-following shrubs
};

/** One row in the foliage-type list view. */
struct FFoliageEntry
{
    bool             bEnabled  = true;
    FString          AssetPath;           // /Game/Foliage/FT_...
    FString          AssetName;           // display label
    EFoliageCategory Category  = EFoliageCategory::MediumTree;

    // Per-entry overrides (0 = use category default)
    float OverrideSpacing  = 0.f;
    float OverrideScaleMin = 0.f;
    float OverrideScaleMax = 0.f;
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
    TSharedRef<SWidget> BuildSettingsSection();
    TSharedRef<SWidget> BuildButtonRow();
    TSharedRef<SWidget> BuildLogSection();

    TSharedRef<ITableRow> GenerateFoliageRow(
        TSharedPtr<FFoliageEntry> Entry,
        const TSharedRef<STableViewBase>& OwnerTable);

    // ── Actions ──────────────────────────────────────────────────────────────
    FReply OnRefreshClicked();
    FReply OnGenerateClicked();
    FReply OnClearClicked();

    void RefreshFoliageList();
    void RunGenerate();
    void RunClear();

    // ── Category combo helpers ────────────────────────────────────────────────
    TSharedRef<SWidget> MakeCategoryWidget(TSharedPtr<FString> Item);
    FText GetCategoryText(TSharedPtr<FFoliageEntry> Entry) const;

    // ── Logging ──────────────────────────────────────────────────────────────
    void AppendLog(const FString& Line);
    void ClearLog();

    // ── Category rules table ─────────────────────────────────────────────────
    static const FCategoryRules& GetRules(EFoliageCategory Cat);

    // ── State ────────────────────────────────────────────────────────────────
    FString                                           MaterialPath;
    TArray<TSharedPtr<FFoliageEntry>>                 FoliageEntries;
    TSharedPtr<SListView<TSharedPtr<FFoliageEntry>>>  FoliageListView;

    // Settings
    int32 Seed              = 42;
    float BuildingClearance = 200.f;  // cm
    bool  bCanopyCheck      = true;

    // Category combo options (shared across all rows)
    TArray<TSharedPtr<FString>> CategoryOptions;

    // Log widget
    TSharedPtr<SMultiLineEditableText> LogText;
    FString                            LogBuffer;
};
