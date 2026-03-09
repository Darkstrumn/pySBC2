using System.Text.Json.Nodes;
using SbcControllerCore.Config;
using SbcControllerCore.Driver;
using SbcControllerCore.Messaging;

namespace SbcControllerCore.Services;

public sealed class ReaderService
{
    private readonly MqttJsonClient _mqtt;
    private readonly TopicMap _topics;
    private readonly RuntimeContextLog _log;
    private readonly int _pollMs;
    private readonly object _stateLock = new();

    private SbcState? _latestState;
    private bool _haveNewState;
    private bool[]? _prevButtons;
    private int? _prevGear;
    private int? _prevTuner;

    public ReaderService(MqttJsonClient mqtt, TopicMap topics, RuntimeContextLog log, int pollMs)
    {
        _mqtt = mqtt;
        _topics = topics;
        _log = log;
        _pollMs = Math.Max(1, pollMs);

        _mqtt.Subscribe(_topics.IoRawState, OnRawState);
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        _log.Write("sbc-reader-service-cs", "started", new { poll_ms = _pollMs, topic_in = _topics.IoRawState });

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                SbcState? state = null;
                lock (_stateLock)
                {
                    if (_haveNewState && _latestState is not null)
                    {
                        state = _latestState.Clone();
                        _haveNewState = false;
                    }
                }

                if (state is null)
                {
                    await Task.Delay(_pollMs, cancellationToken).ConfigureAwait(false);
                    continue;
                }

                var rawStateEvent = new JsonObject
                {
                    ["type"] = "raw_state",
                    ["buttons"] = ToButtonsArray(state.Buttons),
                    ["analogs"] = state.ToAnalogsJsonObject(),
                    ["tuner"] = state.Tuner,
                    ["gear"] = state.Gear,
                    ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                };
                await _mqtt.PublishAsync(_topics.EventRawState, rawStateEvent, cancellationToken).ConfigureAwait(false);

                var currentButtons = (bool[])state.Buttons.Clone();
                if (_prevButtons is null)
                {
                    _prevButtons = (bool[])currentButtons.Clone();
                }

                for (var i = 0; i < currentButtons.Length; i++)
                {
                    var previous = i < _prevButtons.Length && _prevButtons[i];
                    var pressed = currentButtons[i];
                    if (previous == pressed)
                    {
                        continue;
                    }

                    var controlName = i < SbcTemplate.ButtonNames.Length ? SbcTemplate.ButtonNames[i] : $"Button{i}";
                    var buttonEvent = new JsonObject
                    {
                        ["type"] = "button",
                        ["control"] = controlName,
                        ["index"] = i,
                        ["pressed"] = pressed,
                        ["logical_state"] = pressed,
                        ["source"] = "physical",
                        ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    };
                    await _mqtt.PublishAsync(_topics.EventButton, buttonEvent, cancellationToken).ConfigureAwait(false);
                }
                _prevButtons = currentButtons;

                if (_prevGear is null || state.Gear != _prevGear.Value)
                {
                    var gearEvent = new JsonObject
                    {
                        ["type"] = "gear_change",
                        ["gear"] = state.Gear,
                        ["source"] = "physical",
                        ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    };
                    await _mqtt.PublishAsync($"{_topics.BaseTopic}/events/gear_change", gearEvent, cancellationToken).ConfigureAwait(false);
                    _prevGear = state.Gear;
                }

                if (_prevTuner is null || state.Tuner != _prevTuner.Value)
                {
                    var tunerEvent = new JsonObject
                    {
                        ["type"] = "tuner_change",
                        ["tuner"] = state.Tuner,
                        ["source"] = "physical",
                        ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    };
                    await _mqtt.PublishAsync($"{_topics.BaseTopic}/events/tuner_change", tunerEvent, cancellationToken).ConfigureAwait(false);
                    _prevTuner = state.Tuner;
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
            _log.Write("sbc-reader-service-cs", "stopped", new { });
        }
    }

    private void OnRawState(JsonObject payload, string _)
    {
        if (!payload.TryGetPropertyValue("state", out var stateNode) || stateNode is not JsonObject stateObject)
        {
            return;
        }
        if (!SbcState.TryFromJsonObject(stateObject, out var state))
        {
            return;
        }

        lock (_stateLock)
        {
            _latestState = state;
            _haveNewState = true;
        }
    }

    private static JsonArray ToButtonsArray(bool[] buttons)
    {
        var array = new JsonArray();
        foreach (var pressed in buttons)
        {
            array.Add(pressed);
        }
        return array;
    }
}
