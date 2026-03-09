using System.Text.Json.Nodes;
using SbcControllerCore.Config;
using SbcControllerCore.Driver;
using SbcControllerCore.Messaging;

namespace SbcControllerCore.Services;

public sealed class IoService
{
    private readonly ISbcHardwareDriver _hardware;
    private readonly SbcStateParser _parser;
    private readonly MqttJsonClient _mqtt;
    private readonly TopicMap _topics;
    private readonly int _pollMs;
    private readonly RuntimeContextLog _log;
    private readonly object _frameLock = new();

    private JsonObject? _queuedFrame;

    public IoService(
        ISbcHardwareDriver hardware,
        SbcStateParser parser,
        MqttJsonClient mqtt,
        TopicMap topics,
        int pollMs,
        RuntimeContextLog log)
    {
        _hardware = hardware;
        _parser = parser;
        _mqtt = mqtt;
        _topics = topics;
        _pollMs = Math.Max(1, pollMs);
        _log = log;

        _mqtt.Subscribe(_topics.IoLedFrame, OnLedFrame);
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        _log.Write("sbc-io-service-cs", "started", new { poll_ms = _pollMs, topic_raw = _topics.IoRawState, topic_led_frame = _topics.IoLedFrame });

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var raw = await _hardware.ReadRawAsync(cancellationToken).ConfigureAwait(false);
                var state = _parser.Parse(raw);

                var payload = new JsonObject
                {
                    ["type"] = "io_raw_state",
                    ["state"] = state.ToJsonObject(),
                    ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                };

                await _mqtt.PublishAsync(_topics.IoRawState, payload, cancellationToken).ConfigureAwait(false);

                JsonObject? frameToApply = null;
                lock (_frameLock)
                {
                    if (_queuedFrame is not null)
                    {
                        frameToApply = (JsonObject)_queuedFrame.DeepClone();
                        _queuedFrame = null;
                    }
                }

                if (frameToApply is not null)
                {
                    await _hardware.ApplyLedFrameAsync(frameToApply, cancellationToken).ConfigureAwait(false);
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
            _log.Write("sbc-io-service-cs", "stopped", new { });
        }
    }

    private void OnLedFrame(JsonObject payload, string _)
    {
        lock (_frameLock)
        {
            _queuedFrame = (JsonObject)payload.DeepClone();
        }
    }
}
