using System.Text.Json.Nodes;

namespace SbcControllerCore.Driver;

public interface ISbcHardwareDriver : IAsyncDisposable
{
    Task OpenAsync(CancellationToken cancellationToken);
    Task<SbcRawPacket> ReadRawAsync(CancellationToken cancellationToken);
    Task ApplyLedFrameAsync(JsonObject frame, CancellationToken cancellationToken);
}
