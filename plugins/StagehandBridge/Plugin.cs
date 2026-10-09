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
    private readonly object lifecycleGate = new();
    private readonly StatusPublisher statusPublisher;
    private readonly string[] recoveryIds;
    private bool recovered;
    private bool commandRegistered, locationSubscribed, territorySubscribed, logoutSubscribed, updateSubscribed;
    private bool statusWarning;
    private long nextTick;
    private bool disposed;
    public Plugin(IDalamudPluginInterface pi, IFramework framework, ICommandManager commands, IClientState client,
        IObjectTable objects, ICondition conditions, IPluginLog log)
    {
        this.pi = pi; this.framework = framework; this.commands = commands; this.client = client;
        this.objects = objects; this.conditions = conditions; this.log = log;
        // Failed pre-0.2.1 constructors may still have callbacks in this game
        // process. Isolate control files so those instances cannot consume work.
        directory = Path.Combine(pi.GetPluginConfigDirectory(), "control-v2"); Directory.CreateDirectory(directory);
        statusPublisher = new(directory);
        var staleCommand = Path.Combine(directory, "command.txt");
        if (File.Exists(staleCommand)) File.Delete(staleCommand); // Never replay an old RUN after reload/crash.
        var config = pi.GetPluginConfig() as Configuration ?? new();
        config.OwnedStages ??= [];
        api = StagehandApi.CreateIpcClient(pi); stage = new(api);
        var game = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule!.FileName)!;
        session = new(stage, new CaptureClient(game), new Journal(pi, config, directory));
        recoveryIds = config.OwnedStages.ToArray();
        lock (lifecycleGate)
        {
            try
            {
                WriteStatus(); // Publish before any callback can enter this instance.
                commands.AddHandler("/smsm-light", new CommandInfo(OnCommand) { HelpMessage = "run: three samples; probe: OFF/WARM/COOL/OFF material inputs; lifecycle: warm lamp for up to 60s, no capture; stop: cleanup; status: report. No light on load." });
                commandRegistered = true;
                api.LocationChanged += OnLocation; locationSubscribed = true;
                client.TerritoryChanged += OnTerritory; territorySubscribed = true;
                client.Logout += OnLogout; logoutSubscribed = true;
                framework.Update += Update; updateSubscribed = true; // Register last.
            }
            catch
            {
                disposed = true;
                try { Unsubscribe(); } finally { api.Dispose(); }
                throw;
            }
        }
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
        lock (lifecycleGate)
        {
        if (disposed) return;
        RecoverOnFramework();
        try
        {
            switch (args.Trim().ToLowerInvariant())
            {
                case "run": session.Start(Now, Current()); break;
                case "probe": session.Start(Now, Current(), materialProbe: true); break;
                case "lifecycle": session.Start(Now, Current(), lifecycleOnly: true); break;
                case "stop": session.Stop("manual stop"); break;
                case "": case "status": log.Information("SMSM light: {Status}; captures={Captures}", session.Status, session.CompletedCaptures); break;
                default: throw new ArgumentException("Use /smsm-light run, probe, lifecycle, stop or status");
            }
        }
        catch (Exception e) { log.Warning(e, "SMSM light command rejected"); }
        WriteStatus();
        }
    }
    private void Update(IFramework _)
    {
        lock (lifecycleGate)
        {
        if (disposed || Now < nextTick) return; nextTick = Now + 100;
        try
        {
            RecoverOnFramework();
            var command = Path.Combine(directory, "command.txt");
            if (File.Exists(command)) { var value = File.ReadAllText(command).Trim(); File.Delete(command); Execute(value); }
            session.Tick(Now, session.Running ? Current() : default);
        }
        catch (Exception e) { session.Stop("framework error"); log.Warning(e, "SMSM light stopped"); }
        WriteStatus();
        }
    }
    private void RecoverOnFramework()
    {
        if (recovered) return;
        session.Recover(recoveryIds); recovered = true;
    }
    private void StopFromEvent(string reason) => framework.RunOnFrameworkThread(() =>
    {
        lock (lifecycleGate) { if (!disposed) { session.Stop(reason); WriteStatus(); } }
    });
    private void OnLocation(StageLocation _) => StopFromEvent("Stagehand location changed");
    private void OnTerritory(uint _) => StopFromEvent("territory changed");
    private void OnLogout(int type, int code) => StopFromEvent("logout");
    private void WriteStatus()
    {
        var text = JsonSerializer.Serialize(new { bridgeVersion = "0.2.1.0", controlProtocol = 2, processId = Environment.ProcessId, running = session.Running, status = session.Status, completedCaptures = session.CompletedCaptures, ownedStage = session.OwnedStage, pluginDisabled = disposed, apiRevision = stage.Revision });
        if (!statusPublisher.TryPublish(text))
        {
            if (!statusWarning) log.Warning("SMSM status file temporarily unavailable; publication will retry");
            statusWarning = true;
        }
        else statusWarning = false;
    }
    private void Unsubscribe()
    {
        if (updateSubscribed) { framework.Update -= Update; updateSubscribed = false; }
        if (locationSubscribed) { api.LocationChanged -= OnLocation; locationSubscribed = false; }
        if (territorySubscribed) { client.TerritoryChanged -= OnTerritory; territorySubscribed = false; }
        if (logoutSubscribed) { client.Logout -= OnLogout; logoutSubscribed = false; }
        if (commandRegistered) { commands.RemoveHandler("/smsm-light"); commandRegistered = false; }
    }
    public void Dispose()
    {
        lock (lifecycleGate)
        {
            if (disposed) return;
            disposed = true;
            try { Unsubscribe(); session.Stop("plugin disabled"); WriteStatus(); }
            finally { api.Dispose(); }
        }
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
