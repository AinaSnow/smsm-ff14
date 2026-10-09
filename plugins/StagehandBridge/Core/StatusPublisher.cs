namespace Smsm.StagehandBridge.Core;

/// <summary>Status is observational: a locked file must not fail plugin loading or cleanup.</summary>
public sealed class StatusPublisher(string directory)
{
    private readonly object gate = new();
    private string? last;
    public bool TryPublish(string text)
    {
        lock (gate)
        {
            if (text == last) return true;
            var temporary = Path.Combine(directory, ".status-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream)) writer.Write(text);
                File.Move(temporary, Path.Combine(directory, "status.json"), true);
                last = text;
                return true;
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
            finally
            {
                try { File.Delete(temporary); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }
}
