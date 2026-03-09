using System.Text.Json;
using System.Text.Json.Nodes;

namespace SbcControllerCore.Messaging;

public sealed class RuntimeContextLog
{
    private readonly string _path;
    private readonly object _sync = new();

    public RuntimeContextLog(string path)
    {
        _path = string.IsNullOrWhiteSpace(path) ? "runtime_context.log" : path;
    }

    public void Write(string service, string message, object? payload)
    {
        var record = new JsonObject
        {
            ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            ["service"] = service,
            ["message"] = message,
            ["payload"] = payload is null ? null : JsonSerializer.SerializeToNode(payload),
        };

        try
        {
            var line = record.ToJsonString() + Environment.NewLine;
            lock (_sync)
            {
                var directory = Path.GetDirectoryName(_path);
                if (!string.IsNullOrWhiteSpace(directory))
                {
                    Directory.CreateDirectory(directory);
                }
                File.AppendAllText(_path, line);
            }
        }
        catch
        {
            // Best-effort logging only.
        }
    }
}
