using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Smsm.StagehandBridge.Core;

namespace Smsm.StagehandBridge;

public sealed class CaptureClient(string game) : ICaptureClient
{
    private readonly string root = Path.Combine(game, "SMSM-native-captures");
    private string Command => Path.Combine(root, "ambient-command.txt");
    private string Status => Path.Combine(root, "ambient-status.json");
    private string previous = "", ownedCommand = "";
    private DateTime commandWritten;
    private string? ownedAudit;
    private FileStream? lease;
    private Task? validation;
    private bool offPublished;
    public const string Target = "e86f0d4916054deb";

    public void Prepare()
    {
        if (validation is not null || lease is not null) throw new InvalidOperationException("Capture preparation already active");
        offPublished = false;
        // Only read-only integrity work leaves the framework thread. Publishing,
        // ownership and IPC remain on the framework thread, including on cancel.
        validation = Task.Run(ValidateInstallation);
    }

    private void ValidateInstallation()
    {
        ValidateDirectory(root);
        var receipt = Read(Path.Combine(game, "SMSM-native-install.json")) ?? throw new IOException("Missing native install receipt");
        using (receipt)
        {
            var r = receipt.RootElement;
            if (r.GetProperty("client_build").GetString() != "2026.09.15.0000.0000" ||
                !r.GetProperty("output_audit").GetBoolean() || string.IsNullOrEmpty(r.GetProperty("material_roster_sha256").GetString()))
                throw new InvalidOperationException("Installed add-on does not support verified material sampling");
            foreach (var file in r.GetProperty("files").EnumerateObject())
            {
                if (file.Name is not ("d3d11.dll" or "SMSM.NativeLighting.addon64")) throw new InvalidDataException("Unexpected owned file");
                var hash = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(game, file.Name))));
                if (hash != file.Value.GetString()) throw new InvalidDataException("Native owned file changed");
            }
        }
    }

    private void AcquireAndPublishOff()
    {
        if (File.Exists(Command)) throw new IOException("Another capture command is pending");
        using (var status = Read(Status))
            if (status?.RootElement.GetProperty("output_audit_active").GetBoolean() == true) throw new IOException("Another audit is active");
        lease = new FileStream(Path.Combine(root, ".smsm-m2-session.lock"), FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None,
            4096, FileOptions.DeleteOnClose);
        Publish("off");
        offPublished = true;
    }

    public PollResult PollPrepare()
    {
        if (!offPublished)
        {
            if (validation is null) throw new InvalidOperationException("Preparation was not started");
            if (!validation.IsCompleted) return new(false);
            validation.GetAwaiter().GetResult();
            AcquireAndPublishOff();
            return new(false);
        }
        if (File.Exists(Command)) return new(false);
        using var status = Read(Status);
        if (status is null) return new(false);
        var s = status.RootElement;
        if (s.GetProperty("enabled").GetBoolean() || s.GetProperty("coverage_enabled").GetBoolean() || s.GetProperty("output_audit_active").GetBoolean())
            throw new InvalidOperationException("r8/marker/audit must remain OFF");
        ownedCommand = ""; return new(true);
    }

    public void Begin()
    {
        using var status = Read(Status) ?? throw new IOException("No current add-on status");
        var s = status.RootElement;
        if (s.GetProperty("enabled").GetBoolean() || s.GetProperty("coverage_enabled").GetBoolean() || s.GetProperty("output_audit_active").GetBoolean())
            throw new InvalidOperationException("Native pipeline is busy or effect enabled");
        previous = s.GetProperty("output_audit_directory").GetString() ?? ""; ownedAudit = null;
        Publish($"sample {Target} 0");
    }

    public PollResult Poll()
    {
        if (File.Exists(Command)) return new(false);
        using var status = Read(Status);
        if (status is null) return new(false);
        var s = status.RootElement;
        if (s.GetProperty("enabled").GetBoolean() || s.GetProperty("coverage_enabled").GetBoolean()) throw new InvalidOperationException("Effect changed during capture");
        var name = s.GetProperty("output_audit_directory").GetString() ?? "";
        if (name == previous || name.Length == 0) return new(false);
        if (!Regex.IsMatch(name, "^output-audit-[0-9]+-[0-9]+$")) throw new InvalidDataException("Unexpected capture directory");
        ownedAudit = name;
        if (s.GetProperty("output_audit_active").GetBoolean()) return new(false);
        var directory = Path.Combine(root, name); ValidateDirectory(directory);
        using var report = Read(Path.Combine(directory, "report.json"));
        if (report is null) return new(false);
        var r = report.RootElement;
        if (r.GetProperty("status").GetString() != "complete" || r.GetProperty("mode").GetString() != "sample" ||
            r.GetProperty("selected_shader").GetString() != Target || r.GetProperty("selected_bytes").GetUInt64() > 256UL * 1024 * 1024)
            throw new InvalidDataException("Capture report does not match this finite sample");
        ownedCommand = ""; ownedAudit = null; return new(true, directory);
    }

    public void Cancel()
    {
        try
        {
            // A location/stop event can arrive after native command consumption
            // but before the next normal Poll. Discover that own in-flight audit.
            if (ownedAudit is null && ownedCommand.StartsWith("sample ", StringComparison.Ordinal) && !File.Exists(Command))
            {
                using var latest = Read(Status);
                var name = latest?.RootElement.GetProperty("output_audit_directory").GetString();
                if (name is not null && name != previous && Regex.IsMatch(name, "^output-audit-[0-9]+-[0-9]+$")) ownedAudit = name;
            }
            if (ownedCommand.Length != 0 && File.Exists(Command) && File.GetLastWriteTimeUtc(Command) == commandWritten &&
                File.ReadAllText(Command) == ownedCommand) File.Delete(Command);
            if (ownedAudit is not null && !File.Exists(Command))
            {
                using var status = Read(Status);
                if (status is not null && status.RootElement.GetProperty("output_audit_directory").GetString() == ownedAudit &&
                    status.RootElement.GetProperty("output_audit_active").GetBoolean()) Publish("off");
            }
        }
        finally
        {
            // A cancelled validation may finish reading, but cannot publish or
            // acquire a lock. Observe failures without reviving that session.
            var pendingValidation = validation; validation = null; offPublished = false;
            if (pendingValidation is not null)
                _ = pendingValidation.ContinueWith(t => { _ = t.Exception; }, TaskContinuationOptions.OnlyOnFaulted);
            ownedAudit = null; ownedCommand = ""; lease?.Dispose(); lease = null;
        }
    }

    private void Publish(string text)
    {
        if (File.Exists(Command)) throw new IOException("Pending command was not overwritten");
        var temp = Path.Combine(root, ".smsm-m2-command-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            var bytes = Encoding.ASCII.GetBytes(text + "\n");
            using (var f = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { f.Write(bytes); f.Flush(true); }
            File.Move(temp, Command, false); ownedCommand = text + "\n"; commandWritten = File.GetLastWriteTimeUtc(Command);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
    private static void ValidateDirectory(string path)
    {
        var d = new DirectoryInfo(path);
        if (!d.Exists || (d.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Expected a real initialized capture directory");
    }
    private static JsonDocument? Read(string path)
    {
        try { return JsonDocument.Parse(File.ReadAllBytes(path)); }
        catch (IOException) { return null; }
        catch (JsonException) { return null; } // Native status/report writes may be in progress.
    }
}
