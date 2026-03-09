using System.Text.Json.Nodes;

namespace SbcControllerCore.Config;

public sealed record TopicMap(
    string BaseTopic,
    string CmdButton,
    string CmdMacro,
    string CmdLed,
    string CmdEvent,
    string CmdLedFrame,
    string CmdAiMode,
    string IoRawState,
    string IoLedFrame,
    string EventRawState,
    string EventButton,
    string EventVesselSnapshot,
    string EventAiIntent,
    string EventAiDiagnostic)
{
    public static TopicMap Resolve(EffectiveConfig effective)
    {
        var mqtt = effective.GetObject("mqtt");
        var commandTopics = GetObject(mqtt, "command_topics");
        var baseTopic = ReadString(mqtt, "base_topic", "sbc").Trim('/');

        string Topic(string? suffix, string fallback)
        {
            var raw = (suffix ?? fallback).Trim('/');
            return string.IsNullOrWhiteSpace(raw) ? baseTopic : $"{baseTopic}/{raw}";
        }

        return new TopicMap(
            BaseTopic: baseTopic,
            CmdButton: Topic(ReadString(commandTopics, "button", null), "cmd/button"),
            CmdMacro: Topic(ReadString(commandTopics, "macro", null), "cmd/macro"),
            CmdLed: Topic(ReadString(commandTopics, "led", null), "cmd/led"),
            CmdEvent: Topic(ReadString(commandTopics, "event", null), "cmd/event"),
            CmdLedFrame: Topic(ReadString(commandTopics, "led_frame", null), "cmd/led_frame"),
            CmdAiMode: Topic(ReadString(commandTopics, "ai_mode", null), "cmd/ai_mode"),
            IoRawState: Topic(ReadString(mqtt, "io_raw_topic", null), "io/raw_state"),
            IoLedFrame: Topic(ReadString(mqtt, "io_led_frame_topic", null), "io/led_frame"),
            EventRawState: Topic(ReadString(mqtt, "event_raw_topic", null), "events/raw_state"),
            EventButton: Topic(ReadString(mqtt, "event_button_topic", null), "events/button"),
            EventVesselSnapshot: Topic(ReadString(mqtt, "event_vessel_topic", null), "events/vessel_snapshot"),
            EventAiIntent: Topic(ReadString(mqtt, "event_ai_intent_topic", null), "events/ai_intent"),
            EventAiDiagnostic: Topic(ReadString(mqtt, "event_ai_diagnostic_topic", null), "events/ai_diagnostic")
        );
    }

    private static JsonObject? GetObject(JsonObject? section, string key)
    {
        if (section is null)
        {
            return null;
        }
        return section.TryGetPropertyValue(key, out var node) ? node as JsonObject : null;
    }

    private static string ReadString(JsonObject? section, string key, string? defaultValue)
    {
        if (section is null || !section.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue ?? string.Empty;
        }
        if (node is JsonValue jv && jv.TryGetValue<string>(out var s))
        {
            return s ?? defaultValue ?? string.Empty;
        }
        return defaultValue ?? string.Empty;
    }
}
