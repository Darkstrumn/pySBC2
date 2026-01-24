using System;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using vJoyInterfaceWrap;

namespace PySBC2
{
    public static class SbcSubscriber
    {
        public static void Main(string[] args)
        {
            string host = args.Length > 0 ? args[0] : "raspberrypisbc.local";
            int port = args.Length > 1 ? int.Parse(args[1]) : 8765;
            uint deviceId = args.Length > 2 ? uint.Parse(args[2]) : 1;

            using VJoyOutput vjoy = new VJoyOutput(deviceId);
            if (!vjoy.IsReady)
            {
                Console.WriteLine("vJoy not available. Ensure the vJoy driver is installed and device is enabled.");
                return;
            }

            using var client = new TcpClient();
            client.Connect(host, port);

            using NetworkStream stream = client.GetStream();
            using var reader = new StreamReader(stream, Encoding.UTF8);

            while (true)
            {
                string? line = reader.ReadLine();
                if (line == null)
                {
                    break;
                }

                try
                {
                    using JsonDocument doc = JsonDocument.Parse(line);
                    string type = doc.RootElement.GetProperty("type").GetString() ?? "unknown";
                    if (type == "raw_state")
                    {
                        vjoy.ApplyRawState(doc.RootElement);
                    }
                    else
                    {
                        Console.WriteLine($"{DateTime.Now:HH:mm:ss} {type}: {line}");
                    }
                }
                catch (JsonException)
                {
                    Console.WriteLine($"{DateTime.Now:HH:mm:ss} invalid json: {line}");
                }
            }
        }
    }

    public sealed class VJoyOutput : IDisposable
    {
        private readonly vJoy _joystick;
        private readonly uint _deviceId;
        private readonly int _axisMax = 0x8000;
        private int _buttonCount;

        public bool IsReady { get; }

        public VJoyOutput(uint deviceId)
        {
            _deviceId = deviceId;
            _joystick = new vJoy();
            if (!_joystick.vJoyEnabled())
            {
                IsReady = false;
                return;
            }
            var status = _joystick.GetVJDStatus(_deviceId);
            if (status != VjdStat.VJD_STAT_FREE && status != VjdStat.VJD_STAT_OWN)
            {
                IsReady = false;
                return;
            }
            if (!_joystick.AcquireVJD(_deviceId))
            {
                IsReady = false;
                return;
            }
            IsReady = true;
        }

        public void ApplyRawState(JsonElement root)
        {
            if (!IsReady)
            {
                return;
            }
            if (!root.TryGetProperty("buttons", out JsonElement buttonsElem) || buttonsElem.ValueKind != JsonValueKind.Array)
            {
                return;
            }
            _buttonCount = buttonsElem.GetArrayLength();

            for (int i = 0; i < _buttonCount; i++)
            {
                bool pressed = buttonsElem[i].GetInt32() != 0;
                _joystick.SetBtn(pressed, _deviceId, (uint)(i + 1));
            }

            int gearOffset = _buttonCount;
            int tunerOffset = _buttonCount + 7;
            SetExclusiveButtons(gearOffset, 7, GetGearIndex(root));
            SetExclusiveButtons(tunerOffset, 16, GetTunerIndex(root));

            if (root.TryGetProperty("analogs", out JsonElement analogs) && analogs.ValueKind == JsonValueKind.Object)
            {
                SetAxis(analogs, "aim_x", HID_USAGES.HID_USAGE_RX, -512, 511);
                SetAxis(analogs, "aim_y", HID_USAGES.HID_USAGE_RY, -512, 511);
                SetAxis(analogs, "rotation", HID_USAGES.HID_USAGE_RZ, -512, 511);
                SetAxis(analogs, "sight_x", HID_USAGES.HID_USAGE_SL0, -512, 511);
                SetAxis(analogs, "sight_y", HID_USAGES.HID_USAGE_SL1, -512, 511);
                SetAxis(analogs, "left_pedal", HID_USAGES.HID_USAGE_X, 0, 1023);
                SetAxis(analogs, "middle_pedal", HID_USAGES.HID_USAGE_Y, 0, 1023);
                SetAxis(analogs, "right_pedal", HID_USAGES.HID_USAGE_Z, 0, 1023);
            }
        }

        private void SetAxis(JsonElement analogs, string name, HID_USAGES usage, int min, int max)
        {
            if (!analogs.TryGetProperty(name, out JsonElement valueElem))
            {
                return;
            }
            int value = valueElem.GetInt32();
            int scaled = Scale(value, min, max, 0, _axisMax);
            _joystick.SetAxis(scaled, _deviceId, usage);
        }

        private int GetGearIndex(JsonElement root)
        {
            if (!root.TryGetProperty("gear", out JsonElement gearElem))
            {
                return -1;
            }
            int gear = gearElem.GetInt32();
            return gear switch
            {
                -2 => 0,
                -1 => 1,
                1 => 2,
                2 => 3,
                3 => 4,
                4 => 5,
                5 => 6,
                _ => -1,
            };
        }

        private int GetTunerIndex(JsonElement root)
        {
            if (!root.TryGetProperty("tuner", out JsonElement tunerElem))
            {
                return -1;
            }
            int tuner = tunerElem.GetInt32();
            if (tuner < 0 || tuner > 15)
            {
                return -1;
            }
            return tuner;
        }

        private void SetExclusiveButtons(int offset, int count, int activeIndex)
        {
            for (int i = 0; i < count; i++)
            {
                bool pressed = i == activeIndex;
                _joystick.SetBtn(pressed, _deviceId, (uint)(offset + i + 1));
            }
        }

        private static int Scale(int value, int srcMin, int srcMax, int dstMin, int dstMax)
        {
            if (srcMax == srcMin)
            {
                return dstMin;
            }
            double norm = (value - srcMin) / (double)(srcMax - srcMin);
            int scaled = (int)(dstMin + norm * (dstMax - dstMin));
            if (scaled < dstMin)
            {
                return dstMin;
            }
            if (scaled > dstMax)
            {
                return dstMax;
            }
            return scaled;
        }

        public void Dispose()
        {
            if (IsReady)
            {
                _joystick.RelinquishVJD(_deviceId);
            }
        }
    }
}
