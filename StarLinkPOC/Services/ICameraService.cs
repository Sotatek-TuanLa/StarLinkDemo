using LibVLCSharp.Shared;
using StarLinkPOC.Models;

namespace StarLinkPOC.Services
{
    public interface ICameraService
    {
        LibVLC LibVLC { get; }
        MediaPlayer MediaPlayer { get; }
        bool IsConnected { get; }

        event EventHandler? StreamStarted;
        event EventHandler? StreamStopped;
        event EventHandler<string>? StreamError;

        /// <summary>Raw VLC log lines (Warning/Error level) for diagnostics.</summary>
        event EventHandler<string>? VlcLogReceived;

        bool IsRecording { get; }

        Task ConnectAsync(CameraConfig config);
        void Disconnect();

        Task StartRecordingAsync(CameraConfig config, string recordFilePath);
        void StopRecording();
    }
}
