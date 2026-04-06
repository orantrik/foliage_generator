// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.

#include "FoliageGeneratorModule.h"
#include "SFoliageGeneratorWidget.h"

#include "LevelEditor.h"
#include "ToolMenus.h"
#include "Framework/Docking/TabManager.h"
#include "Widgets/Docking/SDockTab.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Styling/SlateStyleRegistry.h"
#include "Styling/AppStyle.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"

#define LOCTEXT_NAMESPACE "FoliageGeneratorModule"

static const FName FoliageGeneratorTabId("FoliageGeneratorTab");
static const FName FoliageGeneratorStyleSetName("FoliageGeneratorStyle");

// ─── Commands ────────────────────────────────────────────────────────────────

FFoliageGeneratorCommands::FFoliageGeneratorCommands()
    : TCommands<FFoliageGeneratorCommands>(
          TEXT("FoliageGenerator"),
          LOCTEXT("FoliageGeneratorCommands", "Foliage Generator"),
          NAME_None,
          FAppStyle::GetAppStyleSetName())
{
}

void FFoliageGeneratorCommands::RegisterCommands()
{
    UI_COMMAND(OpenFoliageGenerator,
               "Foliage Generator",
               "Opens the procedural Foliage Generator panel",
               EUserInterfaceActionType::Button,
               FInputChord());
}

// ─── Module ───────────────────────────────────────────────────────────────────

void FFoliageGeneratorModule::StartupModule()
{
    // Minimal style set — no custom icons (avoids missing Icon128.png warning)
    StyleSet = MakeShareable(new FSlateStyleSet(FoliageGeneratorStyleSetName));
    FSlateStyleRegistry::RegisterSlateStyle(*StyleSet);

    // Register commands
    FFoliageGeneratorCommands::Register();

    CommandList = MakeShareable(new FUICommandList);
    CommandList->MapAction(
        FFoliageGeneratorCommands::Get().OpenFoliageGenerator,
        FExecuteAction::CreateRaw(this, &FFoliageGeneratorModule::OpenFoliageGeneratorTab),
        FCanExecuteAction());

    // Register the tab spawner
    FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
        FoliageGeneratorTabId,
        FOnSpawnTab::CreateRaw(this, &FFoliageGeneratorModule::SpawnFoliageGeneratorTab))
        .SetDisplayName(LOCTEXT("FoliageGeneratorTabTitle", "Foliage Generator"))
        .SetTooltipText(LOCTEXT("FoliageGeneratorTabTooltip",
                                "Procedurally place foliage on material-tagged surfaces"))
        .SetGroup(WorkspaceMenu::GetMenuStructure().GetLevelEditorCategory())
        .SetIcon(FSlateIcon(FAppStyle::GetAppStyleSetName(), "LevelEditor.Tabs.Foliage"));

    // Hook into Level Editor toolbar
    RegisterMenuExtensions();
}

void FFoliageGeneratorModule::ShutdownModule()
{
    UnregisterMenuExtensions();

    if (FSlateStyleRegistry::FindSlateStyle(FoliageGeneratorStyleSetName))
    {
        FSlateStyleRegistry::UnRegisterSlateStyle(*StyleSet);
    }

    FFoliageGeneratorCommands::Unregister();

    FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(FoliageGeneratorTabId);
}

void FFoliageGeneratorModule::RegisterMenuExtensions()
{
    UToolMenus::RegisterStartupCallback(
        FSimpleMulticastDelegate::FDelegate::CreateLambda([this]()
        {
            FToolMenuOwnerScoped OwnerScoped(this);

            // Try UE5.4+ toolbar name first, fall back to earlier name
            UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu(
                "LevelEditor.LevelEditorToolBar.AssetsToolBar");

            if (!ToolbarMenu)
            {
                ToolbarMenu = UToolMenus::Get()->ExtendMenu(
                    "LevelEditor.LevelEditorToolBar.PlayToolBar");
            }
            if (!ToolbarMenu)
            {
                ToolbarMenu = UToolMenus::Get()->ExtendMenu(
                    "LevelEditor.LevelEditorToolBar");
            }

            if (ToolbarMenu)
            {
                FToolMenuSection& Section =
                    ToolbarMenu->FindOrAddSection("FoliageGeneratorSection");
                Section.AddMenuEntryWithCommandList(
                    FFoliageGeneratorCommands::Get().OpenFoliageGenerator,
                    CommandList);
            }
        }));
}

void FFoliageGeneratorModule::UnregisterMenuExtensions()
{
    UToolMenus::UnRegisterStartupCallback(this);
    UToolMenus::UnregisterOwner(this);
}

void FFoliageGeneratorModule::OpenFoliageGeneratorTab()
{
    FGlobalTabmanager::Get()->TryInvokeTab(FoliageGeneratorTabId);
}

TSharedRef<SDockTab> FFoliageGeneratorModule::SpawnFoliageGeneratorTab(
    const FSpawnTabArgs& Args)
{
    return SNew(SDockTab)
        .TabRole(ETabRole::NomadTab)
        .Label(LOCTEXT("FoliageGeneratorTabLabel", "Foliage Generator"))
        [
            SNew(SFoliageGeneratorWidget)
        ];
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FFoliageGeneratorModule, FoliageGenerator)
