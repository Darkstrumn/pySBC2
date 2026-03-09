using System.Text.Json;
using System.Text.Json.Nodes;

namespace SbcControllerCore.Config;

public sealed class EffectiveConfig
{
    private readonly JsonObject _effective;

    private EffectiveConfig(JsonObject effective)
    {
        _effective = effective;
    }

    public static EffectiveConfig Load(string path)
    {
        var content = File.ReadAllText(path);
        var root = JsonNode.Parse(content) as JsonObject
            ?? throw new InvalidDataException("config root must be a JSON object");

        var activeProfile = "default";
        if (root.TryGetPropertyValue("active_profile", out var activeProfileNode) &&
            activeProfileNode is JsonValue activeProfileValue &&
            activeProfileValue.TryGetValue<string>(out var profileValue) &&
            !string.IsNullOrWhiteSpace(profileValue))
        {
            activeProfile = profileValue.Trim();
        }

        var effective = new JsonObject();
        foreach (var pair in root)
        {
            if (string.Equals(pair.Key, "profiles", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            effective[pair.Key] = pair.Value?.DeepClone();
        }

        if (root.TryGetPropertyValue("profiles", out var profilesNode) &&
            profilesNode is JsonObject profiles &&
            profiles.TryGetPropertyValue(activeProfile, out var profileNode) &&
            profileNode is JsonObject profile)
        {
            foreach (var pair in profile)
            {
                effective[pair.Key] = pair.Value?.DeepClone();
            }
        }

        effective["active_profile"] = activeProfile;
        return new EffectiveConfig(effective);
    }

    public JsonObject? GetObject(string key)
    {
        if (_effective.TryGetPropertyValue(key, out var value) && value is JsonObject obj)
        {
            return obj;
        }
        return null;
    }

    public string GetString(string key, string defaultValue)
    {
        if (!_effective.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }
        return ToStringValue(value, defaultValue);
    }

    public int GetInt(string key, int defaultValue)
    {
        if (!_effective.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }
        return ToIntValue(value, defaultValue);
    }

    public bool GetBool(string key, bool defaultValue)
    {
        if (!_effective.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }
        return ToBoolValue(value, defaultValue);
    }

    public int GetSectionInt(string section, string key, int defaultValue)
    {
        var obj = GetObject(section);
        if (obj is null || !obj.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }
        return ToIntValue(value, defaultValue);
    }

    public string GetSectionString(string section, string key, string defaultValue)
    {
        var obj = GetObject(section);
        if (obj is null || !obj.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }
        return ToStringValue(value, defaultValue);
    }

    private static bool ToBoolValue(JsonNode value, bool defaultValue)
    {
        if (value is JsonValue jv)
        {
            if (jv.TryGetValue<bool>(out var b))
            {
                return b;
            }
            if (jv.TryGetValue<string>(out var s))
            {
                if (bool.TryParse(s, out var parsed))
                {
                    return parsed;
                }
                if (int.TryParse(s, out var n))
                {
                    return n != 0;
                }
            }
            if (jv.TryGetValue<int>(out var n2))
            {
                return n2 != 0;
            }
            if (jv.TryGetValue<long>(out var n3))
            {
                return n3 != 0;
            }
        }
        return defaultValue;
    }

    private static int ToIntValue(JsonNode value, int defaultValue)
    {
        if (value is JsonValue jv)
        {
            if (jv.TryGetValue<int>(out var i))
            {
                return i;
            }
            if (jv.TryGetValue<long>(out var l))
            {
                return (int)l;
            }
            if (jv.TryGetValue<double>(out var d))
            {
                return (int)Math.Round(d);
            }
            if (jv.TryGetValue<string>(out var s) && int.TryParse(s, out var parsed))
            {
                return parsed;
            }
        }
        return defaultValue;
    }

    private static string ToStringValue(JsonNode value, string defaultValue)
    {
        if (value is JsonValue jv && jv.TryGetValue<string>(out var s))
        {
            return s ?? defaultValue;
        }
        using var doc = JsonDocument.Parse(value.ToJsonString());
        return doc.RootElement.ValueKind == JsonValueKind.String
            ? doc.RootElement.GetString() ?? defaultValue
            : defaultValue;
    }
}
