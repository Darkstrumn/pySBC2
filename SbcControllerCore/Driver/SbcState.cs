using System.Text.Json.Nodes;

namespace SbcControllerCore.Driver;

public sealed class SbcState
{
    public bool[] Buttons { get; set; } = new bool[SbcTemplate.ButtonNames.Length];
    public int AimX { get; set; }
    public int AimY { get; set; }
    public int Rotation { get; set; }
    public int SightX { get; set; }
    public int SightY { get; set; }
    public int LeftPedal { get; set; }
    public int MiddlePedal { get; set; }
    public int RightPedal { get; set; }
    public int Tuner { get; set; }
    public int Gear { get; set; }

    public SbcState Clone()
    {
        return new SbcState
        {
            Buttons = (bool[])Buttons.Clone(),
            AimX = AimX,
            AimY = AimY,
            Rotation = Rotation,
            SightX = SightX,
            SightY = SightY,
            LeftPedal = LeftPedal,
            MiddlePedal = MiddlePedal,
            RightPedal = RightPedal,
            Tuner = Tuner,
            Gear = Gear,
        };
    }

    public JsonObject ToJsonObject()
    {
        var buttons = new JsonArray();
        foreach (var pressed in Buttons)
        {
            buttons.Add(pressed);
        }

        return new JsonObject
        {
            ["buttons"] = buttons,
            ["aim_x"] = AimX,
            ["aim_y"] = AimY,
            ["rotation"] = Rotation,
            ["sight_x"] = SightX,
            ["sight_y"] = SightY,
            ["left_pedal"] = LeftPedal,
            ["middle_pedal"] = MiddlePedal,
            ["right_pedal"] = RightPedal,
            ["tuner"] = Tuner,
            ["gear"] = Gear,
        };
    }

    public JsonObject ToAnalogsJsonObject()
    {
        return new JsonObject
        {
            ["aim_x"] = AimX,
            ["aim_y"] = AimY,
            ["rotation"] = Rotation,
            ["sight_x"] = SightX,
            ["sight_y"] = SightY,
            ["left_pedal"] = LeftPedal,
            ["middle_pedal"] = MiddlePedal,
            ["right_pedal"] = RightPedal,
        };
    }

    public static bool TryFromJsonObject(JsonObject obj, out SbcState state)
    {
        state = new SbcState();

        if (!TryGetButtons(obj, out var buttons))
        {
            return false;
        }
        state.Buttons = buttons;

        state.AimX = ReadInt(obj, "aim_x", 0);
        state.AimY = ReadInt(obj, "aim_y", 0);
        state.Rotation = ReadInt(obj, "rotation", 0);
        state.SightX = ReadInt(obj, "sight_x", 0);
        state.SightY = ReadInt(obj, "sight_y", 0);
        state.LeftPedal = ReadInt(obj, "left_pedal", 0);
        state.MiddlePedal = ReadInt(obj, "middle_pedal", 0);
        state.RightPedal = ReadInt(obj, "right_pedal", 0);
        state.Tuner = ReadInt(obj, "tuner", 0);
        state.Gear = ReadInt(obj, "gear", 0);
        return true;
    }

    private static bool TryGetButtons(JsonObject obj, out bool[] buttons)
    {
        buttons = new bool[SbcTemplate.ButtonNames.Length];
        if (!obj.TryGetPropertyValue("buttons", out var buttonsNode) || buttonsNode is not JsonArray array)
        {
            return false;
        }

        var length = Math.Min(array.Count, buttons.Length);
        for (var i = 0; i < length; i++)
        {
            buttons[i] = ReadBool(array[i]);
        }
        return true;
    }

    private static bool ReadBool(JsonNode? node)
    {
        if (node is null)
        {
            return false;
        }
        try
        {
            if (node.TryGetValue<bool>(out var b))
            {
                return b;
            }
            if (node.TryGetValue<int>(out var n))
            {
                return n != 0;
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
        }
        catch
        {
            return false;
        }
        return false;
    }

    private static int ReadInt(JsonObject obj, string key, int defaultValue)
    {
        if (!obj.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue;
        }
        try
        {
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
        }
        catch
        {
            return defaultValue;
        }
        return defaultValue;
    }
}

public sealed record SbcRawPacket(SbcState State);
