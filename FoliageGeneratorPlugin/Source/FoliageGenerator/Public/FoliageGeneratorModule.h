// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Framework/Commands/Commands.h"
#include "Framework/Commands/UICommandInfo.h"
#include "Styling/SlateStyle.h"

// ─── Commands ────────────────────────────────────────────────────────────────

class FFoliageGeneratorCommands : public TCommands<FFoliageGeneratorCommands>
{
public:
    FFoliageGeneratorCommands();

    virtual void RegisterCommands() override;

    TSharedPtr<FUICommandInfo> OpenFoliageGenerator;
};

// ─── Module ───────────────────────────────────────────────────────────────────

class FFoliageGeneratorModule : public IModuleInterface
{
public:
    /** IModuleInterface */
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    void RegisterMenuExtensions();
    void UnregisterMenuExtensions();

    void OpenFoliageGeneratorTab();
    TSharedRef<SDockTab> SpawnFoliageGeneratorTab(const FSpawnTabArgs& Args);

    TSharedPtr<FSlateStyleSet>    StyleSet;
    TSharedPtr<FUICommandList>    CommandList;
};
