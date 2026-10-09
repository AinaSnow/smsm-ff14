using System.Numerics;
using Smsm.StagehandBridge.Core;
using Stagehand.Definitions;
using Stagehand.Definitions.Objects;

namespace Smsm.StagehandBridge;

public static class StageRecipe
{
    public static StageDefinition Create(Vector3 position, LightPreset preset)
    {
        var definition = new StageDefinition { Info = new StageInfo { Name = "SMSM M2 owned native light", VersionString = "0.1.0" } };
        definition.Objects["point"] = new LightDefinition { Shape = LightShape.Point, Position = position, IsDisabled = preset == LightPreset.Off,
            Color = preset == LightPreset.Off ? Vector3.Zero : preset == LightPreset.Warm ? new(1, .35f, .1f) : new(.1f, .35f, 1),
            Intensity = 8, Range = 10, EnableDynamicShadows = false, EnableCharacterShadows = false,
            EnableObjectShadows = false, EnableSpecularHighlights = true };
        return definition;
    }
}
