namespace SbcControllerCore.Driver;

public sealed class SbcStateParser
{
    private readonly AnalogProcessor _analogProcessor;

    public SbcStateParser(AnalogProcessor analogProcessor)
    {
        _analogProcessor = analogProcessor;
    }

    public SbcState Parse(SbcRawPacket packet)
    {
        var state = packet.State.Clone();
        return _analogProcessor.Process(state);
    }
}
