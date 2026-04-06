// Copyright 2025 Foliage Generator Plugin. All Rights Reserved.

using UnrealBuildTool;

public class FoliageGenerator : ModuleRules
{
    public FoliageGenerator(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "Foliage",          // AInstancedFoliageActor, UFoliageType, FFoliageInfo
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "Slate",
            "SlateCore",
            "UnrealEd",                 // GEditor, FEditorDelegates
            "LevelEditor",              // FLevelEditorModule, toolbar extension
            "ToolMenus",                // UToolMenus for menu/toolbar registration
            "AssetRegistry",            // IAssetRegistry, FAssetData
            "FoliageEdit",              // Editor-side foliage APIs (IFA AddFoliageType)
            "InputCore",                // FKey, EKeys
            "WorkspaceMenuStructure",   // GetMenuStructure()
        });
    }
}
