using System.Text.Json.Nodes;

namespace SbcControllerCore.Driver;

public sealed class MockSbcHardwareDriver : ISbcHardwareDriver
{
    private readonly Random _random = new();
    private readonly int[] _gearCycle = [-2, -1, 1, 2, 3, 4, 5];
    private readonly Dictionary<string, int> _ledState = new(StringComparer.Ordinal);
    private SbcState _state = new();
    private int _tick;
    private bool _opened;

    public Task OpenAsync(CancellationToken cancellationToken)
    {
        _opened = true;
        _state = new SbcState
        {
            Buttons = new bool[SbcTemplate.ButtonNames.Length],
            AimX = 0,
            AimY = 0,
            Rotation = 0,
            SightX = 0,
            SightY = 0,
            LeftPedal = 0,
            MiddlePedal = 0,
            RightPedal = 0,
            Tuner = 0,
            Gear = -1,
        };

        foreach (var ledName in SbcTemplate.LedNameToId.Keys)
        {
            _ledState[ledName] = 0;
        }

        return Task.CompletedTask;
    }

    public Task<SbcRawPacket> ReadRawAsync(CancellationToken cancellationToken)
    {
        if (!_opened)
        {
            throw new InvalidOperationException("mock hardware was not opened");
        }

        _tick++;
        var t = _tick;
        var next = _state.Clone();

        for (var i = 0; i < next.Buttons.Length; i++)
        {
            if (_random.NextDouble() < 0.008)
            {
                next.Buttons[i] = !next.Buttons[i];
            }
        }

        next.AimX = Clamp((int)Math.Round(Math.Sin(t / 22.0) * 511.0), -512, 511);
        next.AimY = Clamp((int)Math.Round(Math.Cos(t / 20.0) * 511.0), -512, 511);
        next.Rotation = Clamp((int)Math.Round(Math.Sin(t / 18.0) * 511.0), -512, 511);
        next.SightX = Clamp((int)Math.Round(Math.Cos(t / 17.0) * 511.0), -512, 511);
        next.SightY = Clamp((int)Math.Round(Math.Sin(t / 19.0) * 511.0), -512, 511);

        next.LeftPedal = Clamp((int)Math.Round((Math.Sin(t / 25.0) * 0.5 + 0.5) * 1023.0), 0, 1023);
        next.MiddlePedal = Clamp((int)Math.Round((Math.Sin((t + 15) / 28.0) * 0.5 + 0.5) * 1023.0), 0, 1023);
        next.RightPedal = Clamp((int)Math.Round((Math.Sin((t + 30) / 24.0) * 0.5 + 0.5) * 1023.0), 0, 1023);

        next.Tuner = (t / 8) % 16;
        next.Gear = _gearCycle[(t / 60) % _gearCycle.Length];

        _state = next;
        return Task.FromResult(new SbcRawPacket(next.Clone()));
    }

    public Task ApplyLedFrameAsync(JsonObject frame, CancellationToken cancellationToken)
    {
        if (frame.TryGetPropertyValue("leds", out var ledsNode) && ledsNode is JsonObject ledsObj)
        {
            foreach (var pair in ledsObj)
            {
                var normalized = SbcTemplate.NormalizeLedName(pair.Key);
                if (normalized is null)
                {
                    continue;
                }

                var intensity = 0;
                if (pair.Value is not null)
                {
                    if (pair.Value.TryGetValue<int>(out var i))
                    {
                        intensity = i;
                    }
                    else if (pair.Value.TryGetValue<string>(out var s) && int.TryParse(s, out var parsed))
                    {
                        intensity = parsed;
                    }
                }

                _ledState[normalized] = SbcTemplate.ClampIntensity(intensity);
            }
        }

        if (ReadBool(frame, "clear_missing", false))
        {
            var provided = new HashSet<string>(StringComparer.Ordinal);
            if (frame.TryGetPropertyValue("leds", out var ledsNode2) && ledsNode2 is JsonObject ledsObj2)
            {
                foreach (var pair in ledsObj2)
                {
                    var normalized = SbcTemplate.NormalizeLedName(pair.Key);
                    if (normalized is not null)
                    {
                        provided.Add(normalized);
                    }
                }
            }

            foreach (var key in _ledState.Keys.ToArray())
            {
                if (!provided.Contains(key))
                {
                    _ledState[key] = 0;
                }
            }
        }

        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        _opened = false;
        return ValueTask.CompletedTask;
    }

    private static bool ReadBool(JsonObject obj, string key, bool defaultValue)
    {
        if (!obj.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue;
        }
        if (node.TryGetValue<bool>(out var b))
        {
            return b;
        }
        if (node.TryGetValue<int>(out var i))
        {
            return i != 0;
        }
        if (node.TryGetValue<string>(out var s))
        {
            if (bool.TryParse(s, out var parsed))
            {
                return parsed;
            }
            if (int.TryParse(s, out var parsedInt))
            {
                return parsedInt != 0;
            }
        }
        return defaultValue;
    }

    private static int Clamp(int value, int min, int max)
    {
        if (value < min)
        {
            return min;
        }
        if (value > max)
        {
            return max;
        }
        return value;
    }
}
