// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.
//
// SFoliageGeneratorWidget.cpp
// ─────────────────────────────────────────────────────────────────────────────
// Foliage Generator panel — Slate widget driving procedural foliage placement.
//
// KEY FEATURES:
//  • Built-in material asset picker (drag-drop or browse button)
//  • Per-row plant thumbnails in the foliage type list
//  • Select All / Deselect All
//  • Auto-categorisation from keyword matching (National Shading Guide + plant_planning.pdf)
//  • Direct IFA C++ calls → plants appear in Foliage Mode palette immediately

#include "SFoliageGeneratorWidget.h"

// ── Foliage API ───────────────────────────────────────────────────────────────
#include "InstancedFoliageActor.h"
#include "FoliageType_InstancedStaticMesh.h"
#include "FoliageType.h"

// ── Debug visualization ───────────────────────────────────────────────────────
#include "DrawDebugHelpers.h"

// ── Engine / Editor ───────────────────────────────────────────────────────────
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Editor.h"
#include "Selection.h"
#include "Materials/MaterialInterface.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Misc/ScopedSlowTask.h"
#include "StaticMeshResources.h"

// ── Thumbnails ────────────────────────────────────────────────────────────────
#include "AssetThumbnail.h"             // FAssetThumbnail, FAssetThumbnailPool

// ── Material picker ───────────────────────────────────────────────────────────
#include "PropertyCustomizationHelpers.h"   // SObjectPropertyEntryBox

// ── Slate ─────────────────────────────────────────────────────────────────────
#include "Framework/Application/SlateApplication.h"
#include "Widgets/Layout/SWidgetSwitcher.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SWrapBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SSpinBox.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Views/SListView.h"
#include "Widgets/Views/STableRow.h"
#include "Widgets/Text/SMultiLineEditableText.h"
#include "Styling/AppStyle.h"

#define LOCTEXT_NAMESPACE "SFoliageGeneratorWidget"
#define FG_STYLE FAppStyle::Get()

// ─── Category rules — National Shading Guide + plant_planning.pdf Table 3 ────
// LargeTree : H > 10 m  | spacing 1100 cm | scale 0.90–1.10 | Z-upright
// MediumTree: H  6–10 m | spacing  850 cm | scale 0.85–1.15 | Z-upright
// SmallTree : H  3– 6 m | spacing  500 cm | scale 0.80–1.20 | align-slope
// Shrub     : H  1– 3 m | spacing  220 cm | scale 0.70–1.30 | align-slope
// Flower    : H  < 1 m  | spacing   80 cm | scale 0.60–1.40 | align-slope
//
// Spear capsule — vertical capsule swept from ground to canopy tip.
// SpearRadius     = representative trunk/crown half-width at mid-height (cm).
// SpearHalfHeight = half the expected plant height (cm); capsule center sits
//                   at this height above the ground-hit point.
//
// Category   |  Plant H  | SpearRadius | SpearHalfHeight
// -----------|-----------|-------------|----------------
// LargeTree  |  ~1500 cm |   120 cm    |   750 cm
// MediumTree |   ~900 cm |    90 cm    |   450 cm
// SmallTree  |   ~450 cm |    60 cm    |   225 cm
// Shrub      |   ~150 cm |    35 cm    |    75 cm
// Flower     |    ~50 cm |    15 cm    |    25 cm

static const FCategoryRules GCategoryRules[] =
{
    //              spacing  jitter  scaleMin  scaleMax  alignNormal  spearHH
    /* LargeTree  */ { 1100.f, 0.20f,  0.90f,    1.10f,    false,      750.f },
    /* MediumTree */ {  850.f, 0.20f,  0.85f,    1.15f,    false,      450.f },
    /* SmallTree  */ {  500.f, 0.20f,  0.80f,    1.20f,    true,       225.f },
    /* Shrub      */ {  220.f, 0.25f,  0.70f,    1.30f,    true,        75.f },
    /* Flower     */ {   80.f, 0.30f,  0.60f,    1.40f,    true,        25.f },
};

/*static*/ const FCategoryRules& SFoliageGeneratorWidget::GetRules(EFoliageCategory Cat)
{
    return GCategoryRules[static_cast<int32>(Cat)];
}

// ─── AutoCategorize ───────────────────────────────────────────────────────────
// Keyword tables derived from:
//   • Israeli National Guide for Shading Trees (Nov 2020) species lists
//   • plant_planning.pdf Table 3 height / canopy data

/*static*/ EFoliageCategory SFoliageGeneratorWidget::AutoCategorize(const FString& Name)
{
    const FString N = Name.ToLower();

    // ── Large Trees (H > 10 m, spacing 10–12 m) ───────────────────────────────
    // Dominant canopy trees — palms, eucalyptus, ficus, conifers, oaks, etc.
    static const TArray<FString> LargeKeywords =
    {
        TEXT("palm"), TEXT("phoenix"), TEXT("washingtonia"), TEXT("brahea"),
        TEXT("livistona"), TEXT("chamaerops"),
        TEXT("eucalyptus"), TEXT("eucalypt"),
        TEXT("ficus"),
        TEXT("platanus"),
        TEXT("pinus"), TEXT("pine"),
        TEXT("cupressus"), TEXT("cypress"),
        TEXT("populus"), TEXT("poplar"),
        TEXT("quercus"), TEXT("oak"),
        TEXT("jacaranda"),
        TEXT("acacia_large"), TEXT("vachellia"),
        TEXT("ceratonia"), TEXT("carob"),
        TEXT("casuarina"),
        TEXT("liquidambar"),
        TEXT("tipuana"),
        TEXT("tabebuia"),
        TEXT("albizzia"), TEXT("albizia"),
        TEXT("delonix"),
        TEXT("schinus_molle"),
        TEXT("peltophorum"),
    };

    // ── Medium Trees (H 6–10 m, spacing 7–10 m) ───────────────────────────────
    // Flowering/fruiting trees, olives, pistachios, ornamentals
    static const TArray<FString> MediumKeywords =
    {
        TEXT("olea"), TEXT("olive"),
        TEXT("pistacia"), TEXT("pistachio"),
        TEXT("cercis"), TEXT("judas"),
        TEXT("bauhinia"),
        TEXT("lagerstroemia"), TEXT("crepe"), TEXT("crapemyrtle"),
        TEXT("erythrina"),
        TEXT("citrus"), TEXT("lemon"), TEXT("orange"), TEXT("mandarin"),
        TEXT("punica"), TEXT("pomegranate"),
        TEXT("prunus"), TEXT("cherry"), TEXT("almond"),
        TEXT("pyrus"), TEXT("pear"),
        TEXT("malus"), TEXT("apple"),
        TEXT("melia"),
        TEXT("cassia"),
        TEXT("callistemon"),
        TEXT("metrosideros"),
        TEXT("schinus_terebinthifolius"), TEXT("peppercorn"),
        TEXT("tamarix"),
        TEXT("styrax"),
        TEXT("vitex"),
    };

    // ── Small Trees / Saplings (H 3–6 m, spacing 4–6 m) ─────────────────────
    static const TArray<FString> SmallKeywords =
    {
        TEXT("nerium"), TEXT("oleander"),
        TEXT("lantana_arborescens"),
        TEXT("laurus"), TEXT("bay"),
        TEXT("myrtus"), TEXT("myrtle"),
        TEXT("arbutus"),
        TEXT("rhamnus"),
        TEXT("elaeagnus"),
        TEXT("photinia"),
        TEXT("pittosporum"),
        TEXT("teucrium"),
        TEXT("acacia_smalltree"),
    };

    // ── Flowers / Ground cover (H < 1 m, spacing 0.5–1 m) ───────────────────
    static const TArray<FString> FlowerKeywords =
    {
        TEXT("flower"), TEXT("floral"),
        TEXT("tulip"), TEXT("daffodil"), TEXT("narcissus"),
        TEXT("crocus"), TEXT("hyacinth"),
        TEXT("petunia"), TEXT("pansy"), TEXT("viola"),
        TEXT("marigold"), TEXT("tagetes"),
        TEXT("zinnia"), TEXT("dahlia"), TEXT("gazania"),
        TEXT("poppy"), TEXT("papaver"),
        TEXT("cyclamen"),
        TEXT("impatiens"), TEXT("begonia"),
        TEXT("lobelia"), TEXT("alyssum"),
        TEXT("chrysanthemum"), TEXT("daisy"),
        TEXT("geranium"), TEXT("pelargonium"),
        TEXT("verbena"), TEXT("portulaca"),
        TEXT("primrose"), TEXT("primula"),
        TEXT("snapdragon"), TEXT("antirrhinum"),
        TEXT("groundcover"), TEXT("ground_cover"),
        TEXT("moss"), TEXT("clover"), TEXT("trifolium"),
    };

    // Check large first (highest priority)
    for (const FString& KW : LargeKeywords)
        if (N.Contains(KW)) return EFoliageCategory::LargeTree;

    for (const FString& KW : MediumKeywords)
        if (N.Contains(KW)) return EFoliageCategory::MediumTree;

    for (const FString& KW : SmallKeywords)
        if (N.Contains(KW)) return EFoliageCategory::SmallTree;

    for (const FString& KW : FlowerKeywords)
        if (N.Contains(KW)) return EFoliageCategory::Flower;

    // Everything else → Shrub (ground cover, ornamentals, succulents)
    // Includes: Bird_Of_Paradise, Agave, Lavender, Rosemary, Bougainvillea,
    //           Agapanthus, Aloe, Salvia, Plumbago, Lupin, etc.
    return EFoliageCategory::Shrub;
}

// ─── Patch-allowance defaults ─────────────────────────────────────────────────
// Sets the four bAllowOn*Patch flags to match the cumulative rule:
//   LargeTree  → large patches only
//   MediumTree → large + medium
//   SmallTree  → large + medium + small
//   Shrub      → all four (L/M/S/Shrub)
//   Flower     → all four (same as Shrub — they occupy the smallest patches too)
// Called when an entry is first created and when the user changes its category.
static void ResetPatchDefaults(FFoliageEntry* E)
{
    const int32 Idx = static_cast<int32>(E->Category);
    // Allowed on a patch type when plant_idx >= patch_idx
    // (larger plants are only welcome on bigger patches).
    // Flower (idx=4) is >= Shrub (idx=3) for all comparisons → allowed everywhere.
    E->bAllowOnLargePatch  = (Idx >= static_cast<int32>(EFoliageCategory::LargeTree));  // always true
    E->bAllowOnMediumPatch = (Idx >= static_cast<int32>(EFoliageCategory::MediumTree)); // Medium, Small, Shrub, Flower
    E->bAllowOnSmallPatch  = (Idx >= static_cast<int32>(EFoliageCategory::SmallTree));  // Small, Shrub, Flower
    E->bAllowOnShrubPatch  = (Idx >= static_cast<int32>(EFoliageCategory::Shrub));      // Shrub, Flower
}

// ─── Common-name extractor ────────────────────────────────────────────────────
// Extracts the human-readable plant name from an asset name.
//   "FT_Rosemary_vgvoacmia_Var1"  →  "Rosemary"
//   "FT_Amaryllis_sgzkv_Var1_lod3" → "Amaryllis"
//   "dracena_palm_mesh_FoliageType"→  "Dracena"
static FString ExtractCommonName(const FString& AssetName)
{
    FString S = AssetName;

    // Strip standard "FT_" or "ft_" prefix
    if (S.StartsWith(TEXT("FT_"), ESearchCase::IgnoreCase))
        S = S.Mid(3);

    // Take everything up to the first underscore
    int32 Idx;
    if (S.FindChar(TEXT('_'), Idx) && Idx > 0)
        S = S.Left(Idx);

    // Capitalise first letter for readability
    if (!S.IsEmpty())
        S[0] = FChar::ToUpper(S[0]);

    return S;
}

// ─── Section-header helper ────────────────────────────────────────────────────

static TSharedRef<SWidget> MakeSectionHeader(const FText& Title)
{
    return SNew(SBorder)
        .BorderImage(FG_STYLE.GetBrush("ToolPanel.GroupBorder"))
        .Padding(FMargin(6.f, 4.f))
        [
            SNew(STextBlock)
            .Text(Title)
            .TextStyle(FG_STYLE, "SmallText.Subdued")
        ];
}

// ─── Construct ────────────────────────────────────────────────────────────────

void SFoliageGeneratorWidget::Construct(const FArguments& InArgs)
{
    // Thumbnail pool — 512 slots, allow async rendering
    ThumbnailPool = MakeShareable(new FAssetThumbnailPool(512, /*InAreRealThumbnailsAllowed=*/true));

    // Category combo labels
    CategoryOptions.Add(MakeShareable(new FString(TEXT("Large Tree"))));
    CategoryOptions.Add(MakeShareable(new FString(TEXT("Medium Tree"))));
    CategoryOptions.Add(MakeShareable(new FString(TEXT("Small Tree"))));
    CategoryOptions.Add(MakeShareable(new FString(TEXT("Shrub"))));
    CategoryOptions.Add(MakeShareable(new FString(TEXT("Flower"))));

    RefreshFoliageList();

    // ── Helper: styled tab button (CheckBox behaves as a toggle tab) ──────────
    auto MakeTabBtn = [this](const FText& Label, int32 Idx) -> TSharedRef<SWidget>
    {
        return SNew(SCheckBox)
            .Style(FG_STYLE, "ToggleButtonCheckbox")
            .Padding(FMargin(12.f, 4.f))
            .IsChecked_Lambda([this, Idx]()
            {
                return ActiveTab == Idx
                    ? ECheckBoxState::Checked
                    : ECheckBoxState::Unchecked;
            })
            .OnCheckStateChanged_Lambda([this, Idx](ECheckBoxState S)
            {
                if (S == ECheckBoxState::Checked)
                {
                    ActiveTab = Idx;
                    if (TabSwitcher.IsValid())
                        TabSwitcher->SetActiveWidgetIndex(Idx);
                }
            })
            [ SNew(STextBlock).Text(Label).TextStyle(FG_STYLE, "SmallText") ];
    };

    ChildSlot
    [
        SNew(SVerticalBox)

        // ── Tab bar ──────────────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight()
        [
            SNew(SBorder)
            .BorderImage(FG_STYLE.GetBrush("ToolPanel.GroupBorder"))
            .Padding(FMargin(4.f, 4.f, 4.f, 0.f))
            [
                SNew(SHorizontalBox)

                + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 2.f, 0.f))
                [ MakeTabBtn(LOCTEXT("TabAll", "All Plants"), 0) ]

                + SHorizontalBox::Slot().AutoWidth()
                [
                    // "Selected" tab shows a live count of enabled entries
                    SNew(SCheckBox)
                    .Style(FG_STYLE, "ToggleButtonCheckbox")
                    .Padding(FMargin(12.f, 4.f))
                    .IsChecked_Lambda([this]()
                    {
                        return ActiveTab == 1
                            ? ECheckBoxState::Checked
                            : ECheckBoxState::Unchecked;
                    })
                    .OnCheckStateChanged_Lambda([this](ECheckBoxState S)
                    {
                        if (S == ECheckBoxState::Checked)
                        {
                            ActiveTab = 1;
                            if (TabSwitcher.IsValid())
                                TabSwitcher->SetActiveWidgetIndex(1);
                        }
                    })
                    [
                        SNew(STextBlock)
                        .TextStyle(FG_STYLE, "SmallText")
                        .Text_Lambda([this]()
                        {
                            int32 N = 0;
                            for (const auto& E : AllFoliageEntries)
                                if (E->bEnabled) ++N;
                            return FText::Format(
                                LOCTEXT("TabSel", "Selected  ({0})"), FText::AsNumber(N));
                        })
                    ]
                ]
            ]
        ]

        // ── Tab content ──────────────────────────────────────────────────────
        + SVerticalBox::Slot().FillHeight(1.f)
        [
            SAssignNew(TabSwitcher, SWidgetSwitcher)

            // ── Tab 0 : All Plants ────────────────────────────────────────────
            + SWidgetSwitcher::Slot()
            [
                SNew(SScrollBox)
                + SScrollBox::Slot().Padding(6.f)
                [
                    SNew(SVerticalBox)

                    + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 4.f))
                    [ BuildMaterialSection() ]

                    + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 4.f))
                    [ BuildFoliageListSection() ]

                    + SVerticalBox::Slot().AutoHeight()
                    [ BuildSettingsSection() ]
                ]
            ]

            // ── Tab 1 : Selected (enabled) Plants ────────────────────────────
            + SWidgetSwitcher::Slot()
            [
                BuildSelectedTab()
            ]
        ]

        // ── Always-visible: Generate / Clear + Log ───────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(6.f, 4.f, 6.f, 0.f))
        [ BuildButtonRow() ]

        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(6.f, 0.f, 6.f, 4.f))
        [ BuildLogSection() ]
    ];

    // ActiveWidgetIndex is no longer a constructor argument in UE5.7 —
    // set it explicitly after the widget tree is built.
    if (TabSwitcher.IsValid())
        TabSwitcher->SetActiveWidgetIndex(0);
}

// ─── Material section ─────────────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildMaterialSection()
{
    return SNew(SVerticalBox)
        + SVerticalBox::Slot().AutoHeight()
        [
            MakeSectionHeader(LOCTEXT("MatHeader", "Target Surface Material"))
        ]
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f))
        [
            SNew(SHorizontalBox)

            // Inline asset picker — supports drag-drop, browse button, thumbnail
            + SHorizontalBox::Slot().FillWidth(1.f)
            [
                SNew(SObjectPropertyEntryBox)
                .AllowedClass(UMaterialInterface::StaticClass())
                .ObjectPath_Lambda([this]() -> FString { return MaterialPath; })
                .OnObjectChanged_Lambda([this](const FAssetData& AD)
                {
                    MaterialPath = AD.IsValid() ? AD.GetObjectPathString() : FString();
                })
                .ThumbnailPool(ThumbnailPool)
                .ToolTipText(LOCTEXT("MatTip",
                    "Drag a material from the Content Browser here, or click the\n"
                    "browse button. Only actors whose mesh uses this material will\n"
                    "be targeted for foliage placement."))
            ]

            // Helper label
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(6.f, 0.f, 0.f, 0.f))
            [
                SNew(STextBlock)
                .Text(LOCTEXT("MatHint", "← drag from Content Browser"))
                .TextStyle(FG_STYLE, "SmallText.Subdued")
            ]
        ];
}

// ─── Foliage list section ─────────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildFoliageListSection()
{
    return SNew(SVerticalBox)

        // Section header
        + SVerticalBox::Slot().AutoHeight()
        [
            MakeSectionHeader(LOCTEXT("FTHeader",
                "Foliage Types  (auto-discovered · defaults from National Shading Guide)"))
        ]

        // Select All / Deselect All + count
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 2.f))
        [
            SNew(SHorizontalBox)

            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [
                SNew(SButton)
                .Text(LOCTEXT("SelectAll", "Select All"))
                .OnClicked_Lambda([this]() -> FReply
                {
                    for (auto& E : AllFoliageEntries) E->bEnabled = true;
                    ApplyFilterAndSort();
                    return FReply::Handled();
                })
            ]

            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 12.f, 0.f))
            [
                SNew(SButton)
                .Text(LOCTEXT("DeselectAll", "Deselect All"))
                .OnClicked_Lambda([this]() -> FReply
                {
                    for (auto& E : AllFoliageEntries) E->bEnabled = false;
                    ApplyFilterAndSort();
                    return FReply::Handled();
                })
            ]

            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
            [
                SNew(STextBlock)
                .Text_Lambda([this]()
                {
                    int32 Enabled = 0;
                    for (const auto& E : AllFoliageEntries) if (E->bEnabled) ++Enabled;
                    return FText::Format(
                        LOCTEXT("FTCount", "{0} / {1} enabled  ({2} shown)"),
                        FText::AsNumber(Enabled),
                        FText::AsNumber(AllFoliageEntries.Num()),
                        FText::AsNumber(FoliageEntries.Num()));
                })
                .TextStyle(FG_STYLE, "SmallText.Subdued")
            ]

            + SHorizontalBox::Slot().AutoWidth()
            [
                SNew(SButton)
                .Text(LOCTEXT("RefreshBtn", "↻  Refresh List"))
                .ToolTipText(LOCTEXT("RefreshTip",
                    "Re-scans the project AssetRegistry for FoliageType assets.\n"
                    "Run after importing new plant meshes."))
                .OnClicked(this, &SFoliageGeneratorWidget::OnRefreshClicked)
            ]
        ]

        // ── Name filter + sort buttons ────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 2.f))
        [
            SNew(SHorizontalBox)

            // Search box
            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [
                SNew(SEditableTextBox)
                .HintText(LOCTEXT("FilterHint", "Filter by name  (e.g. Rosemary, Palm, Shrub…)"))
                .OnTextChanged_Lambda([this](const FText& T)
                {
                    PlantNameFilter = T.ToString();
                    ApplyFilterAndSort();
                })
                .ToolTipText(LOCTEXT("FilterTip",
                    "Type any part of the plant's common name to narrow the list.\n"
                    "Matches both the short name (Rosemary) and the full asset name."))
            ]

            // Sort by Category toggle
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [
                SNew(SButton)
                .Text_Lambda([this]()
                {
                    return bSortByCategory
                        ? LOCTEXT("SortCatOn",  "Cat ▲ ✓")
                        : LOCTEXT("SortCatOff", "Cat ▲");
                })
                .ToolTipText(LOCTEXT("SortCatTip",
                    "Toggle sort by category (Large → Medium → Small → Shrub).\n"
                    "If both sorts are active, category takes priority."))
                .OnClicked_Lambda([this]() -> FReply
                {
                    bSortByCategory = !bSortByCategory;
                    ApplyFilterAndSort();
                    return FReply::Handled();
                })
            ]

            // Sort by Name toggle
            + SHorizontalBox::Slot().AutoWidth()
            [
                SNew(SButton)
                .Text_Lambda([this]()
                {
                    return bSortByName
                        ? LOCTEXT("SortNameOn",  "A→Z ✓")
                        : LOCTEXT("SortNameOff", "A→Z");
                })
                .ToolTipText(LOCTEXT("SortNameTip",
                    "Toggle sort by common plant name (A → Z)."))
                .OnClicked_Lambda([this]() -> FReply
                {
                    bSortByName = !bSortByName;
                    ApplyFilterAndSort();
                    return FReply::Handled();
                })
            ]
        ]

        // Column header bar
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 2.f))
        [
            SNew(SBorder)
            .BorderImage(FG_STYLE.GetBrush("ToolPanel.GroupBorder"))
            .Padding(FMargin(72.f, 2.f, 2.f, 2.f))  // indent past thumbnail
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().MaxWidth(22.f)
                [ SNew(STextBlock).Text(FText::GetEmpty()) ]
                + SHorizontalBox::Slot().FillWidth(1.f)
                [ SNew(STextBlock).Text(LOCTEXT("ColName","Plant")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(110.f)
                [ SNew(STextBlock).Text(LOCTEXT("ColCat","Category")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(72.f)
                [ SNew(STextBlock).Text(LOCTEXT("ColSpc","Spacing")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(60.f)
                [ SNew(STextBlock).Text(LOCTEXT("ColScMin","Sc.Min")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(60.f)
                [ SNew(STextBlock).Text(LOCTEXT("ColScMax","Sc.Max")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(120.f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("ColPatches","Allowed Patches"))
                    .TextStyle(FG_STYLE,"SmallText.Subdued")
                    .ToolTipText(LOCTEXT("ColPatchesTip",
                        "Which patch sizes this plant is allowed to appear on.\n"
                        "L = Large patch  |  M = Medium  |  S = Small  |  Sh = Shrub-only\n"
                        "Defaults reset automatically when you change the category."))
                ]
            ]
        ]

        // Scrollable list (each row is 72 px tall for the thumbnail)
        + SVerticalBox::Slot().MaxHeight(400.f)
        [
            SAssignNew(FoliageListView, SListView<TSharedPtr<FFoliageEntry>>)
            .ListItemsSource(&FoliageEntries)
            .OnGenerateRow(this, &SFoliageGeneratorWidget::GenerateFoliageRow)
            .SelectionMode(ESelectionMode::None)
            .ScrollbarVisibility(EVisibility::Visible)
        ];
}

// ─── List row ─────────────────────────────────────────────────────────────────

TSharedRef<ITableRow> SFoliageGeneratorWidget::GenerateFoliageRow(
    TSharedPtr<FFoliageEntry>         Entry,
    const TSharedRef<STableViewBase>& OwnerTable)
{
    // Create per-entry thumbnail (64×64 px)
    if (!Entry->Thumbnail.IsValid() && Entry->AssetData.IsValid())
    {
        Entry->Thumbnail = MakeShareable(
            new FAssetThumbnail(Entry->AssetData, 64, 64, ThumbnailPool));
    }

    TSharedPtr<SWidget> ThumbWidget;
    if (Entry->Thumbnail.IsValid())
    {
        FAssetThumbnailConfig ThumbCfg;
        ThumbCfg.bAllowFadeIn = true;
        ThumbWidget = Entry->Thumbnail->MakeThumbnailWidget(ThumbCfg);
    }
    else
    {
        ThumbWidget = SNew(SBox)
            .WidthOverride(64.f).HeightOverride(64.f)
            [SNew(STextBlock).Text(LOCTEXT("NoThumb", "?"))];
    }

    return SNew(STableRow<TSharedPtr<FFoliageEntry>>, OwnerTable)
        .Padding(FMargin(0.f, 1.f))
        [
            SNew(SHorizontalBox)

            // ── Thumbnail ──────────────────────────────────────────────────────
            + SHorizontalBox::Slot().AutoWidth()
            [
                SNew(SBox).WidthOverride(64.f).HeightOverride(64.f)
                [ ThumbWidget.ToSharedRef() ]
            ]

            // ── Enable checkbox ────────────────────────────────────────────────
            + SHorizontalBox::Slot().MaxWidth(22.f).VAlign(VAlign_Center)
                .Padding(FMargin(4.f, 0.f, 0.f, 0.f))
            [
                SNew(SCheckBox)
                .IsChecked_Lambda([Entry]()
                {
                    return Entry->bEnabled
                        ? ECheckBoxState::Checked
                        : ECheckBoxState::Unchecked;
                })
                .OnCheckStateChanged_Lambda([this, Entry](ECheckBoxState State)
                {
                    Entry->bEnabled = (State == ECheckBoxState::Checked);
                    // Keep the "Selected" tab in sync immediately
                    ApplyFilterAndSort();
                })
            ]

            // ── Asset name ─────────────────────────────────────────────────────
            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                .Padding(FMargin(2.f, 0.f))
            [
                SNew(STextBlock)
                .Text(FText::FromString(Entry->CommonName))
                .ToolTipText(FText::Format(
                    LOCTEXT("EntryTooltip", "Asset: {0}\nPath: {1}"),
                    FText::FromString(Entry->AssetName),
                    FText::FromString(Entry->AssetPath)))
                .TextStyle(FG_STYLE, "SmallText")
                .AutoWrapText(true)
            ]

            // ── Category combo ─────────────────────────────────────────────────
            + SHorizontalBox::Slot().MaxWidth(110.f).VAlign(VAlign_Center)
                .Padding(FMargin(2.f, 0.f))
            [
                SNew(SComboBox<TSharedPtr<FString>>)
                .OptionsSource(&CategoryOptions)
                .OnGenerateWidget(this, &SFoliageGeneratorWidget::MakeCategoryWidget)
                .OnSelectionChanged_Lambda(
                    [Entry](TSharedPtr<FString> Sel, ESelectInfo::Type)
                    {
                        if (!Sel.IsValid()) return;
                        const FString& S = *Sel;
                        if      (S == TEXT("Large Tree"))  Entry->Category = EFoliageCategory::LargeTree;
                        else if (S == TEXT("Medium Tree")) Entry->Category = EFoliageCategory::MediumTree;
                        else if (S == TEXT("Small Tree"))  Entry->Category = EFoliageCategory::SmallTree;
                        else if (S == TEXT("Flower"))      Entry->Category = EFoliageCategory::Flower;
                        else                               Entry->Category = EFoliageCategory::Shrub;
                        // Refresh spacing, scale and patch defaults for the new category.
                        // The spinbox/checkbox Value_Lambdas read from Entry so the UI updates automatically.
                        const FCategoryRules& R = SFoliageGeneratorWidget::GetRules(Entry->Category);
                        Entry->OverrideSpacing  = R.Spacing;
                        Entry->OverrideScaleMin = R.ScaleMin;
                        Entry->OverrideScaleMax = R.ScaleMax;
                        ResetPatchDefaults(Entry.Get());
                    })
                [
                    SNew(STextBlock)
                    .Text(this, &SFoliageGeneratorWidget::GetCategoryText, Entry)
                    .TextStyle(FG_STYLE, "SmallText")
                ]
            ]

            // ── Override spacing ───────────────────────────────────────────────
            + SHorizontalBox::Slot().MaxWidth(72.f).VAlign(VAlign_Center)
                .Padding(FMargin(2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([Entry]() { return Entry->OverrideSpacing; })
                .MinValue(10.f).MaxValue(5000.f).Delta(50.f)
                .ToolTipText(LOCTEXT("OvrSpc",
                    "Grid spacing (cm) — pre-filled from category default.\n"
                    "Edit to override. Min 10 cm."))
                .OnValueChanged_Lambda([Entry](float V) { Entry->OverrideSpacing = V; })
            ]

            // ── Override scale min ─────────────────────────────────────────────
            + SHorizontalBox::Slot().MaxWidth(60.f).VAlign(VAlign_Center)
                .Padding(FMargin(2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([Entry]() { return Entry->OverrideScaleMin; })
                .MinValue(0.f).MaxValue(10.f).Delta(0.05f)
                .ToolTipText(LOCTEXT("OvrScMin","Scale min override. 0 = category default."))
                .OnValueChanged_Lambda([Entry](float V) { Entry->OverrideScaleMin = V; })
            ]

            // ── Override scale max ─────────────────────────────────────────────
            + SHorizontalBox::Slot().MaxWidth(60.f).VAlign(VAlign_Center)
                .Padding(FMargin(2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([Entry]() { return Entry->OverrideScaleMax; })
                .MinValue(0.f).MaxValue(10.f).Delta(0.05f)
                .ToolTipText(LOCTEXT("OvrScMax","Scale max override. 0 = category default."))
                .OnValueChanged_Lambda([Entry](float V) { Entry->OverrideScaleMax = V; })
            ]

            // ── Allowed patch sizes ────────────────────────────────────────────
            // Four compact checkboxes: L / M / S / Sh
            // Controls on which patch-size classes this plant may be placed.
            // Defaults are auto-set from the category; user can override freely.
            + SHorizontalBox::Slot().MaxWidth(120.f).VAlign(VAlign_Center)
                .Padding(FMargin(4.f, 0.f, 2.f, 0.f))
            [
                SNew(SHorizontalBox)
                .ToolTipText(LOCTEXT("PatchCBGroupTip",
                    "Tick which patch sizes this plant may appear on.\n"
                    "L = Large patch (biggest open spaces)\n"
                    "M = Medium patch\n"
                    "S = Small patch\n"
                    "Sh = Tiny / shrub-only patch\n"
                    "Defaults reset when you change the category."))

                // Large patch
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                [
                    SNew(SCheckBox)
                    .IsChecked_Lambda([Entry]()
                    {
                        return Entry->bAllowOnLargePatch
                            ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                    })
                    .OnCheckStateChanged_Lambda([Entry](ECheckBoxState S)
                    {
                        Entry->bAllowOnLargePatch = (S == ECheckBoxState::Checked);
                    })
                    .ToolTipText(LOCTEXT("PatchL","Allow on Large patches"))
                    [ SNew(STextBlock).Text(LOCTEXT("PatchLLabel","L")).TextStyle(FG_STYLE,"SmallText") ]
                ]

                // Medium patch
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                    .Padding(FMargin(2.f, 0.f, 0.f, 0.f))
                [
                    SNew(SCheckBox)
                    .IsChecked_Lambda([Entry]()
                    {
                        return Entry->bAllowOnMediumPatch
                            ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                    })
                    .OnCheckStateChanged_Lambda([Entry](ECheckBoxState S)
                    {
                        Entry->bAllowOnMediumPatch = (S == ECheckBoxState::Checked);
                    })
                    .ToolTipText(LOCTEXT("PatchM","Allow on Medium patches"))
                    [ SNew(STextBlock).Text(LOCTEXT("PatchMLabel","M")).TextStyle(FG_STYLE,"SmallText") ]
                ]

                // Small patch
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                    .Padding(FMargin(2.f, 0.f, 0.f, 0.f))
                [
                    SNew(SCheckBox)
                    .IsChecked_Lambda([Entry]()
                    {
                        return Entry->bAllowOnSmallPatch
                            ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                    })
                    .OnCheckStateChanged_Lambda([Entry](ECheckBoxState S)
                    {
                        Entry->bAllowOnSmallPatch = (S == ECheckBoxState::Checked);
                    })
                    .ToolTipText(LOCTEXT("PatchS","Allow on Small patches"))
                    [ SNew(STextBlock).Text(LOCTEXT("PatchSLabel","S")).TextStyle(FG_STYLE,"SmallText") ]
                ]

                // Shrub-only patch
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                    .Padding(FMargin(2.f, 0.f, 0.f, 0.f))
                [
                    SNew(SCheckBox)
                    .IsChecked_Lambda([Entry]()
                    {
                        return Entry->bAllowOnShrubPatch
                            ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                    })
                    .OnCheckStateChanged_Lambda([Entry](ECheckBoxState S)
                    {
                        Entry->bAllowOnShrubPatch = (S == ECheckBoxState::Checked);
                    })
                    .ToolTipText(LOCTEXT("PatchSh","Allow on tiny / shrub-only patches"))
                    [ SNew(STextBlock).Text(LOCTEXT("PatchShLabel","Sh")).TextStyle(FG_STYLE,"SmallText") ]
                ]
            ]
        ];
}

// ─── Settings section ─────────────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildSettingsSection()
{
    return SNew(SVerticalBox)
        + SVerticalBox::Slot().AutoHeight()
        [
            MakeSectionHeader(LOCTEXT("SettingsHeader", "Settings"))
        ]
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f))
        [
            SNew(SHorizontalBox)

            // Seed
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SeedLabel","Seed")) ]
            + SHorizontalBox::Slot().MaxWidth(80.f).Padding(FMargin(0.f, 0.f, 16.f, 0.f))
            [
                SNew(SSpinBox<int32>)
                .Value(Seed).MinValue(0).MaxValue(99999)
                .OnValueChanged_Lambda([this](int32 V) { Seed = V; })
                .ToolTipText(LOCTEXT("SeedTip","Change to get a different random layout."))
            ]

            // (Building clearance moved to its own row below)

            // Canopy check
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CanopyLabel","Canopy Check")) ]
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 16.f, 0.f))
            [
                SNew(SCheckBox)
                .IsChecked_Lambda([this]()
                {
                    return bCanopyCheck ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                })
                .OnCheckStateChanged_Lambda([this](ECheckBoxState S)
                {
                    bCanopyCheck = (S == ECheckBoxState::Checked);
                })
                .ToolTipText(LOCTEXT("CanopyTip",
                    "Skip points that already have another plant directly overhead."))
            ]

            // Building spear collision
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearLabel","Detect Buildings")) ]
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SCheckBox)
                .IsChecked_Lambda([this]()
                {
                    return bSpearCollision ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                })
                .OnCheckStateChanged_Lambda([this](ECheckBoxState S)
                {
                    bSpearCollision = (S == ECheckBoxState::Checked);
                })
                .ToolTipText(LOCTEXT("SpearTip",
                    "Sweep a vertical capsule (spear) above each candidate point to\n"
                    "detect building walls and ceilings that would intersect the plant.\n"
                    "Disable this if your buildings have no collision at all and you\n"
                    "just want to paint on the selected material surface."))
            ]

            // Use viewport selection
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SelOnlyLabel","Use Selection")) ]
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 16.f, 0.f))
            [
                SNew(SCheckBox)
                .IsChecked_Lambda([this]()
                {
                    return bUseSelection ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                })
                .OnCheckStateChanged_Lambda([this](ECheckBoxState S)
                {
                    bUseSelection = (S == ECheckBoxState::Checked);
                })
                .ToolTipText(LOCTEXT("SelOnlyTip",
                    "When checked, foliage is only placed on the actors you have\n"
                    "selected in the viewport — ignores the material filter.\n"
                    "Use this to test placement on a single patch without generating\n"
                    "across the entire scene."))
            ]

            // Flat-mesh threshold
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("FlatThrLabel","Min Bldg H")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(60.f)
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearFlatThreshold; })
                .MinValue(0.f).MaxValue(500.f).Delta(5.f)
                .OnValueChanged_Lambda([this](float V){ SpearFlatThreshold = V; })
                .ToolTipText(LOCTEXT("FlatThrTip",
                    "Minimum actor Z half-extent (cm) to be treated as a building.\n"
                    "Hit actors shorter than this are considered flat ground meshes\n"
                    "(roads, sidewalks, kerbs) and do NOT block placement.\n"
                    "Raise if low walls are being ignored; lower if flat roofs block."))
            ]

            // Max instances per type
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("MaxInstLabel","Max / Type")) ]
            + SHorizontalBox::Slot().MaxWidth(80.f)
            [
                SNew(SSpinBox<int32>)
                .Value(MaxInstancesPerType)
                .MinValue(10).MaxValue(50000).Delta(100)
                .OnValueChanged_Lambda([this](int32 V) { MaxInstancesPerType = V; })
                .ToolTipText(LOCTEXT("MaxInstTip",
                    "Maximum instances placed per foliage type.\n"
                    "Lower = faster generation. Raise once the layout looks right."))
            ]
        ]

        // ── Per-category building clearance row ─────────────────────────────────
        // Large/Medium → sphere sweep radius (detects lateral walls).
        // Small/Shrub  → upward trace height (detects overhangs only).
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 0.f))
        [
            SNew(SHorizontalBox)

            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 6.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrHdr","Building Clearance (cm):")) ]

            // Large Tree
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrLT","Large")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(ClearanceLargeTree).MinValue(0.f).MaxValue(2000.f).Delta(50.f)
                .OnValueChanged_Lambda([this](float V){ ClearanceLargeTree = V; })
                .ToolTipText(LOCTEXT("ClrLTTip",
                    "Sphere sweep radius for Large Trees (cm).\n"
                    "Rejects placement if any non-target geometry is within this radius.\n"
                    "Catches walls, pillars and columns laterally."))
            ]

            // Medium Tree
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrMT","Medium")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(ClearanceMediumTree).MinValue(0.f).MaxValue(2000.f).Delta(50.f)
                .OnValueChanged_Lambda([this](float V){ ClearanceMediumTree = V; })
                .ToolTipText(LOCTEXT("ClrMTTip","Sphere sweep radius for Medium Trees (cm)."))
            ]

            // Small Tree
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrST","Small")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(ClearanceSmallTree).MinValue(0.f).MaxValue(2000.f).Delta(25.f)
                .OnValueChanged_Lambda([this](float V){ ClearanceSmallTree = V; })
                .ToolTipText(LOCTEXT("ClrSTTip",
                    "Upward trace height for Small Trees (cm).\n"
                    "Rejects placement if non-target geometry is directly overhead."))
            ]

            // Shrub
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrSh","Shrub")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(ClearanceShrub).MinValue(0.f).MaxValue(2000.f).Delta(25.f)
                .OnValueChanged_Lambda([this](float V){ ClearanceShrub = V; })
                .ToolTipText(LOCTEXT("ClrShTip","Spear capsule extra margin for Shrubs (cm)."))
            ]

            // Flower
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("ClrFl","Flower")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f)
            [
                SNew(SSpinBox<float>)
                .Value(ClearanceFlower).MinValue(0.f).MaxValue(500.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ ClearanceFlower = V; })
                .ToolTipText(LOCTEXT("ClrFlTip","Spear capsule extra margin for Flowers (cm)."))
            ]
        ]

        // ── Spear radius row ────────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 0.f))
        [
            SNew(SHorizontalBox)

            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 6.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRadHdr","Spear Radius (cm):")) ]

            // Large
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRL","Large")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearRadiusLarge; })
                .MinValue(0.f).MaxValue(2000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ SpearRadiusLarge = V; })
                .ToolTipText(LOCTEXT("SpearRLTip","Base sphere radius for Large Tree spear (cm). Clearance is added on top."))
            ]

            // Medium
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRM","Med")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearRadiusMedium; })
                .MinValue(0.f).MaxValue(2000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ SpearRadiusMedium = V; })
                .ToolTipText(LOCTEXT("SpearRMTip","Base sphere radius for Medium Tree spear (cm)."))
            ]

            // Small
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRS","Small")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearRadiusSmall; })
                .MinValue(0.f).MaxValue(2000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ SpearRadiusSmall = V; })
                .ToolTipText(LOCTEXT("SpearRSTip","Base sphere radius for Small Tree spear (cm)."))
            ]

            // Shrub
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRSh","Shrub")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearRadiusShrub; })
                .MinValue(0.f).MaxValue(1000.f).Delta(5.f)
                .OnValueChanged_Lambda([this](float V){ SpearRadiusShrub = V; })
                .ToolTipText(LOCTEXT("SpearRShTip","Base sphere radius for Shrub spear (cm)."))
            ]

            // Flower
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("SpearRFl","Flower")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f)
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return SpearRadiusFlower; })
                .MinValue(0.f).MaxValue(500.f).Delta(5.f)
                .OnValueChanged_Lambda([this](float V){ SpearRadiusFlower = V; })
                .ToolTipText(LOCTEXT("SpearRFlTip","Base sphere radius for Flower spear (cm)."))
            ]
        ]

        // ── Canopy Radius row ──────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 0.f))
        [
            SNew(SHorizontalBox)

            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 6.f, 0.f))
            [
                SNew(STextBlock)
                .Text(LOCTEXT("CanopyRadHdr","Canopy Radius (cm):"))
                .ToolTipText(LOCTEXT("CanopyRadHdrTip",
                    "Full canopy spread (trunk + leaves) per tree category.\n"
                    "Sizes the building-detection capsule when 'Detect Buildings' is on.\n"
                    "Clearance is added on top of this value."))
            ]

            // Large
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CanopyRL","Large")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return CanopyRadiusLarge; })
                .MinValue(10.f).MaxValue(5000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ CanopyRadiusLarge = V; })
                .ToolTipText(LOCTEXT("CanopyRLTip","Canopy capsule radius for Large Trees (cm)."))
            ]

            // Medium
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CanopyRM","Med")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f).Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return CanopyRadiusMedium; })
                .MinValue(10.f).MaxValue(5000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ CanopyRadiusMedium = V; })
                .ToolTipText(LOCTEXT("CanopyRMTip","Canopy capsule radius for Medium Trees (cm)."))
            ]

            // Small
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CanopyRS","Small")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(65.f)
            [
                SNew(SSpinBox<float>)
                .Value_Lambda([this](){ return CanopyRadiusSmall; })
                .MinValue(10.f).MaxValue(3000.f).Delta(10.f)
                .OnValueChanged_Lambda([this](float V){ CanopyRadiusSmall = V; })
                .ToolTipText(LOCTEXT("CanopyRSTip","Canopy capsule radius for Small Trees (cm)."))
            ]
        ]

        // ── Patch-size filter row ───────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f))
        [
            SNew(SHorizontalBox)

            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [
                SNew(SCheckBox)
                .IsChecked_Lambda([this]()
                {
                    return bPatchSizeFilter ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
                })
                .OnCheckStateChanged_Lambda([this](ECheckBoxState S)
                {
                    bPatchSizeFilter = (S == ECheckBoxState::Checked);
                })
                .ToolTipText(LOCTEXT("PatchFilterTip",
                    "When enabled, each patch is sized by its longest footprint dimension.\n"
                    "The size class sets the MAXIMUM plant size allowed on that patch:\n"
                    "  Large patch  → Large + Medium + Small + Shrubs + Flowers\n"
                    "  Medium patch → Medium + Small + Shrubs + Flowers\n"
                    "  Small patch  → Small Trees + Shrubs + Flowers\n"
                    "  Shrub patch  → Shrubs + Flowers only\n"
                    "Large lawns get trees AND shrubs; narrow slivers get only shrubs/flowers."))
            ]

            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("PatchFilterLabel","Patch-size filter")) ]

            // Large Tree threshold
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("PLrgLabel","Large ≥")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(PatchThresholdLarge).MinValue(100.f).MaxValue(50000.f).Delta(100.f)
                .OnValueChanged_Lambda([this](float V) { PatchThresholdLarge = V; })
                .ToolTipText(LOCTEXT("PLrgTip","Patches with longest dimension ≥ this (cm) get Large Trees."))
            ]
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CmA"," cm")).TextStyle(FG_STYLE,"SmallText") ]

            // Medium Tree threshold
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("PMedLabel","Med ≥")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(PatchThresholdMedium).MinValue(100.f).MaxValue(50000.f).Delta(100.f)
                .OnValueChanged_Lambda([this](float V) { PatchThresholdMedium = V; })
                .ToolTipText(LOCTEXT("PMedTip","Patches with longest dimension ≥ this (cm) get Medium Trees."))
            ]
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 8.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CmB"," cm")).TextStyle(FG_STYLE,"SmallText") ]

            // Small Tree threshold
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("PSmlLabel","Small ≥")).TextStyle(FG_STYLE,"SmallText") ]
            + SHorizontalBox::Slot().MaxWidth(70.f).Padding(FMargin(0.f, 0.f, 2.f, 0.f))
            [
                SNew(SSpinBox<float>)
                .Value(PatchThresholdSmall).MinValue(50.f).MaxValue(50000.f).Delta(50.f)
                .OnValueChanged_Lambda([this](float V) { PatchThresholdSmall = V; })
                .ToolTipText(LOCTEXT("PSmlTip","Patches with longest dimension ≥ this (cm) get Small Trees. Below this → Shrubs only."))
            ]
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                .Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [ SNew(STextBlock).Text(LOCTEXT("CmC"," cm  (below → Shrubs only)")).TextStyle(FG_STYLE,"SmallText") ]
        ];
}

// ─── Selected tab ────────────────────────────────────────────────────────────
// Shows only the enabled (checked) foliage entries so the user can quickly
// review and tweak spacing / scale / category for the active selection without
// having to scroll through the full "All Plants" list.

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildSelectedTab()
{
    return SNew(SVerticalBox)

        // ── Header ────────────────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight()
        [
            MakeSectionHeader(LOCTEXT("SelTabHeader",
                "Selected Plants  —  only enabled entries shown here"))
        ]

        // ── Quick-actions row ─────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 2.f))
        [
            SNew(SHorizontalBox)

            // Deselect All button (useful to quickly start over)
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 4.f, 0.f))
            [
                SNew(SButton)
                .Text(LOCTEXT("SelDeselectAll", "Deselect All"))
                .ToolTipText(LOCTEXT("SelDeselectAllTip",
                    "Uncheck every plant. Switch to the \"All Plants\" tab to re-select."))
                .OnClicked_Lambda([this]() -> FReply
                {
                    for (auto& E : AllFoliageEntries) E->bEnabled = false;
                    ApplyFilterAndSort();   // rebuilds EnabledEntries → list goes empty
                    if (FoliageListView.IsValid()) FoliageListView->RequestListRefresh();
                    return FReply::Handled();
                })
            ]

            // Live count
            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                .Padding(FMargin(6.f, 0.f))
            [
                SNew(STextBlock)
                .Text_Lambda([this]()
                {
                    return FText::Format(
                        LOCTEXT("SelCount", "{0} plant(s) selected for generation"),
                        FText::AsNumber(EnabledEntries.Num()));
                })
                .TextStyle(FG_STYLE, "SmallText.Subdued")
            ]
        ]

        // ── Settings — mirrored from the All Plants tab ───────────────────────
        // Shown here so the user never has to switch tabs to tweak global params.
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 2.f))
        [
            BuildSettingsSection()
        ]

        // ── Column headers (identical to All Plants tab) ──────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 2.f))
        [
            SNew(SBorder)
            .BorderImage(FG_STYLE.GetBrush("ToolPanel.GroupBorder"))
            .Padding(FMargin(72.f, 2.f, 2.f, 2.f))
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().MaxWidth(22.f)
                [ SNew(STextBlock).Text(FText::GetEmpty()) ]
                + SHorizontalBox::Slot().FillWidth(1.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColName","Plant")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(110.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColCat","Category")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(72.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColSpc","Spacing")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(60.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColScMin","Sc.Min")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(60.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColScMax","Sc.Max")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
                + SHorizontalBox::Slot().MaxWidth(120.f)
                [ SNew(STextBlock).Text(LOCTEXT("SelColPatches","Allowed Patches")).TextStyle(FG_STYLE,"SmallText.Subdued") ]
            ]
        ]

        // ── Scrollable list of enabled entries ────────────────────────────────
        // Reuses GenerateFoliageRow — unchecking a row in this tab removes it
        // from EnabledEntries live (via ApplyFilterAndSort inside the lambda).
        + SVerticalBox::Slot().FillHeight(1.f)
        [
            SNew(SScrollBox)
            + SScrollBox::Slot()
            [
                SAssignNew(SelectedListView, SListView<TSharedPtr<FFoliageEntry>>)
                .ListItemsSource(&EnabledEntries)
                .OnGenerateRow(this, &SFoliageGeneratorWidget::GenerateFoliageRow)
                .SelectionMode(ESelectionMode::None)
                .ScrollbarVisibility(EVisibility::Visible)
            ]
        ]

        // ── Empty-state hint ──────────────────────────────────────────────────
        + SVerticalBox::Slot().AutoHeight().Padding(FMargin(12.f, 8.f))
        [
            SNew(STextBlock)
            .Text(LOCTEXT("SelEmptyHint",
                "No plants selected yet — go to the \"All Plants\" tab and check some entries."))
            .TextStyle(FG_STYLE, "SmallText.Subdued")
            .Visibility_Lambda([this]()
            {
                return EnabledEntries.IsEmpty()
                    ? EVisibility::Visible
                    : EVisibility::Collapsed;
            })
        ];
}

// ─── Button row ───────────────────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildButtonRow()
{
    return SNew(SHorizontalBox)

        + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 8.f, 0.f))
        [
            SNew(SButton)
            .ButtonStyle(FG_STYLE, "PrimaryButton")
            .Text(LOCTEXT("GenerateBtn", "Generate Foliage"))
            .ToolTipText(LOCTEXT("GenerateTip",
                "Scans the level for actors that use the target material,\n"
                "then places all enabled foliage types directly into the\n"
                "Foliage Mode palette via the native IFA C++ API."))
            .OnClicked(this, &SFoliageGeneratorWidget::OnGenerateClicked)
        ]

        + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 8.f, 0.f))
        [
            SNew(SButton)
            .Text(LOCTEXT("ClearBtn", "Clear All Foliage"))
            .ToolTipText(LOCTEXT("ClearTip",
                "Removes ALL foliage instances from the level's InstancedFoliageActor.\n"
                "FoliageType assets are preserved."))
            .OnClicked(this, &SFoliageGeneratorWidget::OnClearClicked)
        ]

        + SHorizontalBox::Slot().AutoWidth()
        [
            SNew(SButton)
            .Text(LOCTEXT("DebugPtsBtn", "Show Placement Points"))
            .ToolTipText(LOCTEXT("DebugPtsTip",
                "Draws debug spheres in the viewport showing where the surface\n"
                "detection finds valid placement positions on the target patch.\n"
                "Green = accepted  |  Red = rejected by boundary check.\n"
                "Spheres persist for 30 seconds then disappear automatically."))
            .OnClicked(this, &SFoliageGeneratorWidget::OnDebugPointsClicked)
        ];
}

// ─── Log section ──────────────────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::BuildLogSection()
{
    return SNew(SVerticalBox)
        + SVerticalBox::Slot().AutoHeight()
        [
            MakeSectionHeader(LOCTEXT("LogHeader","Log"))
        ]
        + SVerticalBox::Slot().MaxHeight(180.f)
        [
            SNew(SBorder)
            .BorderImage(FG_STYLE.GetBrush("ToolPanel.DarkGroupBorder"))
            .Padding(4.f)
            [
                SNew(SScrollBox)
                + SScrollBox::Slot()
                [
                    SAssignNew(LogText, SMultiLineEditableText)
                    .IsReadOnly(true)
                    .AutoWrapText(true)
                    .Text(LOCTEXT("LogInit","(log will appear here after Generate)"))
                ]
            ]
        ];
}

// ─── Category combo helpers ───────────────────────────────────────────────────

TSharedRef<SWidget> SFoliageGeneratorWidget::MakeCategoryWidget(TSharedPtr<FString> Item)
{
    return SNew(STextBlock)
        .Text(FText::FromString(*Item))
        .TextStyle(FG_STYLE, "SmallText");
}

FText SFoliageGeneratorWidget::GetCategoryText(TSharedPtr<FFoliageEntry> Entry) const
{
    if (!Entry.IsValid()) return FText::GetEmpty();
    switch (Entry->Category)
    {
        case EFoliageCategory::LargeTree:  return LOCTEXT("CatLT","Large Tree");
        case EFoliageCategory::MediumTree: return LOCTEXT("CatMT","Medium Tree");
        case EFoliageCategory::SmallTree:  return LOCTEXT("CatST","Small Tree");
        case EFoliageCategory::Shrub:      return LOCTEXT("CatSh","Shrub");
        case EFoliageCategory::Flower:     return LOCTEXT("CatFl","Flower");
        default:                           return LOCTEXT("CatMT2","Medium Tree");
    }
}

// ─── RefreshFoliageList ───────────────────────────────────────────────────────

void SFoliageGeneratorWidget::RefreshFoliageList()
{
    AllFoliageEntries.Empty();

    IAssetRegistry& AR =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

    if (AR.IsLoadingAssets())
        AR.SearchAllAssets(/*bSynchronousSearch=*/true);

    FARFilter Filter;
    Filter.bRecursiveClasses = true;
    Filter.ClassPaths.Add(
        FTopLevelAssetPath(TEXT("/Script/Foliage"), TEXT("FoliageType_InstancedStaticMesh")));

    TArray<FAssetData> Assets;
    AR.GetAssets(Filter, Assets);

    // Default order: alphabetical by asset name
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.AssetName.Compare(B.AssetName) < 0;
    });

    for (const FAssetData& AD : Assets)
    {
        TSharedPtr<FFoliageEntry> Entry = MakeShareable(new FFoliageEntry());
        Entry->AssetPath   = AD.GetObjectPathString();
        Entry->AssetName   = AD.AssetName.ToString();
        Entry->CommonName  = ExtractCommonName(Entry->AssetName);
        Entry->AssetData   = AD;
        Entry->bEnabled    = true;

        Entry->Category = AutoCategorize(Entry->AssetName);
        {
            const FCategoryRules& R = GetRules(Entry->Category);
            Entry->OverrideSpacing  = R.Spacing;
            Entry->OverrideScaleMin = R.ScaleMin;
            Entry->OverrideScaleMax = R.ScaleMax;
        }
        ResetPatchDefaults(Entry.Get());

        AllFoliageEntries.Add(Entry);
    }

    ApplyFilterAndSort();
}

// ─── ApplyFilterAndSort ───────────────────────────────────────────────────────

void SFoliageGeneratorWidget::ApplyFilterAndSort()
{
    // Rebuild the list-view source from the master array
    FoliageEntries.Empty();
    for (const TSharedPtr<FFoliageEntry>& E : AllFoliageEntries)
    {
        // Name filter — case-insensitive substring on CommonName or full AssetName
        if (!PlantNameFilter.IsEmpty())
        {
            const bool bMatchCommon = E->CommonName.Contains(PlantNameFilter, ESearchCase::IgnoreCase);
            const bool bMatchFull   = E->AssetName.Contains(PlantNameFilter,  ESearchCase::IgnoreCase);
            if (!bMatchCommon && !bMatchFull) continue;
        }
        FoliageEntries.Add(E);
    }

    // Sort
    if (bSortByCategory && bSortByName)
    {
        FoliageEntries.Sort([](const TSharedPtr<FFoliageEntry>& A, const TSharedPtr<FFoliageEntry>& B)
        {
            if (A->Category != B->Category)
                return static_cast<int32>(A->Category) < static_cast<int32>(B->Category);
            return A->CommonName < B->CommonName;
        });
    }
    else if (bSortByCategory)
    {
        FoliageEntries.Sort([](const TSharedPtr<FFoliageEntry>& A, const TSharedPtr<FFoliageEntry>& B)
        {
            return static_cast<int32>(A->Category) < static_cast<int32>(B->Category);
        });
    }
    else if (bSortByName)
    {
        FoliageEntries.Sort([](const TSharedPtr<FFoliageEntry>& A, const TSharedPtr<FFoliageEntry>& B)
        {
            return A->CommonName < B->CommonName;
        });
    }

    if (FoliageListView.IsValid())
        FoliageListView->RequestListRefresh();

    // Rebuild the "Selected" tab source — only entries that are enabled
    EnabledEntries.Empty();
    for (const TSharedPtr<FFoliageEntry>& E : AllFoliageEntries)
    {
        if (E->bEnabled)
            EnabledEntries.Add(E);
    }

    if (SelectedListView.IsValid())
        SelectedListView->RequestListRefresh();
}

// ─── Actions ─────────────────────────────────────────────────────────────────

FReply SFoliageGeneratorWidget::OnRefreshClicked()
{
    RefreshFoliageList();
    AppendLog(FString::Printf(TEXT("List refreshed — %d FoliageType asset(s) found."),
                              FoliageEntries.Num()));
    return FReply::Handled();
}

FReply SFoliageGeneratorWidget::OnGenerateClicked()
{
    ClearLog();
    RunGenerate();
    return FReply::Handled();
}

FReply SFoliageGeneratorWidget::OnClearClicked()
{
    RunClear();
    return FReply::Handled();
}

// ─── OnDebugPointsClicked ────────────────────────────────────────────────────
// Draws debug spheres at every surface candidate that the placement algorithm
// would find on the target patch.
//  Green  = point accepted by surface detection + boundary containment check
//  Red    = point failed the boundary containment check (outside mesh)
// Spheres persist for 30 s then disappear automatically.

FReply SFoliageGeneratorWidget::OnDebugPointsClicked()
{
    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!World) return FReply::Handled();

    // Debug Points ALWAYS works on the viewport selection only.
    // Scanning the whole scene at 50 cm resolution is prohibitively expensive
    // on large levels — this tool is designed as a spot-check on one patch.
    TArray<AStaticMeshActor*> TargetActors;
    {
        USelection* Sel = GEditor->GetSelectedActors();
        for (int32 i = 0; i < Sel->Num(); ++i)
            if (AStaticMeshActor* A = Cast<AStaticMeshActor>(Sel->GetSelectedObject(i)))
                TargetActors.Add(A);
    }
    if (TargetActors.IsEmpty())
    {
        AppendLog(TEXT("Debug Points: select at least one surface actor in the viewport first."));
        return FReply::Handled();
    }

    // Hard point cap — prevents accidental freeze on large selections
    constexpr int32 MaxDebugPoints = 2000;
    constexpr float DebugStep      = 50.f;   // 50 cm grid — readable but not excessive

    int32 nGreen = 0, nRed = 0, nTotal = 0;
    FCollisionQueryParams QP(NAME_None, true);

    // Walk per-actor bounds (same as RunGenerate) so two patches 2 km apart
    // don't generate a 2 km × 2 km grid of trace points.
    TSet<TPair<int32,int32>> VisitedKeys;
    for (AStaticMeshActor* TA : TargetActors)
    {
        if (nTotal >= MaxDebugPoints) break;
        FSlateApplication::Get().PumpMessages();

        FVector O, E;
        TA->GetActorBounds(false, O, E);
        const float TraceTop = (float)O.Z + (float)E.Z + 500.f;
        const float TraceBot = (float)O.Z - (float)E.Z - 100.f;

        for (float GX = (float)(O.X - E.X) + DebugStep * 0.5f;
             GX <= (float)(O.X + E.X) && nTotal < MaxDebugPoints;
             GX += DebugStep)
        {
            for (float GY = (float)(O.Y - E.Y) + DebugStep * 0.5f;
                 GY <= (float)(O.Y + E.Y) && nTotal < MaxDebugPoints;
                 GY += DebugStep)
            {
                // Deduplicate across overlapping actor AABBs
                const int32 KX = FMath::RoundToInt(GX / DebugStep);
                const int32 KY = FMath::RoundToInt(GY / DebugStep);
                if (VisitedKeys.Contains({KX, KY})) continue;
                VisitedKeys.Add({KX, KY});

                // Surface detection — trace first, AABB fallback
                FHitResult Hit;
                bool bFound = false;
                FVector PassStart(GX, GY, TraceTop);
                const FVector PassEnd(GX, GY, TraceBot);
                for (int32 P = 0; P < 8 && !bFound; ++P)
                {
                    if (!World->LineTraceSingleByChannel(Hit, PassStart, PassEnd, ECC_Visibility, QP))
                        break;
                    AStaticMeshActor* HA = Cast<AStaticMeshActor>(Hit.GetActor());
                    if (HA && TargetActors.Contains(HA)) bFound = true;
                    else PassStart = Hit.Location - FVector(0,0,1);
                }
                if (!bFound)
                {
                    Hit.Location = FVector(GX, GY, O.Z + E.Z);
                    bFound = true;
                }

                // Boundary containment — OccupiedCells-style: check each actor's
                // local component bounds (same logic as RunGenerate boundary gate)
                bool bInside = false;
                for (AStaticMeshActor* CheckTA : TargetActors)
                {
                    UStaticMeshComponent* SMC = CheckTA->GetStaticMeshComponent();
                    if (!SMC) continue;
                    const FVector LP = SMC->GetComponentTransform().InverseTransformPosition(Hit.Location);
                    const FBox    LB = SMC->CalcLocalBounds().GetBox();
                    if (LP.X >= LB.Min.X - 1.f && LP.X <= LB.Max.X + 1.f &&
                        LP.Y >= LB.Min.Y - 1.f && LP.Y <= LB.Max.Y + 1.f)
                    { bInside = true; break; }
                }

                DrawDebugSphere(World, Hit.Location + FVector(0,0,5),
                                8.f, 6, bInside ? FColor::Green : FColor::Red,
                                /*bPersist=*/false, /*LifeTime=*/30.f);
                bInside ? ++nGreen : ++nRed;
                ++nTotal;
            }
        }
    }

    const bool bCapped = nTotal >= MaxDebugPoints;
    AppendLog(FString::Printf(
        TEXT("Debug Points: %d green | %d red%s — visible for 30 s"),
        nGreen, nRed,
        bCapped ? TEXT("  [cap reached — select fewer actors for full coverage]") : TEXT("")));

    if (GEditor) GEditor->RedrawAllViewports(true);
    return FReply::Handled();
}

// ─── RAII Collision Guard ────────────────────────────────────────────────────
// Guarantees collision state is restored even if RunGenerate exits early via
// return, user cancel, or exception. The destructor runs unconditionally.

struct FScopedCollisionModifier
{
    struct FSavedState
    {
        UStaticMeshComponent*   SMC;
        ECollisionEnabled::Type OrigEnabled;
        FName                   OrigProfile;
    };
    TArray<FSavedState> Modifications;

    void Apply(UStaticMeshComponent* InSMC)
    {
        if (!InSMC) return;
        FSavedState& S = Modifications.AddDefaulted_GetRef();
        S.SMC         = InSMC;
        S.OrigEnabled = InSMC->GetCollisionEnabled();
        S.OrigProfile = InSMC->GetCollisionProfileName();
        InSMC->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
        InSMC->SetCollisionResponseToAllChannels(ECollisionResponse::ECR_Block);
        InSMC->SetCollisionObjectType(ECollisionChannel::ECC_WorldStatic);
    }

    ~FScopedCollisionModifier()
    {
        for (const FSavedState& S : Modifications)
        {
            if (IsValid(S.SMC))
            {
                S.SMC->SetCollisionEnabled(S.OrigEnabled);
                S.SMC->SetCollisionProfileName(S.OrigProfile);
            }
        }
    }

    // Non-copyable
    FScopedCollisionModifier() = default;
    FScopedCollisionModifier(const FScopedCollisionModifier&) = delete;
    FScopedCollisionModifier& operator=(const FScopedCollisionModifier&) = delete;
};

// ─── CPU Triangle Raycast ────────────────────────────────────────────────────
// Fires a downward ray against the raw render-mesh triangles using
// Möller–Trumbore intersection.  Accurate on sloped / uneven surfaces even
// when the StaticMesh has "No Collision" set at the asset level.
// Returns true if any triangle was hit; OutLocation and OutNormal are in world
// space.  Falls through to false for meshes with no accessible render data or
// for extreme poly counts (> 200 k tris) where the AABB fallback is faster.

static bool RaycastMeshCPU(
    UStaticMeshComponent* SMC,
    float WorldX, float WorldY,
    float RayTop,
    FVector& OutLocation, FVector& OutNormal)
{
    if (!SMC) return false;
    UStaticMesh* Mesh = SMC->GetStaticMesh();
    if (!Mesh) return false;
    FStaticMeshRenderData* RD = Mesh->GetRenderData();
    if (!RD || RD->LODResources.Num() == 0) return false;

    const FStaticMeshLODResources& LOD  = RD->LODResources[0];
    const FPositionVertexBuffer&   PVB  = LOD.VertexBuffers.PositionVertexBuffer;

    TArray<uint32> Indices;
    LOD.IndexBuffer.GetCopy(Indices);
    const int32 NumTris = Indices.Num() / 3;
    if (NumTris == 0 || NumTris > 200000) return false;   // sanity / perf guard

    const FTransform& CompT = SMC->GetComponentTransform();

    // Ray in world space — straight down from RayTop
    const FVector RayOriginW(WorldX, WorldY, RayTop);
    const FVector RayDirW   (0.f, 0.f, -1.f);

    // Transform ray into component local space (Möller–Trumbore works in local)
    const FVector RayOriginL = CompT.InverseTransformPosition(RayOriginW);
    FVector       RayDirL    = CompT.InverseTransformVector(RayDirW);
    const float   DirLen     = RayDirL.Size();
    if (DirLen < KINDA_SMALL_NUMBER) return false;
    RayDirL /= DirLen;   // normalise (non-uniform scale can stretch direction)

    float   BestT       = FLT_MAX;
    FVector BestNormalL = FVector::UpVector;
    bool    bHit        = false;

    for (int32 Ti = 0; Ti < NumTris; ++Ti)
    {
        const FVector V0(PVB.VertexPosition(Indices[Ti * 3 + 0]));
        const FVector V1(PVB.VertexPosition(Indices[Ti * 3 + 1]));
        const FVector V2(PVB.VertexPosition(Indices[Ti * 3 + 2]));

        const FVector E1 = V1 - V0;
        const FVector E2 = V2 - V0;
        const FVector H  = FVector::CrossProduct(RayDirL, E2);
        const float   A  = FVector::DotProduct(E1, H);
        if (FMath::Abs(A) < 1e-6f) continue;           // parallel

        const float   F  = 1.f / A;
        const FVector S  = RayOriginL - V0;
        const float   U  = F * FVector::DotProduct(S, H);
        if (U < 0.f || U > 1.f) continue;

        const FVector Q  = FVector::CrossProduct(S, E1);
        const float   V  = F * FVector::DotProduct(RayDirL, Q);
        if (V < 0.f || U + V > 1.f) continue;

        const float T = F * FVector::DotProduct(E2, Q);
        if (T > 0.f && T < BestT)
        {
            BestT       = T;
            BestNormalL = FVector::CrossProduct(E1, E2).GetSafeNormal();
            bHit        = true;
        }
    }

    if (!bHit) return false;

    const FVector LocalHit = RayOriginL + RayDirL * BestT;
    OutLocation = CompT.TransformPosition(LocalHit);
    OutNormal   = CompT.TransformVectorNoScale(BestNormalL).GetSafeNormal();
    if (OutNormal.Z < 0.f) OutNormal = -OutNormal;   // always face upward
    return true;
}

// ─── RunGenerate ─────────────────────────────────────────────────────────────

void SFoliageGeneratorWidget::RunGenerate()
{
    // 0. Validation
    if (MaterialPath.IsEmpty())
    {
        AppendLog(TEXT("ERROR: No material selected. Drag a material into the picker above."));
        return;
    }

    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!World)
    {
        AppendLog(TEXT("ERROR: No editor world found. Is a level open?"));
        return;
    }

    // 1. Load target material
    UMaterialInterface* TargetMat = Cast<UMaterialInterface>(
        StaticLoadObject(UMaterialInterface::StaticClass(), nullptr, *MaterialPath));

    if (!TargetMat)
    {
        AppendLog(FString::Printf(TEXT("ERROR: Cannot load material '%s'."), *MaterialPath));
        return;
    }
    AppendLog(FString::Printf(TEXT("Material: %s"), *TargetMat->GetName()));

    // 2. Collect target actors — either the viewport selection OR all actors
    //    that use the target material, depending on bUseSelection.
    TArray<AStaticMeshActor*> TargetActors;

    if (bUseSelection)
    {
        // Use only the actors the user has selected in the viewport.
        // Useful for testing placement on a single patch without scanning the scene.
        TArray<AActor*> SelActors;
        GEditor->GetSelectedActors()->GetSelectedObjects<AActor>(SelActors);
        for (AActor* A : SelActors)
        {
            AStaticMeshActor* SMA = Cast<AStaticMeshActor>(A);
            if (IsValid(SMA)) TargetActors.Add(SMA);
        }
        AppendLog(FString::Printf(TEXT("Using viewport selection: %d actor(s)."), TargetActors.Num()));
    }
    else
    {
        for (TActorIterator<AStaticMeshActor> It(World); It; ++It)
        {
            AStaticMeshActor* Actor = *It;
            if (!IsValid(Actor)) continue;

            UStaticMeshComponent* SMC = Actor->GetStaticMeshComponent();
            if (!SMC || !SMC->GetStaticMesh()) continue;

            for (int32 Slot = 0; Slot < SMC->GetNumMaterials(); ++Slot)
            {
                UMaterialInterface* SlotMat = SMC->GetMaterial(Slot);
                if (!SlotMat) continue;

                // Strict match: same object pointer OR same asset path.
                if (SlotMat == TargetMat || SlotMat->GetPathName() == MaterialPath)
                {
                    TargetActors.Add(Actor);
                    break;
                }
            }
        }
    }

    if (TargetActors.IsEmpty())
    {
        AppendLog(bUseSelection
            ? TEXT("WARNING: Nothing selected in the viewport. Select at least one actor.")
            : TEXT("WARNING: No actors found using this material. Check the path."));
        return;
    }
    AppendLog(FString::Printf(TEXT("Found %d surface actor(s)."), TargetActors.Num()));

    // RAII guard — destructor restores collision unconditionally even on
    // early return, user cancel, or exception.
    FScopedCollisionModifier CollisionGuard;
    {
        // Enable collision on target surface actors
        for (AStaticMeshActor* A : TargetActors)
        {
            UStaticMeshComponent* SMC = A->GetStaticMeshComponent();
            CollisionGuard.Apply(SMC);
        }

        // Enable collision on building-like obstacle actors
        const float MinHalfHeight = 25.f;
        for (TActorIterator<AStaticMeshActor> It(World); It; ++It)
        {
            AStaticMeshActor* A = *It;
            if (!IsValid(A) || TargetActors.Contains(A)) continue;
            FVector Orig, Ext;
            A->GetActorBounds(false, Orig, Ext);
            if (Ext.Z < MinHalfHeight) continue;
            UStaticMeshComponent* SMC = A->GetStaticMeshComponent();
            CollisionGuard.Apply(SMC);
        }
        AppendLog(FString::Printf(
            TEXT("Collision enabled on %d actor(s) (%d surface + obstacles) for traces."),
            CollisionGuard.Modifications.Num(), TargetActors.Num()));
    }

    // 3. Collect enabled entries from the FULL list (not the filtered view)
    TArray<TSharedPtr<FFoliageEntry>> Enabled;
    for (auto& E : AllFoliageEntries) if (E->bEnabled) Enabled.Add(E);

    if (Enabled.IsEmpty())
    {
        AppendLog(TEXT("WARNING: No foliage types enabled. Tick at least one checkbox."));
        return;
    }

    // Sort by ecological hierarchy: large trees first, flowers last.
    // This ensures each tier claims its territory before the next tier fills
    // the gaps.  Within the same category, larger spacing wins (denser species
    // placed before compact ones of the same tier).
    Enabled.Sort([](const TSharedPtr<FFoliageEntry>& A, const TSharedPtr<FFoliageEntry>& B)
    {
        const int32 CatA = static_cast<int32>(A->Category);
        const int32 CatB = static_cast<int32>(B->Category);
        if (CatA != CatB) return CatA < CatB;  // LargeTree(0) before Flower(4)
        return FMath::Max(A->OverrideSpacing, 10.f) > FMath::Max(B->OverrideSpacing, 10.f);
    });

    // 4. Get or create IFA
    AInstancedFoliageActor* IFA =
        AInstancedFoliageActor::GetInstancedFoliageActorForCurrentLevel(World, true);
    if (!IFA)
    {
        AppendLog(TEXT("ERROR: Could not get or create InstancedFoliageActor."));
        return;
    }
    AppendLog(TEXT("InstancedFoliageActor ready."));

    // 5a. Build occupancy grid → erode → flood-fill → dilate → classify.
    //
    //  WHY this approach:
    //    The target surface is one continuous connected mesh (corridors link all
    //    courtyards). Any connectivity-based grouping collapses everything into
    //    one group. Instead we:
    //      1. Rasterise the surface at CellSize resolution (downward traces).
    //      2. ERODE by 1 cell — removes narrow corridors (< 2×CellSize wide).
    //         Each courtyard keeps its interior cells; thin links disappear.
    //      3. FLOOD-FILL the eroded grid → each isolated open space = one
    //         component. Classify by sqrt(cellCount × CellSize²).
    //      4. DILATE labels back onto the full (un-eroded) cells so placement
    //         points on edge-cells inherit the nearest courtyard component.
    //      5. Per-placement O(1) lookup via grid coordinates — no extra traces.

    FBox CombinedBounds(ForceInit);
    TSet<AActor*> TargetActorSet;
    for (AStaticMeshActor* A : TargetActors)
    {
        FVector Orig, Ext;
        A->GetActorBounds(false, Orig, Ext);
        CombinedBounds += FBox(Orig - Ext, Orig + Ext);
        TargetActorSet.Add(A);
    }
    // ── Patch category ────────────────────────────────────────────────────────
    // For explicit viewport selection the whole selection is one patch sized
    // by the combined-bounds longest dimension.  For material-scan mode each
    // actor is classified independently from its own bounds.
    EFoliageCategory SelectionPatchCat = EFoliageCategory::Shrub;
    if (bUseSelection)
    {
        const float LongestDim = FMath::Max(CombinedBounds.GetSize().X,
                                            CombinedBounds.GetSize().Y);
        if      (LongestDim >= PatchThresholdLarge)  SelectionPatchCat = EFoliageCategory::LargeTree;
        else if (LongestDim >= PatchThresholdMedium) SelectionPatchCat = EFoliageCategory::MediumTree;
        else if (LongestDim >= PatchThresholdSmall)  SelectionPatchCat = EFoliageCategory::SmallTree;
        AppendLog(FString::Printf(
            TEXT("Selection patch class: %s  (longest dim %.0f cm)"),
            SelectionPatchCat == EFoliageCategory::LargeTree  ? TEXT("Large Tree")  :
            SelectionPatchCat == EFoliageCategory::MediumTree ? TEXT("Medium Tree") :
            SelectionPatchCat == EFoliageCategory::SmallTree  ? TEXT("Small Tree")  :
                                                                TEXT("Shrub/Flower"),
            LongestDim));
    }

    // Returns the patch category for a target actor (O(1), no grid needed).
    auto GetActorPatchCat = [&](AStaticMeshActor* Actor) -> EFoliageCategory
    {
        if (bUseSelection) return SelectionPatchCat;
        FVector Orig, Ext;
        Actor->GetActorBounds(false, Orig, Ext);
        const float Longest = FMath::Max(Ext.X * 2.f, Ext.Y * 2.f);
        if (Longest >= PatchThresholdLarge)  return EFoliageCategory::LargeTree;
        if (Longest >= PatchThresholdMedium) return EFoliageCategory::MediumTree;
        if (Longest >= PatchThresholdSmall)  return EFoliageCategory::SmallTree;
        return EFoliageCategory::Shrub;
    };

    // 5b. Place each foliage type over the unified grid
    int32 TotalPlaced    = 0;
    bool  bUserCancelled = false;
    const double StartTime = FPlatformTime::Seconds();

    // One progress frame per foliage type
    FScopedSlowTask Progress(
        static_cast<float>(Enabled.Num()),
        LOCTEXT("Generating", "Generating foliage..."));
    Progress.MakeDialog(/*bShowCancelButton=*/true);

    FRandomStream Rng(Seed);

    // ─── Cross-foliage spatial hash ───────────────────────────────────────────
    //
    // Two-radius model for hierarchical under-canopy planting:
    //
    //   HalfSpacing  — full exclusion radius used between plants of the SAME
    //                  or LARGER category (enforces design spacing).
    //   StemRadius   — tight trunk clearance used when a SMALLER plant (higher
    //                  category index) checks against a LARGER already-placed
    //                  plant.  This lets shrubs/flowers grow under tree canopies
    //                  while still keeping clear of the trunk.
    //
    // Rule: when placing category C near an existing point of category E,
    //   C > E  (smaller plant under larger) → minDist = thisStemR + P.StemRadius
    //   C ≤ E  (same tier or placing large near small) → minDist = thisHalfSp + P.HalfSpacing
    //
    // StemRadius values mirror the SpearRadius settings (plant body half-width).

    struct FPlacedPoint
    {
        FVector2D        Pos;
        float            HalfSpacing;
        float            StemRadius;
        EFoliageCategory Category;
    };
    TMap<TPair<int32,int32>, TArray<FPlacedPoint>> SpatialHash;

    float MaxSpacingAllTypes = 10.f;
    for (const TSharedPtr<FFoliageEntry>& E : Enabled)
        MaxSpacingAllTypes = FMath::Max(MaxSpacingAllTypes, FMath::Max(E->OverrideSpacing, 10.f));
    const float BucketSize = MaxSpacingAllTypes;

    auto HashKey = [&](float X, float Y) -> TPair<int32,int32>
    {
        return { FMath::FloorToInt(X / BucketSize), FMath::FloorToInt(Y / BucketSize) };
    };

    // Returns the trunk/stem radius for a category (reuses the SpearRadius UI values).
    auto StemRadiusFor = [&](EFoliageCategory Cat) -> float
    {
        switch (Cat)
        {
            case EFoliageCategory::LargeTree:  return SpearRadiusLarge;
            case EFoliageCategory::MediumTree: return SpearRadiusMedium;
            case EFoliageCategory::SmallTree:  return SpearRadiusSmall;
            case EFoliageCategory::Shrub:      return SpearRadiusShrub;
            default:                           return SpearRadiusFlower;
        }
    };

    auto IsTooCloseToAny = [&](float X, float Y,
                                float ThisHalfSp, float ThisStemR,
                                EFoliageCategory ThisCat) -> bool
    {
        const int32 BX = FMath::FloorToInt(X / BucketSize);
        const int32 BY = FMath::FloorToInt(Y / BucketSize);
        for (int32 DY = -1; DY <= 1; ++DY)
        for (int32 DX = -1; DX <= 1; ++DX)
        {
            const TPair<int32,int32> Key{ BX + DX, BY + DY };
            if (const TArray<FPlacedPoint>* Bucket = SpatialHash.Find(Key))
            {
                for (const FPlacedPoint& P : *Bucket)
                {
                    // Smaller plant near larger → stem clearance only (under-canopy ok)
                    // Same or larger plant near existing → full design spacing
                    const bool bSmallerNearLarger =
                        static_cast<int32>(ThisCat) > static_cast<int32>(P.Category);
                    const float MinDist = bSmallerNearLarger
                        ? (ThisStemR + P.StemRadius)
                        : (ThisHalfSp + P.HalfSpacing);

                    if (FVector2D::DistSquared(FVector2D(X, Y), P.Pos) < MinDist * MinDist)
                        return true;
                }
            }
        }
        return false;
    };

    auto RegisterPlacedPoint = [&](float X, float Y,
                                   float HalfSp, float StemR,
                                   EFoliageCategory Cat)
    {
        SpatialHash.FindOrAdd(HashKey(X, Y)).Add({ FVector2D(X, Y), HalfSp, StemR, Cat });
    };
    // ─────────────────────────────────────────────────────────────────────────

    for (const TSharedPtr<FFoliageEntry>& Entry : Enabled)
    {
        if (bUserCancelled) break;

        Progress.EnterProgressFrame(1.f,
            FText::Format(LOCTEXT("GenType", "Placing {0}..."),
                FText::FromString(Entry->CommonName)));

        if (Progress.ShouldCancel()) { bUserCancelled = true; break; }

        // Load foliage type asset
        UFoliageType* FT = Cast<UFoliageType>(
            StaticLoadObject(UFoliageType::StaticClass(), nullptr, *Entry->AssetPath));
        if (!FT)
        {
            AppendLog(FString::Printf(TEXT("  SKIP: Cannot load %s"), *Entry->AssetPath));
            continue;
        }

        const float Spacing  = FMath::Max(Entry->OverrideSpacing,  10.f);
        const float ScaleMin = FMath::Max(Entry->OverrideScaleMin, 0.1f);
        const float ScaleMax = FMath::Max(Entry->OverrideScaleMax, ScaleMin);

        // Register in Foliage Mode palette
        FFoliageInfo* FoliageInfo = nullptr;
        IFA->AddFoliageType(FT, &FoliageInfo);
        if (!FoliageInfo)
        {
            AppendLog(FString::Printf(TEXT("  SKIP: AddFoliageType returned null for %s"),
                                      *Entry->AssetName));
            continue;
        }

        TArray<FFoliageInstance> Instances;
        bool  bCapReached = false;
        int32 DbgCandidates=0, DbgPatchReject=0, DbgSpearReject=0, DbgCanopyReject=0, DbgHashReject=0;

        // ── Triangle-based placement (mirrors UE's built-in Fill tool) ────────
        //
        // For each target actor we read LOD0 triangles directly from render
        // data — this works on meshes with "No Collision" because it bypasses
        // the physics system entirely.  Random points are generated inside each
        // upward-facing triangle using barycentric coordinates, giving spatially
        // uniform coverage that respects the exact mesh outline (no AABB leakage
        // onto adjacent surfaces).
        //
        // Instance count per triangle ∝ area / Spacing² so density is uniform
        // regardless of triangle tessellation.
        const float Spacing2 = Spacing * Spacing;

        for (AStaticMeshActor* TA : TargetActors)
        {
            if (bCapReached || bUserCancelled) break;

            // ── Per-actor patch-size gate ──────────────────────────────────────
            if (bPatchSizeFilter)
            {
                const EFoliageCategory ActorCat = GetActorPatchCat(TA);
                bool bAllowed = false;
                switch (ActorCat)
                {
                    case EFoliageCategory::LargeTree:  bAllowed = Entry->bAllowOnLargePatch;  break;
                    case EFoliageCategory::MediumTree: bAllowed = Entry->bAllowOnMediumPatch; break;
                    case EFoliageCategory::SmallTree:  bAllowed = Entry->bAllowOnSmallPatch;  break;
                    default:                           bAllowed = Entry->bAllowOnShrubPatch;  break;
                }
                if (!bAllowed) { ++DbgPatchReject; continue; }
            }

            UStaticMeshComponent* SMC = TA->GetStaticMeshComponent();
            if (!SMC) continue;
            UStaticMesh* SM = SMC->GetStaticMesh();
            if (!SM || !SM->HasValidRenderData()) continue;

            FStaticMeshLODResources& LOD = SM->GetRenderData()->LODResources[0];
            FPositionVertexBuffer&   PVB = LOD.VertexBuffers.PositionVertexBuffer;
            const uint32             NV  = PVB.GetNumVertices();
            if (NV == 0) continue;

            TArray<uint32> Indices;
            LOD.IndexBuffer.GetCopy(Indices);

            const FTransform CompXform = SMC->GetComponentTransform();

            for (int32 SecIdx = 0; SecIdx < LOD.Sections.Num(); ++SecIdx)
            {
                if (bCapReached || bUserCancelled) break;

                const FStaticMeshSection& Sec = LOD.Sections[SecIdx];

                // In material-scan mode only process sections that use TargetMat,
                // so we don't place foliage on e.g. the wood planks of a multi-
                // material mesh that also happens to have a grass slot.
                if (!bUseSelection)
                {
                    UMaterialInterface* SecMat = SMC->GetMaterial(Sec.MaterialIndex);
                    if (!SecMat ||
                        (SecMat != TargetMat && SecMat->GetPathName() != MaterialPath))
                        continue;
                }

                const uint32 FirstIdx  = Sec.FirstIndex;
                const uint32 TriCount  = Sec.NumTriangles;

                for (uint32 TriIdx = 0; TriIdx < TriCount; ++TriIdx)
                {
                    if (bCapReached || bUserCancelled) break;
                    if (TriIdx % 500 == 0)
                    {
                        FSlateApplication::Get().PumpMessages();
                        if (Progress.ShouldCancel()) { bUserCancelled = true; break; }
                    }

                    const uint32 I0 = Indices[FirstIdx + TriIdx * 3 + 0];
                    const uint32 I1 = Indices[FirstIdx + TriIdx * 3 + 1];
                    const uint32 I2 = Indices[FirstIdx + TriIdx * 3 + 2];
                    if (I0 >= NV || I1 >= NV || I2 >= NV) continue;

                    // World-space vertices
                    const FVector V0 = CompXform.TransformPosition(FVector(PVB.VertexPosition(I0)));
                    const FVector V1 = CompXform.TransformPosition(FVector(PVB.VertexPosition(I1)));
                    const FVector V2 = CompXform.TransformPosition(FVector(PVB.VertexPosition(I2)));

                    const FVector Edge1 = V1 - V0;
                    const FVector Edge2 = V2 - V0;
                    const FVector CrossP = Edge1 ^ Edge2;  // magnitude = 2 × area

                    // Ensure normal points upward; skip wall/downward triangles
                    FVector TriNormal = CrossP.GetSafeNormal();
                    if (TriNormal.Z < 0.f) TriNormal = -TriNormal;
                    if (TriNormal.Z < 0.17f) continue;  // > ~80° from vertical

                    const float Area = CrossP.Size() * 0.5f;
                    if (Area < 1.f) continue;  // degenerate triangle

                    // Expected instances for this triangle (area-proportional density)
                    const float ExpF  = Area / Spacing2;
                    int32       Count = FMath::FloorToInt(ExpF);
                    if (Rng.FRandRange(0.f, 1.f) < FMath::Frac(ExpF)) ++Count;
                    if (Count <= 0) continue;

                    for (int32 k = 0; k < Count; ++k)
                    {
                        if (bCapReached || bUserCancelled) break;
                        if (Instances.Num() >= MaxInstancesPerType)
                        { bCapReached = true; break; }

                        ++DbgCandidates;

                        // Uniform random point inside triangle (parallelogram-fold method)
                        float u = Rng.FRandRange(0.f, 1.f);
                        float v = Rng.FRandRange(0.f, 1.f);
                        if (u + v > 1.f) { u = 1.f - u; v = 1.f - v; }
                        const FVector Pos = V0 + u * Edge1 + v * Edge2;

                        // ── Building detection ─────────────────────────────────
                        // Trees: full-canopy capsule overlap (covers trunk + leaves).
                        // Shrubs/Flowers: narrow stem sphere sweep (original logic).
                        // DbgCapsuleCenter/HalfH/R are set for trees and read below
                        // to draw a short-lived debug capsule on accepted placements.
                        FVector DbgCapsuleCenter = FVector::ZeroVector;
                        float   DbgCapsuleHalfH  = 0.f;
                        float   DbgCapsuleR      = 0.f;
                        bool    bDbgDrawCapsule  = false;

                        if (bSpearCollision)
                        {
                            const FCategoryRules& R = GetRules(Entry->Category);
                            const bool bIsTree =
                                Entry->Category == EFoliageCategory::LargeTree  ||
                                Entry->Category == EFoliageCategory::MediumTree ||
                                Entry->Category == EFoliageCategory::SmallTree;

                            FCollisionQueryParams SpearQP(NAME_None, false);
                            for (AActor* Ignored : TargetActorSet) SpearQP.AddIgnoredActor(Ignored);
                            SpearQP.AddIgnoredActor(IFA);
                            for (const FScopedCollisionModifier::FSavedState& SC : CollisionGuard.Modifications)
                                if (SC.SMC) SpearQP.AddIgnoredActor(SC.SMC->GetOwner());

                            if (bIsTree)
                            {
                                // Resolve per-category canopy radius + clearance
                                float BaseCanopyR     = CanopyRadiusSmall;
                                float ActiveClearance = ClearanceSmallTree;
                                switch (Entry->Category)
                                {
                                    case EFoliageCategory::LargeTree:
                                        BaseCanopyR = CanopyRadiusLarge; ActiveClearance = ClearanceLargeTree; break;
                                    case EFoliageCategory::MediumTree:
                                        BaseCanopyR = CanopyRadiusMedium; ActiveClearance = ClearanceMediumTree; break;
                                    default: break;
                                }
                                const float CanopyR      = BaseCanopyR + ActiveClearance;
                                // CapsuleHalfH: half the cylindrical segment of the capsule.
                                // Center is at SpearHalfHeight above ground.
                                // The capsule top sphere reaches SpearHalfHeight + CanopyR,
                                // so the half-height of the cylinder = SpearHalfHeight - CanopyR
                                // (clamped to ≥ 1 so UE never gets a degenerate shape).
                                const float CapsuleHalfH = FMath::Max(1.f, R.SpearHalfHeight - CanopyR);
                                const FVector CapsuleCenter = Pos + FVector(0.f, 0.f, R.SpearHalfHeight);

                                TArray<FOverlapResult> Overlaps;
                                bool bBlocked = false;
                                if (World->OverlapMultiByObjectType(
                                        Overlaps, CapsuleCenter, FQuat::Identity,
                                        FCollisionObjectQueryParams(ECollisionChannel::ECC_WorldStatic),
                                        FCollisionShape::MakeCapsule(CanopyR, CapsuleHalfH), SpearQP))
                                {
                                    for (const FOverlapResult& O : Overlaps)
                                    {
                                        if (!IsValid(O.GetActor())) continue;
                                        FVector HO, HExt;
                                        O.GetActor()->GetActorBounds(false, HO, HExt);
                                        if (HExt.Z >= SpearFlatThreshold) { bBlocked = true; break; }
                                    }
                                }
                                if (bBlocked) { ++DbgSpearReject; continue; }

                                // Stash capsule geometry for debug draw on acceptance
                                DbgCapsuleCenter = CapsuleCenter;
                                DbgCapsuleHalfH  = CapsuleHalfH;
                                DbgCapsuleR      = CanopyR;
                                bDbgDrawCapsule  = true;
                            }
                            else
                            {
                                // Shrubs / Flowers — narrow stem sphere sweep
                                float ActiveClearance = ClearanceShrub;
                                float BaseSpearRadius = SpearRadiusShrub;
                                if (Entry->Category == EFoliageCategory::Flower)
                                {
                                    ActiveClearance = ClearanceFlower;
                                    BaseSpearRadius = SpearRadiusFlower;
                                }
                                const float SpearRadius   = BaseSpearRadius + ActiveClearance;
                                const float GroundSkip    = FMath::Clamp(R.SpearHalfHeight * 0.1f, 5.f, 100.f);
                                const FVector SpearBottom = Pos + FVector(0.f, 0.f, GroundSkip);
                                const FVector SpearTop    = Pos + FVector(0.f, 0.f, R.SpearHalfHeight * 2.f);

                                FHitResult SpearHit;
                                if (World->SweepSingleByObjectType(
                                        SpearHit, SpearBottom, SpearTop, FQuat::Identity,
                                        FCollisionObjectQueryParams(ECollisionChannel::ECC_WorldStatic),
                                        FCollisionShape::MakeSphere(SpearRadius), SpearQP))
                                {
                                    bool bIsBuilding = true;
                                    if (IsValid(SpearHit.GetActor()))
                                    {
                                        FVector HO, HExt;
                                        SpearHit.GetActor()->GetActorBounds(false, HO, HExt);
                                        if (HExt.Z < SpearFlatThreshold) bIsBuilding = false;
                                    }
                                    if (bIsBuilding) { ++DbgSpearReject; continue; }
                                }
                            }
                        }

                        // ── Canopy check ───────────────────────────────────────
                        // Shrubs and flowers are understory plants — they grow
                        // under tree canopies by design, so skip this check for
                        // those categories.  Only trees need clear sky overhead.
                        const bool bIsUnderstory =
                            Entry->Category == EFoliageCategory::Shrub ||
                            Entry->Category == EFoliageCategory::Flower;
                        if (bCanopyCheck && !bIsUnderstory)
                        {
                            FCollisionQueryParams CanopyQP(NAME_None, false);
                            CanopyQP.AddIgnoredActor(IFA);
                            for (const FScopedCollisionModifier::FSavedState& SC : CollisionGuard.Modifications)
                                if (SC.SMC) CanopyQP.AddIgnoredActor(SC.SMC->GetOwner());

                            FHitResult CanopyHit;
                            if (World->LineTraceSingleByChannel(
                                    CanopyHit,
                                    Pos + FVector(0.f, 0.f, 10.f),
                                    Pos + FVector(0.f, 0.f, Spacing * 2.f),
                                    ECC_WorldStatic, CanopyQP))
                            { ++DbgCanopyReject; continue; }
                        }

                        // ── Cross-foliage spacing ──────────────────────────────
                        // Smaller plants (shrubs, flowers) use stem clearance
                        // against already-placed larger plants, allowing them to
                        // grow under canopies.  Same-tier plants use full spacing.
                        const float HalfSp   = Spacing * 0.5f;
                        const float StemR    = StemRadiusFor(Entry->Category);
                        if (IsTooCloseToAny(Pos.X, Pos.Y, HalfSp, StemR, Entry->Category))
                        { ++DbgHashReject; continue; }

                        // ── Build instance ─────────────────────────────────────
                        FFoliageInstance Inst;
                        Inst.Location = Pos;

                        const float Yaw = Rng.FRandRange(0.f, 360.f);
                        if (GetRules(Entry->Category).bAlignToNormal)
                        {
                            // Tilt instance to follow the surface slope
                            const FQuat   AlignQ   = FQuat::FindBetweenVectors(FVector::UpVector, TriNormal);
                            const FRotator AlignRot = AlignQ.Rotator();
                            Inst.Rotation = FRotator(AlignRot.Pitch, Yaw, AlignRot.Roll);
                        }
                        else
                        {
                            Inst.Rotation = FRotator(0.f, Yaw, 0.f);
                        }

                        const float Scale = Rng.FRandRange(ScaleMin, ScaleMax);
                        Inst.DrawScale3D  = FVector3f(Scale, Scale, Scale);

                        RegisterPlacedPoint(Pos.X, Pos.Y, HalfSp, StemR, Entry->Category);
                        Instances.Add(MoveTemp(Inst));

                        // Draw the building-detection capsule for a few seconds
                        // so the user can see the volume that was checked.
                        if (bDbgDrawCapsule)
                        {
                            DrawDebugCapsule(
                                World,
                                DbgCapsuleCenter,
                                DbgCapsuleHalfH,
                                DbgCapsuleR,
                                FQuat::Identity,
                                FColor::Cyan,
                                /*bPersistentLines=*/false,
                                /*LifeTime=*/3.f);
                        }
                    }
                }
            }
        }

        if (Instances.IsEmpty())
        {
            AppendLog(FString::Printf(
                TEXT("  %s: 0 placements (spacing %.0f cm) [sampled=%d patch=%d spear=%d canopy=%d hash=%d]"),
                *Entry->AssetName, Spacing,
                DbgCandidates, DbgPatchReject,
                DbgSpearReject, DbgCanopyReject, DbgHashReject));
            continue;
        }

        // AddInstances — UE5.7 pointer-array signature
        TArray<const FFoliageInstance*> Ptrs;
        Ptrs.Reserve(Instances.Num());
        for (const FFoliageInstance& I : Instances) Ptrs.Add(&I);
        FoliageInfo->AddInstances(FT, Ptrs);

        AppendLog(FString::Printf(
            TEXT("  ✓ %-40s  %5d instances  [%s]  spacing %.0f cm"),
            *Entry->AssetName, Instances.Num(),
            *GetCategoryText(Entry).ToString(), Spacing));

        TotalPlaced += Instances.Num();
    }

    if (bUserCancelled)
    {
        AppendLog(TEXT("⚠  Generation cancelled by user."));
    }

    IFA->PostEditChange();
    IFA->MarkPackageDirty();

    // Redraw all viewports immediately — foliage becomes visible without
    // the user needing to switch modes or click away.
    if (GEditor)
    {
        GEditor->RedrawAllViewports(/*bInvalidateHitProxies=*/true);
    }

    const double Elapsed = FPlatformTime::Seconds() - StartTime;
    AppendLog(FString::Printf(
        TEXT("\n━━━ DONE ━━━  %d instances placed in %.1f s"), TotalPlaced, Elapsed));
    AppendLog(TEXT("Viewport refreshed — foliage is now visible in the scene."));
}

// ─── RunClear ────────────────────────────────────────────────────────────────

void SFoliageGeneratorWidget::RunClear()
{
    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!World) { AppendLog(TEXT("ERROR: No editor world.")); return; }

    AInstancedFoliageActor* IFA =
        AInstancedFoliageActor::GetInstancedFoliageActorForCurrentLevel(World, false);
    if (!IFA) { AppendLog(TEXT("No InstancedFoliageActor in level — nothing to clear.")); return; }

    TArray<UHierarchicalInstancedStaticMeshComponent*> HISCs;
    IFA->GetComponents<UHierarchicalInstancedStaticMeshComponent>(HISCs);

    int32 Removed = 0;
    for (UHierarchicalInstancedStaticMeshComponent* HISC : HISCs)
    {
        if (!IsValid(HISC)) continue;
        Removed += HISC->GetInstanceCount();
        HISC->ClearInstances();
    }

    IFA->PostEditChange();
    IFA->MarkPackageDirty();

    if (GEditor)
    {
        GEditor->RedrawAllViewports(/*bInvalidateHitProxies=*/true);
    }

    AppendLog(FString::Printf(TEXT("Cleared %d foliage instances."), Removed));
}

// ─── Logging ─────────────────────────────────────────────────────────────────

void SFoliageGeneratorWidget::AppendLog(const FString& Line)
{
    if (!LogBuffer.IsEmpty()) LogBuffer += TEXT("\n");
    LogBuffer += Line;
    if (LogText.IsValid()) LogText->SetText(FText::FromString(LogBuffer));
    UE_LOG(LogTemp, Log, TEXT("[FoliageGen] %s"), *Line);
}

void SFoliageGeneratorWidget::ClearLog()
{
    LogBuffer.Empty();
    if (LogText.IsValid()) LogText->SetText(FText::GetEmpty());
}

#undef LOCTEXT_NAMESPACE
