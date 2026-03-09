using System.Text.Json.Nodes;

namespace SbcControllerCore.Driver;

public sealed class AnalogProcessor
{
    private readonly Dictionary<string, AxisConfig> _axes = new(StringComparer.OrdinalIgnoreCase);

    public AnalogProcessor(JsonObject? analogSection)
    {
        if (analogSection is null)
        {
            return;
        }

        foreach (var pair in analogSection)
        {
            if (pair.Value is not JsonObject axisObj)
            {
                continue;
            }
            _axes[pair.Key] = AxisConfig.FromJson(axisObj);
        }
    }

    public SbcState Process(SbcState input)
    {
        if (_axes.Count == 0)
        {
            return input;
        }

        var output = input.Clone();
        foreach (var pair in _axes)
        {
            if (!TryReadAxis(output, pair.Key, out var value))
            {
                continue;
            }

            var cfg = pair.Value;
            if (cfg.DeadzoneMode == "center")
            {
                value -= cfg.Center;
            }

            if (cfg.Min is not null && value < cfg.Min.Value)
            {
                value = cfg.Min.Value;
            }
            if (cfg.Max is not null && value > cfg.Max.Value)
            {
                value = cfg.Max.Value;
            }

            cfg.Samples.Enqueue(value);
            while (cfg.Samples.Count > cfg.SmoothingSamples)
            {
                cfg.Samples.Dequeue();
            }

            if (cfg.Samples.Count > 0)
            {
                value = (int)Math.Round(cfg.Samples.Average());
            }

            if (cfg.DeadzoneMode == "center")
            {
                if (Math.Abs(value) <= cfg.Deadzone)
                {
                    value = 0;
                }
            }
            else if (cfg.DeadzoneMode == "low")
            {
                if (value <= cfg.Deadzone)
                {
                    value = 0;
                }
            }

            WriteAxis(output, pair.Key, value);
        }

        return output;
    }

    private static bool TryReadAxis(SbcState state, string axisName, out int value)
    {
        value = axisName switch
        {
            "aim_x" => state.AimX,
            "aim_y" => state.AimY,
            "rotation" => state.Rotation,
            "sight_x" => state.SightX,
            "sight_y" => state.SightY,
            "left_pedal" => state.LeftPedal,
            "middle_pedal" => state.MiddlePedal,
            "right_pedal" => state.RightPedal,
            _ => 0,
        };
        return axisName is "aim_x" or "aim_y" or "rotation" or "sight_x" or "sight_y" or "left_pedal" or "middle_pedal" or "right_pedal";
    }

    private static void WriteAxis(SbcState state, string axisName, int value)
    {
        switch (axisName)
        {
            case "aim_x":
                state.AimX = value;
                break;
            case "aim_y":
                state.AimY = value;
                break;
            case "rotation":
                state.Rotation = value;
                break;
            case "sight_x":
                state.SightX = value;
                break;
            case "sight_y":
                state.SightY = value;
                break;
            case "left_pedal":
                state.LeftPedal = value;
                break;
            case "middle_pedal":
                state.MiddlePedal = value;
                break;
            case "right_pedal":
                state.RightPedal = value;
                break;
        }
    }

    private sealed class AxisConfig
    {
        public string DeadzoneMode { get; init; } = "center";
        public int Center { get; init; }
        public int Deadzone { get; init; }
        public int SmoothingSamples { get; init; } = 1;
        public int? Min { get; init; }
        public int? Max { get; init; }
        public Queue<int> Samples { get; } = [];

        public static AxisConfig FromJson(JsonObject obj)
        {
            var sampleCount = Math.Max(1, ReadInt(obj, "smoothing_samples", 1));
            return new AxisConfig
            {
                DeadzoneMode = ReadString(obj, "deadzone_mode", "center").ToLowerInvariant(),
                Center = ReadInt(obj, "center", 0),
                Deadzone = ReadInt(obj, "deadzone", 0),
                SmoothingSamples = sampleCount,
                Min = ReadNullableInt(obj, "min"),
                Max = ReadNullableInt(obj, "max"),
            };
        }

        private static int ReadInt(JsonObject obj, string key, int defaultValue)
        {
            if (!obj.TryGetPropertyValue(key, out var node) || node is null)
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

        private static int? ReadNullableInt(JsonObject obj, string key)
        {
            if (!obj.TryGetPropertyValue(key, out var node) || node is null)
            {
                return null;
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
            return null;
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
    }
}
