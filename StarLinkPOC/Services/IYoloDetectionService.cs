using StarLinkPOC.Models;

namespace StarLinkPOC.Services
{
    public interface IYoloDetectionService : IDisposable
    {
        bool IsRunning { get; }
        string? ModelPath { get; set; }

        event EventHandler<List<Detection>>? DetectionsUpdated;
        event EventHandler<string>? StatusMessage;

        /// <summary>Start grabbing frames from the RTSP stream and running inference.</summary>
        Task StartAsync(string rtspUrl);

        /// <summary>Stop inference and release the frame capture player.</summary>
        void Stop();
    }
}
