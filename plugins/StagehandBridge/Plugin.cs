using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Serialization;
using Dalamud.Configuration;
using Dalamud.Game.Command;
using Dalamud.Plugin;
using Dalamud.Plugin.Services;
using Smsm.StagehandBridge.Core;
using Stagehand.Api;
using Stagehand.Definitions;
using Stagehand.Definitions.Objects;

namespace Smsm.StagehandBridge;

[Serializable]
public sealed class Configuration : IPluginConfiguration
{
    public int Version { get; set; } = 1;
    public List<string> OwnedStages { get; set; } = [];
}

public sealed class Plugin : IDalamudPlugin
{
    private readonly IDalamudPluginInterface pi;
    private readonly IFramework framework;
    private readonly ICommandManager commands;
    private readonly IClientState client;
    private readonly IObjectTable objects;
    private readonly ICondition conditions;
    private readonly IPluginLog log;
    private readonly IStagehandApiConsumer api;
    private readonly Session session;
    private readonly StageClient stage;
    private readonly string directory;
    private long nextTick;
    private bool disposed;
    private string lastStatus = "";
    public Plugin(IDalamudPluginInterface pi, IFramework framework, ICommandManager commands, IClientState client,
        IObjectTable objects, ICondition conditions, IPluginLog log)
    {
        this.pi = pi; this.framework = framework; this.commands = commands; this.client = client;
        this.objects = objects; this.conditions = conditions; this.log = log;
        directory = pi.GetPluginConfigDirectory(); Directory.CreateDirectory(directory);
        var staleCommand = Path.Combine(directory, "command.txt");
        if (File.Exists(staleCommand)) File.Delete(staleCommand); // Never replay an old RUN after reload/crash.
        var config = pi.GetPluginConfig() as Configuration ?? new();
        config.OwnedStages ??= [];
        api = StagehandApi.CreateIpcClient(pi); stage = new(api);
        var game = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule!.FileName)!;
        session = new(stage, new CaptureClient(game), new Journal(pi, config, directory));
        session.Recover(config.OwnedStages.ToArray());
        commands.AddHandler("/smsm-light", new CommandInfo(OnCommand) { HelpMessage = "run: OFF/WARM/COOL samples; lifecycle: warm lamp for up to 60s, no capture; stop: cleanup; status: report. No light on load." });
        framework.Update += Update;
        api.LocationChanged += OnLocation;
        client.TerritoryChanged += OnTerritory;
        client.Logout += OnLogout;
        WriteStatus();
    }
    private static long Now => Environment.TickCount64;
    private EnvironmentState Current()
    {
        var player = objects.LocalPlayer;
        var ready = client.IsLoggedIn && player is not null && !client.IsGPosing &&
            !conditions[Dalamud.Game.ClientState.Conditions.ConditionFlag.BetweenAreas] &&
            !conditions[Dalamud.Game.ClientState.Conditions.ConditionFlag.BetweenAreas51];
        if (!ready || !stage.Available) return new(false, default, default);
        var location = api.GetLocation();
        return new(true, player!.Position, new(location.WorldId, location.TerritoryId, location.WardId, location.DivisionId, location.HouseId, location.RoomId));
    }
    private void OnCommand(string command, string args) => framework.RunOnFrameworkThread(() => Execute(args));
    private void Execute(string args)
    {
        try
        {
            switch (args.Trim().ToLowerInvariant())
            {
                case "run": session.Start(Now, Current()); break;
                case "lifecycle": session.Start(Now, Current(), lifecycleOnly: true); break;
                case "stop": session.Stop("manual stop"); break;
                case "": case "status": log.Information("SMSM light: {Status}; captures={Captures}", session.Status, session.CompletedCaptures); break;
                default: throw new ArgumentException("Use /smsm-light run, lifecycle, stop or status");
            }
        }
        catch (Exception e) { log.Warning(e, "SMSM light command rejected"); }
        WriteStatus();
    }
    private void Update(IFramework _)
    {
        if (disposed || Now < nextTick) return; nextTick = Now + 100;
        try
        {
            var command = Path.Combine(directory, "command.txt");
            if (File.Exists(command)) { var value = File.ReadAllText(command).Trim(); File.Delete(command); Execute(value); }
            session.Tick(Now, session.Running ? Current() : default);
        }
        catch (Exception e) { session.Stop("framework error"); log.Warning(e, "SMSM light stopped"); }
        WriteStatus();
    }
    private void OnLocation(StageLocation _) => framework.RunOnFrameworkThread(() => session.Stop("Stagehand location changed"));
    private void OnTerritory(uint _) => framework.RunOnFrameworkThread(() => session.Stop("territory changed"));
    private void OnLogout(int type, int code) => framework.RunOnFrameworkThread(() => session.Stop("logout"));
    private void WriteStatus()
    {
        var path = Path.Combine(directory, "status.json"); var temp = path + ".tmp";
        var text = JsonSerializer.Serialize(new { processId = Environment.ProcessId, running = session.Running, status = session.Status, completedCaptures = session.CompletedCaptures, ownedStage = session.OwnedStage, pluginDisabled = disposed, apiRevision = stage.Revision });
        if (text == lastStatus) return;
        File.WriteAllText(temp, text);
        File.Move(temp, path, true);
        lastStatus = text;
    }
    public void Dispose()
    {
        disposed = true;
        framework.Update -= Update; api.LocationChanged -= OnLocation;
        client.TerritoryChanged -= OnTerritory; client.Logout -= OnLogout;
        commands.RemoveHandler("/smsm-light"); session.Stop("plugin disabled");
        WriteStatus(); api.Dispose();
    }
    private sealed class StageClient(IStagehandApiConsumer api) : IStageClient
    {
        public string Revision { get; private set; } = "unverified";
        public bool Available { get { try { var v = api.GetPluginApiRevision(); Revision = v.ToString(); return v.Major == 1 && v.Minor >= 2; } catch { Revision = "unavailable"; return false; } } }
        public bool Apply(string id, Vector3 position, LightPreset preset)
        {
            var definition = StageRecipe.Create(position, preset);
            if (!api.TryCreateOrUpdateTemporaryStage(definition.ToDefinitionString(), id, "SMSM M2 finite test")) return false;
            var visible = api.TrySetTemporaryStageVisible(id, preset != LightPreset.Off);
            return preset == LightPreset.Off || visible; // Already hidden is a valid OFF result.
        }
        public bool Remove(string id) { if (!Available) return false; api.TryDestroyTemporaryStage(id); return true; }
    }
    private sealed class Journal(IDalamudPluginInterface pi, Configuration config, string directory) : ISessionJournal
    {
        private readonly JsonSerializerOptions options = new() { IncludeFields = true, Converters = { new JsonStringEnumConverter() } };
        public void Own(string id) { config.OwnedStages.Add(id); pi.SavePluginConfig(config); }
        public void Released(string id) { config.OwnedStages.Remove(id); pi.SavePluginConfig(config); }
        public void Event(string kind, object value)
        {
            var path = Path.Combine(directory, "events.jsonl");
            File.AppendAllText(path, JsonSerializer.Serialize(new { utc = DateTimeOffset.UtcNow, kind, value }, options) + "\n");
        }
    }
}
