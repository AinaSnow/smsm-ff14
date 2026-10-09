using System.Numerics;

namespace Smsm.StagehandBridge.Core;

public enum LightPreset { Off, Warm, Cool }
public readonly record struct Place(uint World, ushort Territory, int Ward, int Division, int House, int Room);
public readonly record struct EnvironmentState(bool Ready, Vector3 Player, Place Place);
public readonly record struct PollResult(bool Done, string? Directory = null);
public interface IStageClient
{
    bool Available { get; }
    bool Apply(string id, Vector3 position, LightPreset preset);
    // True means deleted or already absent; never deletes another caller's ID.
    bool Remove(string id);
}
public interface ICaptureClient
{
    void Prepare();
    PollResult PollPrepare();
    void Begin();
    PollResult Poll();
    void Cancel();
}
public interface ISessionJournal
{
    void Own(string id);
    void Released(string id);
    void Event(string kind, object value);
}

/// <summary>A finite manual-start session. All methods run on the framework thread.</summary>
public sealed class Session(IStageClient stage, ICaptureClient capture, ISessionJournal journal)
{
    private enum Phase { Idle, Prepare, Settle, Capture, Lifecycle }
    private Phase phase;
    private int index;
    private long deadline, readyAt;
    private Place place;
    private Vector3 player, position;
    private string? owned;
    private bool lifecycleOnly;
    private readonly List<string> cleanupPending = [];
    private static readonly LightPreset[] Sequence = [LightPreset.Off, LightPreset.Warm, LightPreset.Cool];
    public bool Running => phase != Phase.Idle;
    public string Status { get; private set; } = "Idle; no light created";
    public string? OwnedStage => owned;
    public int CompletedCaptures { get; private set; }

    public void Recover(IEnumerable<string> ids)
    {
        foreach (var id in ids)
            if (id.StartsWith("smsm.m2.", StringComparison.Ordinal) && !cleanupPending.Contains(id)) cleanupPending.Add(id);
        RetryCleanup();
    }

    public void Start(long now, EnvironmentState environment, bool lifecycleOnly = false)
    {
        if (Running) throw new InvalidOperationException("A finite session is already running");
        RetryCleanup();
        if (cleanupPending.Count != 0) throw new InvalidOperationException("Previous owned Stage cleanup is pending");
        if (!environment.Ready || !stage.Available) throw new InvalidOperationException("Ordinary gameplay and compatible Stagehand are required");
        this.lifecycleOnly = lifecycleOnly;
        place = environment.Place; player = environment.Player;
        position = player + new Vector3(2, 1.5f, 1.5f);
        if (!Finite(position)) throw new InvalidOperationException("Invalid player position");
        owned = "smsm.m2." + Guid.NewGuid().ToString("N");
        // Durable ownership precedes any native Stage creation.
        try
        {
            journal.Own(owned);
            journal.Event("start", new { stageId = owned, place, position, mode = lifecycleOnly ? "lifecycle" : "capture", presets = lifecycleOnly ? [LightPreset.Warm] : Sequence });
            capture.Prepare(); index = 0; CompletedCaptures = 0;
            phase = Phase.Prepare; deadline = now + 5000; Status = "Waiting for r8 OFF acknowledgment";
        }
        catch { Stop("start failed"); throw; }
    }

    public void Tick(long now, EnvironmentState environment)
    {
        if (!Running) { RetryCleanup(); return; }
        try
        {
            if (!environment.Ready || environment.Place != place || !stage.Available)
            { Stop("location/logout/provider changed"); return; }
            if (!lifecycleOnly && Vector3.Distance(environment.Player, player) > .15f)
            { Stop("player moved; capture pairing cancelled"); return; }
            if (now > deadline) { Stop("bounded phase timeout"); return; }
            switch (phase)
            {
                case Phase.Prepare:
                    if (capture.PollPrepare().Done)
                    {
                        if (!lifecycleOnly) Apply(now);
                        else
                        {
                            if (owned is null || !stage.Apply(owned, position, LightPreset.Warm)) throw new InvalidOperationException("Stagehand rejected lifecycle lamp");
                            journal.Event("lifecycle-light", new { preset = LightPreset.Warm, durationSeconds = 60, captureEnabled = false });
                            phase = Phase.Lifecycle; deadline = now + 60000;
                            Status = "Lifecycle warm lamp; no capture; automatic cleanup within 60 seconds";
                        }
                    }
                    break;
                case Phase.Settle:
                    if (now >= readyAt)
                    { capture.Begin(); phase = Phase.Capture; deadline = now + 15000; Status = $"Capturing {Sequence[index]}"; }
                    break;
                case Phase.Capture:
                    var result = capture.Poll();
                    if (!result.Done) break;
                    journal.Event("capture", new { preset = Sequence[index], directory = result.Directory });
                    ++CompletedCaptures; ++index;
                    if (index == Sequence.Length) Stop("completed three captures");
                    else Apply(now);
                    break;
            }
        }
        catch (Exception e) { Stop("error: " + e.Message); }
    }

    private void Apply(long now)
    {
        if (owned is null || !stage.Apply(owned, position, Sequence[index])) throw new InvalidOperationException("Stagehand rejected owned preset");
        var color = Sequence[index] == LightPreset.Off ? Vector3.Zero : Sequence[index] == LightPreset.Warm ? new Vector3(1, .35f, .1f) : new Vector3(.1f, .35f, 1);
        journal.Event("preset", new { preset = Sequence[index], color, position, intensity = 8, range = 10, extraShadows = false });
        phase = Phase.Settle; readyAt = now + 2000; deadline = now + 6000; Status = $"Settling {Sequence[index]}";
    }

    public void Stop(string reason)
    {
        if (!Running && owned is null && cleanupPending.Count == 0) return;
        phase = Phase.Idle; Status = reason;
        try { capture.Cancel(); } catch { /* Stage cleanup must still run. */ }
        if (owned is not null)
        {
            if (!cleanupPending.Contains(owned)) cleanupPending.Add(owned);
            owned = null;
        }
        RetryCleanup();
        try { journal.Event("stop", new { reason, completedCaptures = CompletedCaptures, cleanupPending = cleanupPending.Count }); } catch { }
    }

    private void RetryCleanup()
    {
        if (cleanupPending.Count == 0) return;
        try
        {
            if (!stage.Available) return;
            foreach (var id in cleanupPending.ToArray())
                if (stage.Remove(id)) { journal.Released(id); cleanupPending.Remove(id); }
        }
        catch { /* Keep durable ownership and retry when the provider returns. */ }
    }
    private static bool Finite(Vector3 v) => float.IsFinite(v.X) && float.IsFinite(v.Y) && float.IsFinite(v.Z);
}
