using System.Text.Json.Nodes;
using SbcControllerCore.Cli;
using SbcControllerCore.Config;
using SbcControllerCore.Driver;
using SbcControllerCore.Messaging;
using SbcControllerCore.Services;

namespace SbcControllerCore;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        CommandLineOptions options;
        try
        {
            options = CommandLineOptions.Parse(args);
        }
        catch (ArgumentException ex)
        {
            Console.Error.WriteLine(ex.Message);
            Console.WriteLine(CommandLineOptions.Usage);
            return 2;
        }

        if (options.ShowHelp)
        {
            Console.WriteLine(CommandLineOptions.Usage);
            return 0;
        }

        EffectiveConfig effective;
        try
        {
            effective = EffectiveConfig.Load(options.ConfigPath);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"failed to load config '{options.ConfigPath}': {ex.Message}");
            return 2;
        }

        var topics = TopicMap.Resolve(effective);
        var log = new RuntimeContextLog(effective.GetSectionString("audit", "path", "runtime_context.log"));
        var mqttSection = effective.GetObject("mqtt");
        var mqttEnabled = ReadBool(mqttSection, "enabled", true);
        if (!mqttEnabled)
        {
            Console.Error.WriteLine("mqtt.enabled is false in config; C# process services require MQTT to run.");
            return 2;
        }

        using var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            cts.Cancel();
        };

        await using var mqtt = new MqttJsonClient(mqttSection, $"sbc-{options.Role}-service-cs", log);
        await mqtt.StartAsync(cts.Token);

        try
        {
            switch (options.Role)
            {
                case "io":
                    await RunIoAsync(options, effective, topics, mqtt, log, cts.Token);
                    break;
                case "reader":
                    await RunReaderAsync(effective, topics, mqtt, log, cts.Token);
                    break;
                case "writer":
                    await RunWriterAsync(effective, topics, mqtt, log, cts.Token);
                    break;
                default:
                    Console.Error.WriteLine($"unknown role '{options.Role}'.");
                    Console.WriteLine(CommandLineOptions.Usage);
                    return 2;
            }
        }
        catch (OperationCanceledException)
        {
            // Graceful shutdown.
        }
        finally
        {
            await mqtt.StopAsync(CancellationToken.None);
        }

        return 0;
    }

    private static async Task RunIoAsync(
        CommandLineOptions options,
        EffectiveConfig effective,
        TopicMap topics,
        MqttJsonClient mqtt,
        RuntimeContextLog log,
        CancellationToken cancellationToken)
    {
        var analogProcessor = new AnalogProcessor(effective.GetObject("analog"));
        var parser = new SbcStateParser(analogProcessor);
        var pollMs = Math.Max(
            1,
            effective.GetSectionInt("services", "reader_poll_ms", effective.GetInt("poll_interval_ms", 4)));

        await using var hardware = options.HardwareMode switch
        {
            "mock" => new MockSbcHardwareDriver(),
            _ => throw new InvalidOperationException(
                $"unsupported hardware mode '{options.HardwareMode}'. Supported: mock"),
        };
        await hardware.OpenAsync(cancellationToken);

        var service = new IoService(hardware, parser, mqtt, topics, pollMs, log);
        await service.RunAsync(cancellationToken);
    }

    private static async Task RunReaderAsync(
        EffectiveConfig effective,
        TopicMap topics,
        MqttJsonClient mqtt,
        RuntimeContextLog log,
        CancellationToken cancellationToken)
    {
        var pollMs = Math.Max(
            1,
            effective.GetSectionInt("services", "reader_poll_ms", effective.GetInt("poll_interval_ms", 4)));
        var service = new ReaderService(mqtt, topics, log, pollMs);
        await service.RunAsync(cancellationToken);
    }

    private static async Task RunWriterAsync(
        EffectiveConfig effective,
        TopicMap topics,
        MqttJsonClient mqtt,
        RuntimeContextLog log,
        CancellationToken cancellationToken)
    {
        var pollMs = Math.Max(
            1,
            effective.GetSectionInt("services", "writer_poll_ms", effective.GetInt("poll_interval_ms", 4)));
        var runtime = new LedWriterRuntime();
        var service = new WriterService(mqtt, topics, runtime, pollMs, log);
        await service.RunAsync(cancellationToken);
    }

    private static bool ReadBool(JsonObject? section, string key, bool defaultValue)
    {
        if (section is null || !section.TryGetPropertyValue(key, out var value) || value is null)
        {
            return defaultValue;
        }

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
        }

        return defaultValue;
    }
}
