using System.Diagnostics;
using System.Text.Json.Nodes;
using SbcControllerCore.Config;
using SbcControllerCore.Messaging;

namespace SbcControllerCore.Services;

public sealed class WriterService
{
    private readonly MqttJsonClient _mqtt;
    private readonly TopicMap _topics;
    private readonly LedWriterRuntime _runtime;
    private readonly int _pollMs;
    private readonly RuntimeContextLog _log;

    public WriterService(
        MqttJsonClient mqtt,
        TopicMap topics,
        LedWriterRuntime runtime,
        int pollMs,
        RuntimeContextLog log)
    {
        _mqtt = mqtt;
        _topics = topics;
        _runtime = runtime;
        _pollMs = Math.Max(1, pollMs);
        _log = log;

        _mqtt.Subscribe(_topics.CmdLed, OnLedCommand);
        _mqtt.Subscribe(_topics.CmdLedFrame, OnLedFrame);
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        _log.Write("sbc-writer-service-cs", "started", new { poll_ms = _pollMs, topic_cmd_led = _topics.CmdLed, topic_io_led_frame = _topics.IoLedFrame });

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var now = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
                var (changed, map) = _runtime.Tick(now);
                if (changed)
                {
                    var leds = new JsonObject();
                    foreach (var pair in map)
                    {
                        leds[pair.Key] = pair.Value;
                    }

                    var payload = new JsonObject
                    {
                        ["type"] = "io_led_frame",
                        ["source"] = "writer_service_cs",
                        ["clear_missing"] = true,
                        ["leds"] = leds,
                        ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    };
                    await _mqtt.PublishAsync(_topics.IoLedFrame, payload, cancellationToken).ConfigureAwait(false);
                }

                await Task.Delay(_pollMs, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            // Graceful cancellation.
        }
        finally
        {
            _log.Write("sbc-writer-service-cs", "stopped", new { });
        }
    }

    private void OnLedCommand(JsonObject payload, string _) => _runtime.EnqueueLedCommand(payload);

    private void OnLedFrame(JsonObject payload, string _) => _runtime.EnqueueLedFrame(payload);
}
