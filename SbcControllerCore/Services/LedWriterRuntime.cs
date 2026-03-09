using System.Text.Json.Nodes;
using SbcControllerCore.Driver;

namespace SbcControllerCore.Services;

public sealed class LedWriterRuntime
{
    private readonly object _lock = new();
    private readonly Queue<JsonObject> _queuedLedCommands = [];
    private readonly Queue<JsonObject> _queuedFrames = [];

    private readonly Dictionary<string, int> _steady = new(StringComparer.Ordinal);
    private readonly Dictionary<string, LedEffect> _effects = new(StringComparer.Ordinal);
    private readonly Dictionary<string, LedPattern> _patterns = new(StringComparer.Ordinal);
    private Dictionary<string, int> _current = SbcTemplate.LedNameToId.Keys.ToDictionary(k => k, _ => 0, StringComparer.Ordinal);

    public void EnqueueLedCommand(JsonObject payload)
    {
        lock (_lock)
        {
            _queuedLedCommands.Enqueue((JsonObject)payload.DeepClone());
        }
    }

    public void EnqueueLedFrame(JsonObject payload)
    {
        lock (_lock)
        {
            _queuedFrames.Enqueue((JsonObject)payload.DeepClone());
        }
    }

    public (bool changed, Dictionary<string, int> map) Tick(double nowSeconds)
    {
        List<JsonObject> queuedCommands;
        List<JsonObject> queuedFrames;
        lock (_lock)
        {
            queuedCommands = _queuedLedCommands.ToList();
            queuedFrames = _queuedFrames.ToList();
            _queuedLedCommands.Clear();
            _queuedFrames.Clear();
        }

        foreach (var frame in queuedFrames)
        {
            ApplyFrame(frame);
        }
        foreach (var command in queuedCommands)
        {
            ApplyCommand(command, nowSeconds);
        }

        var before = new Dictionary<string, int>(_current, StringComparer.Ordinal);
        var output = new Dictionary<string, int>(_current, StringComparer.Ordinal);

        foreach (var pair in _steady)
        {
            output[pair.Key] = SbcTemplate.ClampIntensity(pair.Value);
        }

        var expiredEffects = new List<string>();
        foreach (var pair in _effects)
        {
            var level = EffectIntensity(pair.Value, nowSeconds);
            if (level is null)
            {
                expiredEffects.Add(pair.Key);
                continue;
            }
            output[pair.Key] = SbcTemplate.ClampIntensity(level.Value);
        }
        foreach (var key in expiredEffects)
        {
            _effects.Remove(key);
        }

        var expiredPatterns = new List<string>();
        foreach (var pair in _patterns)
        {
            var level = PatternIntensity(pair.Value, nowSeconds);
            if (level is null)
            {
                expiredPatterns.Add(pair.Key);
                continue;
            }
            output[pair.Key] = SbcTemplate.ClampIntensity(level.Value);
        }
        foreach (var key in expiredPatterns)
        {
            _patterns.Remove(key);
        }

        _current = output;
        var changed = !DictionaryEqual(before, _current);
        return (changed, new Dictionary<string, int>(_current, StringComparer.Ordinal));
    }

    private void ApplyFrame(JsonObject frame)
    {
        if (!frame.TryGetPropertyValue("leds", out var ledsNode) || ledsNode is not JsonObject ledsObj)
        {
            return;
        }

        var mode = ReadString(frame, "mode", "merge").ToLowerInvariant();
        if (mode == "replace")
        {
            foreach (var key in _current.Keys.ToList())
            {
                _current[key] = 0;
            }
            _steady.Clear();
            _effects.Clear();
            _patterns.Clear();
        }

        foreach (var pair in ledsObj)
        {
            var normalized = SbcTemplate.NormalizeLedName(pair.Key);
            if (normalized is null)
            {
                continue;
            }

            var intensity = SbcTemplate.ClampIntensity(ReadInt(pair.Value, 0));
            _current[normalized] = intensity;
            _steady[normalized] = intensity;
            _effects.Remove(normalized);
            _patterns.Remove(normalized);
        }
    }

    private void ApplyCommand(JsonObject command, double nowSeconds)
    {
        var led = SbcTemplate.NormalizeLedName(ReadString(command, "led", string.Empty));
        if (led is null)
        {
            return;
        }

        var mode = ReadString(command, "mode", "steady").ToLowerInvariant();
        var intensity = SbcTemplate.ClampIntensity(ReadInt(command, "intensity", 15));
        var durationMs = command.TryGetPropertyValue("duration_ms", out var durationNode) && durationNode is not null
            ? ReadInt(durationNode, 0)
            : (int?)null;

        if (mode is "clear" or "default")
        {
            _steady.Remove(led);
            _effects.Remove(led);
            _patterns.Remove(led);
            return;
        }

        if (mode is "off" or "steady" or "on")
        {
            _steady[led] = mode == "off" ? 0 : intensity;
            _effects.Remove(led);
            _patterns.Remove(led);
            return;
        }

        if (mode == "blink")
        {
            var periodMs = Math.Max(1, ReadInt(command, "period_ms", 500));
            var onMs = Math.Max(1, ReadInt(command, "on_ms", periodMs / 2));
            _steady.Remove(led);
            _patterns.Remove(led);
            _effects[led] = new LedEffect
            {
                Type = "blink",
                Start = nowSeconds,
                DurationMs = durationMs,
                PeriodMs = periodMs,
                OnMs = onMs,
                Intensity = intensity,
            };
            return;
        }

        if (mode == "breathe")
        {
            var periodMs = Math.Max(1, ReadInt(command, "period_ms", 2000));
            var minVal = SbcTemplate.ClampIntensity(ReadInt(command, "min", 0));
            var maxVal = SbcTemplate.ClampIntensity(ReadInt(command, "max", intensity));
            _steady.Remove(led);
            _patterns.Remove(led);
            _effects[led] = new LedEffect
            {
                Type = "breathe",
                Start = nowSeconds,
                DurationMs = durationMs,
                PeriodMs = periodMs,
                Min = minVal,
                Max = maxVal,
            };
            return;
        }

        if (mode == "pattern")
        {
            var steps = new List<PatternStep>();
            if (command.TryGetPropertyValue("steps", out var stepsNode) && stepsNode is JsonArray stepsArray)
            {
                foreach (var node in stepsArray)
                {
                    if (node is not JsonObject stepObj)
                    {
                        continue;
                    }
                    steps.Add(new PatternStep
                    {
                        DurationMs = Math.Max(1, ReadInt(stepObj, "duration_ms", 100)),
                        Intensity = SbcTemplate.ClampIntensity(ReadInt(stepObj, "intensity", 0)),
                    });
                }
            }
            if (steps.Count == 0)
            {
                return;
            }

            _steady.Remove(led);
            _effects.Remove(led);
            _patterns[led] = new LedPattern
            {
                Start = nowSeconds,
                Steps = steps,
                Repeat = ReadBool(command, "repeat", true),
                HoldFinal = ReadBool(command, "hold_final", false),
            };
        }
    }

    private static int? EffectIntensity(LedEffect effect, double nowSeconds)
    {
        if (effect.DurationMs is not null && (nowSeconds - effect.Start) * 1000.0 >= effect.DurationMs.Value)
        {
            return null;
        }

        var elapsed = Math.Max(0.0, nowSeconds - effect.Start);
        if (effect.Type == "blink")
        {
            var periodS = Math.Max(0.001, effect.PeriodMs / 1000.0);
            var onS = Math.Max(0.0, effect.OnMs / 1000.0);
            return (elapsed % periodS) <= onS ? effect.Intensity : 0;
        }
        if (effect.Type == "breathe")
        {
            var periodS = Math.Max(0.001, effect.PeriodMs / 1000.0);
            var cycle = (elapsed % periodS) / periodS;
            var tri = 1.0 - Math.Abs(2.0 * cycle - 1.0);
            return (int)Math.Round(effect.Min + (effect.Max - effect.Min) * tri);
        }
        return null;
    }

    private static int? PatternIntensity(LedPattern pattern, double nowSeconds)
    {
        if (pattern.Steps.Count == 0)
        {
            return null;
        }

        var totalMs = pattern.Steps.Sum(s => s.DurationMs);
        if (totalMs <= 0)
        {
            return null;
        }

        var elapsedMs = (int)Math.Max(0.0, (nowSeconds - pattern.Start) * 1000.0);
        if (!pattern.Repeat && elapsedMs >= totalMs)
        {
            return pattern.HoldFinal ? pattern.Steps[^1].Intensity : null;
        }

        var phase = elapsedMs % totalMs;
        var cursor = 0;
        foreach (var step in pattern.Steps)
        {
            cursor += step.DurationMs;
            if (phase < cursor)
            {
                return step.Intensity;
            }
        }

        return pattern.Steps[^1].Intensity;
    }

    private static int ReadInt(JsonObject obj, string key, int defaultValue)
    {
        if (!obj.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue;
        }
        return ReadInt(node, defaultValue);
    }

    private static int ReadInt(JsonNode? node, int defaultValue)
    {
        if (node is null)
        {
            return defaultValue;
        }
        if (node.TryGetValue<int>(out var i))
        {
            return i;
        }
        if (node.TryGetValue<long>(out var l))
        {
            return (int)l;
        }
        if (node.TryGetValue<double>(out var d))
        {
            return (int)Math.Round(d);
        }
        if (node.TryGetValue<string>(out var s) && int.TryParse(s, out var parsed))
        {
            return parsed;
        }
        return defaultValue;
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

    private static string ReadString(JsonObject obj, string key, string defaultValue)
    {
        if (!obj.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue;
        }
        if (node.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
        {
            return s;
        }
        return defaultValue;
    }

    private static bool DictionaryEqual(Dictionary<string, int> a, Dictionary<string, int> b)
    {
        if (a.Count != b.Count)
        {
            return false;
        }
        foreach (var pair in a)
        {
            if (!b.TryGetValue(pair.Key, out var other) || other != pair.Value)
            {
                return false;
            }
        }
        return true;
    }

    private sealed class LedEffect
    {
        public string Type { get; init; } = "steady";
        public double Start { get; init; }
        public int? DurationMs { get; init; }
        public int PeriodMs { get; init; } = 500;
        public int OnMs { get; init; } = 250;
        public int Intensity { get; init; }
        public int Min { get; init; }
        public int Max { get; init; } = 15;
    }

    private sealed class LedPattern
    {
        public double Start { get; init; }
        public List<PatternStep> Steps { get; init; } = [];
        public bool Repeat { get; init; } = true;
        public bool HoldFinal { get; init; }
    }

    private sealed class PatternStep
    {
        public int DurationMs { get; init; }
        public int Intensity { get; init; }
    }
}
