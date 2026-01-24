using System;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace PySBC2
{
    public static class SbcSubscriber
    {
        public static void Main(string[] args)
        {
            string host = args.Length > 0 ? args[0] : "127.0.0.1";
            int port = args.Length > 1 ? int.Parse(args[1]) : 8765;

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
                    Console.WriteLine($"{DateTime.Now:HH:mm:ss} {type}: {line}");
                }
                catch (JsonException)
                {
                    Console.WriteLine($"{DateTime.Now:HH:mm:ss} invalid json: {line}");
                }
            }
        }
    }
}
