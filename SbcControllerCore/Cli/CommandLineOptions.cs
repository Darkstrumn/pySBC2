namespace SbcControllerCore.Cli;

public sealed class CommandLineOptions
{
    public string Role { get; init; } = "io";
    public string ConfigPath { get; init; } = "sbc_config.json";
    public string HardwareMode { get; init; } = "mock";
    public bool ShowHelp { get; init; }

    public static string Usage =>
        """
        Usage:
          dotnet run --project SbcControllerCore -- <role> [--config <path>] [--hardware <mode>]

        Roles:
          io       Poll hardware, publish sbc/io/raw_state, consume sbc/io/led_frame
          reader   Consume sbc/io/raw_state, publish event topics (raw_state/button/gear/tuner)
          writer   Consume sbc/cmd/led + sbc/cmd/led_frame, publish sbc/io/led_frame

        Options:
          --config <path>    Config file path (default: sbc_config.json)
          --hardware <mode>  IO hardware backend (default: mock)
          --help             Show this help
        """;

    public static CommandLineOptions Parse(string[] args)
    {
        var role = "io";
        var configPath = "sbc_config.json";
        var hardwareMode = "mock";
        var showHelp = false;
        var roleSet = false;

        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            switch (arg)
            {
                case "--help":
                case "-h":
                    showHelp = true;
                    break;
                case "--config":
                    if (i + 1 >= args.Length)
                    {
                        throw new ArgumentException("missing value for --config");
                    }
                    configPath = args[++i];
                    break;
                case "--hardware":
                    if (i + 1 >= args.Length)
                    {
                        throw new ArgumentException("missing value for --hardware");
                    }
                    hardwareMode = args[++i].Trim().ToLowerInvariant();
                    break;
                default:
                    if (arg.StartsWith("--", StringComparison.Ordinal))
                    {
                        throw new ArgumentException($"unknown option '{arg}'");
                    }
                    if (roleSet)
                    {
                        throw new ArgumentException($"unexpected argument '{arg}'");
                    }
                    role = arg.Trim().ToLowerInvariant();
                    roleSet = true;
                    break;
            }
        }

        return new CommandLineOptions
        {
            Role = role,
            ConfigPath = configPath,
            HardwareMode = hardwareMode,
            ShowHelp = showHelp,
        };
    }
}
