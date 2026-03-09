namespace SbcControllerCore.Driver;

public static class SbcTemplate
{
    public static readonly string[] ButtonNames =
    [
        "RightJoyMainWeapon",
        "RightJoyFire",
        "RightJoyLockOn",
        "Eject",
        "CockpitHatch",
        "Ignition",
        "Start",
        "MultiMonOpenClose",
        "MultiMonMapZoomInOut",
        "MultiMonModeSelect",
        "MultiMonSubMonitor",
        "MainMonZoomIn",
        "MainMonZoomOut",
        "FunctionFSS",
        "FunctionManipulator",
        "FunctionLineColorChange",
        "Washing",
        "Extinguisher",
        "Chaff",
        "FunctionTankDetach",
        "FunctionOverride",
        "FunctionNightScope",
        "FunctionF1",
        "FunctionF2",
        "FunctionF3",
        "WeaponCtrlMain",
        "WeaponCtrlSub",
        "WeaponCtrlMagazineChange",
        "Comm1",
        "Comm2",
        "Comm3",
        "Comm4",
        "Comm5",
        "LeftJoySightChange",
        "ToggleFilterControl",
        "ToggleOxygenSupply",
        "ToggleFuelFlowRate",
        "ToggleBufferMaterial",
        "ToggleVTLocation",
    ];

    public static readonly Dictionary<string, int> LedNameToId = new(StringComparer.Ordinal)
    {
        ["Eject"] = 4,
        ["CockpitHatch"] = 5,
        ["Ignition"] = 6,
        ["Start"] = 7,
        ["OpenClose"] = 8,
        ["MapZoomInOut"] = 9,
        ["ModeSelect"] = 10,
        ["SubMonitorModeSelect"] = 11,
        ["MainMonitorZoomIn"] = 12,
        ["MainMonitorZoomOut"] = 13,
        ["ForecastShootingSystem"] = 14,
        ["Manipulator"] = 15,
        ["LineColorChange"] = 16,
        ["Washing"] = 17,
        ["Extinguisher"] = 18,
        ["Chaff"] = 19,
        ["TankDetach"] = 20,
        ["Override"] = 21,
        ["NightScope"] = 22,
        ["F1"] = 23,
        ["F2"] = 24,
        ["F3"] = 25,
        ["MainWeaponControl"] = 26,
        ["SubWeaponControl"] = 27,
        ["MagazineChange"] = 28,
        ["Comm1"] = 29,
        ["Comm2"] = 30,
        ["Comm3"] = 31,
        ["Comm4"] = 32,
        ["Comm5"] = 33,
        ["GearR"] = 35,
        ["GearN"] = 36,
        ["Gear1"] = 37,
        ["Gear2"] = 38,
        ["Gear3"] = 39,
        ["Gear4"] = 40,
        ["Gear5"] = 41,
    };

    public static readonly Dictionary<string, string> LedNameAlias =
        LedNameToId.Keys.ToDictionary(k => k.ToLowerInvariant(), v => v, StringComparer.OrdinalIgnoreCase);

    public static int ClampIntensity(int value)
    {
        if (value < 0)
        {
            return 0;
        }
        if (value > 15)
        {
            return 15;
        }
        return value;
    }

    public static string? NormalizeLedName(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var raw = value.Trim();
        if (LedNameToId.ContainsKey(raw))
        {
            return raw;
        }

        return LedNameAlias.TryGetValue(raw.ToLowerInvariant(), out var resolved) ? resolved : null;
    }
}
