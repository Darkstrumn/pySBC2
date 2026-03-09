using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MQTTnet;
using MQTTnet.Protocol;

namespace SbcControllerCore.Messaging;

public sealed class MqttJsonClient : IAsyncDisposable
{
    private readonly string _host;
    private readonly int _port;
    private readonly int _keepAliveSeconds;
    private readonly string _username;
    private readonly string _password;
    private readonly MqttQualityOfServiceLevel _publishQos;
    private readonly bool _retainDefault;
    private readonly string _clientId;
    private readonly RuntimeContextLog? _log;
    private readonly object _subscriptionsLock = new();
    private readonly List<Subscription> _subscriptions = [];
    private readonly SemaphoreSlim _connectGate = new(1, 1);
    private readonly CancellationTokenSource _lifetimeCts = new();

    private IMqttClient? _client;
    private MqttClientOptions? _options;
    private Task? _reconnectTask;
    private bool _stopping;
    private bool _disposed;

    public MqttJsonClient(JsonObject? mqttSection, string clientId, RuntimeContextLog? log)
    {
        _clientId = clientId;
        _log = log;

        _host = ReadString(mqttSection, "host", "127.0.0.1");
        _port = ReadInt(mqttSection, "port", 1883);
        _keepAliveSeconds = Math.Max(5, ReadInt(mqttSection, "keepalive", 60));
        _username = ReadString(mqttSection, "username", string.Empty);
        _password = ReadString(mqttSection, "password", string.Empty);
        _publishQos = ToQos(ReadInt(mqttSection, "publish_qos", 0));
        _retainDefault = ReadBool(mqttSection, "retain", false);
    }

    public bool IsConnected => _client?.IsConnected == true;

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        EnsureNotDisposed();
        _stopping = false;

        if (_client is null)
        {
            var factory = new MqttClientFactory();
            _client = factory.CreateMqttClient();
            _client.ApplicationMessageReceivedAsync += OnMessageReceivedAsync;
            _client.ConnectedAsync += OnConnectedAsync;
            _client.DisconnectedAsync += OnDisconnectedAsync;
        }

        _options = BuildOptions();
        await ConnectInternalAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        _stopping = true;
        _lifetimeCts.Cancel();

        if (_reconnectTask is not null)
        {
            try
            {
                await _reconnectTask.ConfigureAwait(false);
            }
            catch
            {
                // Ignore reconnect-loop teardown errors.
            }
            _reconnectTask = null;
        }

        if (_client is not null)
        {
            try
            {
                await _client.DisconnectAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
            }
            catch
            {
                // Ignore disconnect errors during shutdown.
            }
        }
    }

    public void Subscribe(string topicFilter, Action<JsonObject, string> handler)
    {
        var filter = topicFilter.Trim();
        if (string.IsNullOrWhiteSpace(filter))
        {
            throw new ArgumentException("topic filter cannot be blank", nameof(topicFilter));
        }

        lock (_subscriptionsLock)
        {
            _subscriptions.Add(new Subscription(filter, handler));
        }

        if (IsConnected)
        {
            _ = SubscribeFilterAsync(filter, CancellationToken.None);
        }
    }

    public async Task PublishAsync(
        string topic,
        JsonNode payload,
        CancellationToken cancellationToken,
        MqttQualityOfServiceLevel? qos = null,
        bool? retain = null)
    {
        if (_client is null || !_client.IsConnected)
        {
            return;
        }

        var json = payload.ToJsonString();
        var message = new MqttApplicationMessageBuilder()
            .WithTopic(topic)
            .WithPayload(Encoding.UTF8.GetBytes(json))
            .WithQualityOfServiceLevel(qos ?? _publishQos)
            .WithRetainFlag(retain ?? _retainDefault)
            .Build();

        try
        {
            await _client.PublishAsync(message, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _log?.Write(_clientId, "mqtt_publish_failed", new { topic, error = ex.Message });
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        await StopAsync(CancellationToken.None).ConfigureAwait(false);
        _client?.Dispose();
        _connectGate.Dispose();
        _lifetimeCts.Dispose();
    }

    private async Task OnConnectedAsync(MqttClientConnectedEventArgs args)
    {
        List<string> filters;
        lock (_subscriptionsLock)
        {
            filters = _subscriptions.Select(s => s.Filter).Distinct(StringComparer.Ordinal).ToList();
        }

        foreach (var filter in filters)
        {
            await SubscribeFilterAsync(filter, _lifetimeCts.Token).ConfigureAwait(false);
        }

        _log?.Write(_clientId, "mqtt_connected", new { host = _host, port = _port, subscriptions = filters });
    }

    private Task OnDisconnectedAsync(MqttClientDisconnectedEventArgs args)
    {
        _log?.Write(_clientId, "mqtt_disconnected", new { reason = args.Reason.ToString() });

        if (_stopping || _disposed)
        {
            return Task.CompletedTask;
        }

        if (_reconnectTask is null || _reconnectTask.IsCompleted)
        {
            _reconnectTask = Task.Run(() => ReconnectLoopAsync(_lifetimeCts.Token), CancellationToken.None);
        }

        return Task.CompletedTask;
    }

    private Task OnMessageReceivedAsync(MqttApplicationMessageReceivedEventArgs args)
    {
        var topic = args.ApplicationMessage.Topic ?? string.Empty;
        var payloadBytes = args.ApplicationMessage.PayloadSegment.Array is null
            ? args.ApplicationMessage.PayloadSegment.ToArray()
            : args.ApplicationMessage.PayloadSegment.Array;

        JsonObject payload;
        try
        {
            var text = payloadBytes is null ? "{}" : Encoding.UTF8.GetString(payloadBytes);
            payload = JsonNode.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text) as JsonObject ?? new JsonObject();
        }
        catch
        {
            _log?.Write(_clientId, "mqtt_bad_payload", new { topic });
            return Task.CompletedTask;
        }

        List<Subscription> subs;
        lock (_subscriptionsLock)
        {
            subs = _subscriptions.ToList();
        }

        foreach (var sub in subs)
        {
            if (!TopicMatches(sub.Filter, topic))
            {
                continue;
            }

            try
            {
                sub.Handler(payload, topic);
            }
            catch (Exception ex)
            {
                _log?.Write(_clientId, "mqtt_handler_error", new { topic, filter = sub.Filter, error = ex.Message });
            }
        }

        return Task.CompletedTask;
    }

    private async Task ConnectInternalAsync(CancellationToken cancellationToken)
    {
        if (_client is null || _options is null)
        {
            return;
        }

        await _connectGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_client.IsConnected)
            {
                return;
            }
            await _client.ConnectAsync(_options, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _log?.Write(_clientId, "mqtt_connect_failed", new { host = _host, port = _port, error = ex.Message });
            throw;
        }
        finally
        {
            _connectGate.Release();
        }
    }

    private async Task ReconnectLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested && !_stopping && !_disposed)
        {
            try
            {
                await ConnectInternalAsync(cancellationToken).ConfigureAwait(false);
                if (IsConnected)
                {
                    return;
                }
            }
            catch
            {
                // Keep retrying.
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private async Task SubscribeFilterAsync(string filter, CancellationToken cancellationToken)
    {
        if (_client is null || !_client.IsConnected)
        {
            return;
        }

        try
        {
            var topicFilter = new MqttTopicFilterBuilder()
                .WithTopic(filter)
                .WithQualityOfServiceLevel(_publishQos)
                .Build();

            await _client.SubscribeAsync(topicFilter, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _log?.Write(_clientId, "mqtt_subscribe_failed", new { filter, error = ex.Message });
        }
    }

    private MqttClientOptions BuildOptions()
    {
        var builder = new MqttClientOptionsBuilder()
            .WithClientId(_clientId)
            .WithTcpServer(_host, _port)
            .WithKeepAlivePeriod(TimeSpan.FromSeconds(_keepAliveSeconds))
            .WithCleanSession();

        if (!string.IsNullOrWhiteSpace(_username))
        {
            builder = builder.WithCredentials(_username, _password);
        }

        return builder.Build();
    }

    private static bool TopicMatches(string filter, string topic)
    {
        var fs = filter.Split('/', StringSplitOptions.None);
        var ts = topic.Split('/', StringSplitOptions.None);

        var fi = 0;
        var ti = 0;
        while (fi < fs.Length && ti < ts.Length)
        {
            var f = fs[fi];
            if (f == "#")
            {
                return fi == fs.Length - 1;
            }
            if (f != "+" && !string.Equals(f, ts[ti], StringComparison.Ordinal))
            {
                return false;
            }
            fi++;
            ti++;
        }

        if (fi == fs.Length && ti == ts.Length)
        {
            return true;
        }

        if (fi == fs.Length - 1 && fs[fi] == "#")
        {
            return true;
        }

        return false;
    }

    private static MqttQualityOfServiceLevel ToQos(int qos)
    {
        return qos switch
        {
            2 => MqttQualityOfServiceLevel.ExactlyOnce,
            1 => MqttQualityOfServiceLevel.AtLeastOnce,
            _ => MqttQualityOfServiceLevel.AtMostOnce,
        };
    }

    private static int ReadInt(JsonObject? section, string key, int defaultValue)
    {
        if (section is null || !section.TryGetPropertyValue(key, out var node) || node is null)
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

    private static bool ReadBool(JsonObject? section, string key, bool defaultValue)
    {
        if (section is null || !section.TryGetPropertyValue(key, out var node) || node is null)
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

    private static string ReadString(JsonObject? section, string key, string defaultValue)
    {
        if (section is null || !section.TryGetPropertyValue(key, out var node) || node is null)
        {
            return defaultValue;
        }
        if (node.TryGetValue<string>(out var s) && s is not null)
        {
            return s;
        }
        return defaultValue;
    }

    private void EnsureNotDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(MqttJsonClient));
        }
    }

    private sealed record Subscription(string Filter, Action<JsonObject, string> Handler);
}
