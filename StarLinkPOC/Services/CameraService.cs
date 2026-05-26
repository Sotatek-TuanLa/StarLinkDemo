using LibVLCSharp.Shared;
using StarLinkPOC.Models;
using System.Net.Sockets;

namespace StarLinkPOC.Services
{
    /// <summary>
    /// Concrete camera service using LibVLC to decode RTSP streams from IP cameras.
    /// </summary>
    public class CameraService : ICameraService, IDisposable
    {
        private Media? _currentMedia;
        private bool _disposed;

        // ──────────────────────────────────────────────────────────────
        //  Events
        // ──────────────────────────────────────────────────────────────

        public event EventHandler? StreamStarted;
        public event EventHandler? StreamStopped;
        public event EventHandler<string>? StreamError;

        /// <summary>
        /// Fires for every VLC log entry (Warning / Error level).
        /// Gives the raw VLC message so the UI can show diagnostic detail.
        /// </summary>
        public event EventHandler<string>? VlcLogReceived;

        // ──────────────────────────────────────────────────────────────
        //  ICameraService
        // ──────────────────────────────────────────────────────────────

        public LibVLC LibVLC { get; }
        public MediaPlayer MediaPlayer { get; }
        public bool IsConnected { get; private set; }

        // ──────────────────────────────────────────────────────────────
        //  Constructor
        // ──────────────────────────────────────────────────────────────

        public CameraService()
        {
            Core.Initialize();

            LibVLC = new LibVLC(enableDebugLogs: true);

            // Capture VLC log messages so we can surface real error details
            LibVLC.Log += OnVlcLog;

            MediaPlayer = new MediaPlayer(LibVLC);

            MediaPlayer.Playing        += OnPlaying;
            MediaPlayer.Stopped        += OnStopped;
            MediaPlayer.EndReached     += OnStopped;
            MediaPlayer.EncounteredError += OnError;
        }

        // ──────────────────────────────────────────────────────────────
        //  Public API
        // ──────────────────────────────────────────────────────────────

        public async Task ConnectAsync(CameraConfig config)
        {
            if (string.IsNullOrWhiteSpace(config.Host))
                throw new InvalidOperationException("Camera Host / IP must not be empty.");
            if (string.IsNullOrWhiteSpace(config.Password))
                throw new InvalidOperationException("Password must not be empty.");

            // ── Step 1: TCP reachability check — soft warning only ────
            // We log whether port 554 is open but we do NOT abort; VLC will
            // attempt regardless and surface a richer error if it fails.
            bool tcpOk = await TryTcpConnectAsync(config.Host, config.Port);
            if (!tcpOk)
            {
                // Fire as a log warning — NOT as a StreamError (don't stop yet)
                VlcLogReceived?.Invoke(this,
                    $"[WARN] TCP port {config.Port} on {config.Host} did not respond in 5 s. " +
                    "Camera may use UDP or a firewall is filtering the port. Trying VLC anyway…");
            }
            else
            {
                VlcLogReceived?.Invoke(this,
                    $"[INFO] TCP port {config.Port} reachable on {config.Host}.");
            }

            // ── Step 2: Stop any running stream ──────────────────────
            if (MediaPlayer.IsPlaying)
                MediaPlayer.Stop();

            _currentMedia?.Dispose();
            _currentMedia = null;

            // ── Step 3: Build URL & start VLC ────────────────────────
            var rtspUrl = config.BuildRtspUrl();

            _currentMedia = await Task.Run(() =>
            {
                // IMPORTANT: use string + FromType.FromLocation, NOT new Uri()
                // Uri() sanitises/re-encodes query strings, breaking Dahua paths
                var media = new Media(LibVLC, rtspUrl, FromType.FromLocation);

                media.AddOption(":network-caching=500");
                media.AddOption(":rtsp-tcp");
                media.AddOption(":rtsp-timeout=10");
                media.AddOption(":clock-jitter=0");
                media.AddOption(":clock-synchro=0");
                // Disable GPU hw decode — fixes black frames on many drivers
                media.AddOption(":avcodec-hw=none");

                return media;
            });

            MediaPlayer.Play(_currentMedia);
        }

        public void Disconnect()
        {
            if (MediaPlayer.IsPlaying)
                MediaPlayer.Stop();

            _currentMedia?.Dispose();
            _currentMedia = null;
            IsConnected = false;
        }

        // ──────────────────────────────────────────────────────────────
        //  Helpers
        // ──────────────────────────────────────────────────────────────

        /// <summary>
        /// Tries to open a TCP socket to host:port within 3 seconds.
        /// Gives early feedback before VLC's own (silent) timeout fires.
        /// </summary>
        private static async Task<bool> TryTcpConnectAsync(string host, int port)
        {
            try
            {
                using var client = new TcpClient();
                var cts = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                await client.ConnectAsync(host, port, cts.Token);
                return true;
            }
            catch
            {
                return false;
            }
        }

        // ──────────────────────────────────────────────────────────────
        //  VLC Event Handlers
        // ──────────────────────────────────────────────────────────────

        private void OnVlcLog(object? sender, LogEventArgs e)
        {
            // Forward Warning + Error to UI; ignore Debug/Info noise
            if (e.Level >= LogLevel.Warning)
                VlcLogReceived?.Invoke(this, $"[VLC {e.Level}] {e.Message}");
        }

        private void OnPlaying(object? sender, EventArgs e)
        {
            IsConnected = true;
            StreamStarted?.Invoke(this, EventArgs.Empty);
        }

        private void OnStopped(object? sender, EventArgs e)
        {
            IsConnected = false;
            StreamStopped?.Invoke(this, EventArgs.Empty);
        }

        private void OnError(object? sender, EventArgs e)
        {
            IsConnected = false;
            StreamError?.Invoke(this,
                "VLC stream error — see the Diagnostics panel below for details.");
        }

        // ──────────────────────────────────────────────────────────────
        //  IDisposable
        // ──────────────────────────────────────────────────────────────

        protected virtual void Dispose(bool disposing)
        {
            if (_disposed) return;
            if (disposing)
            {
                LibVLC.Log -= OnVlcLog;
                MediaPlayer.Playing         -= OnPlaying;
                MediaPlayer.Stopped         -= OnStopped;
                MediaPlayer.EndReached      -= OnStopped;
                MediaPlayer.EncounteredError -= OnError;

                Disconnect();
                MediaPlayer.Dispose();
                LibVLC.Dispose();
            }
            _disposed = true;
        }

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }
    }
}
