using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.Input;
using StarLinkPOC.Models;
using StarLinkPOC.Services;

namespace StarLinkPOC.ViewModels
{
    public class MainViewModel : ViewModelBase
    {
        private readonly ICameraService _cameraService;

        // ──────────────────────────────────────────────────────────────
        //  Stream Path Presets
        // ──────────────────────────────────────────────────────────────

        public ObservableCollection<StreamPreset> StreamPresets { get; } = new()
        {
            new("Dahua — Main stream",  "/cam/realmonitor?channel=1&subtype=0"),
            new("Dahua — Sub stream",   "/cam/realmonitor?channel=1&subtype=1"),
            new("Dahua — Alt format",   "/h264/ch01/main/av_stream"),
            new("Hikvision — Main",     "/Streaming/Channels/101"),
            new("Hikvision — Sub",      "/Streaming/Channels/102"),
            new("Generic /stream",      "/stream"),
            new("Generic /live",        "/live"),
        };

        private StreamPreset? _selectedPreset;
        public StreamPreset? SelectedPreset
        {
            get => _selectedPreset;
            set
            {
                if (SetProperty(ref _selectedPreset, value) && value is not null)
                    StreamPath = value.Path;
            }
        }

        // ──────────────────────────────────────────────────────────────
        //  Form Fields
        // ──────────────────────────────────────────────────────────────

        private string _cameraHost = string.Empty;
        public string CameraHost
        {
            get => _cameraHost;
            set => SetProperty(ref _cameraHost, value);
        }

        private string _username = "admin";
        public string Username
        {
            get => _username;
            set => SetProperty(ref _username, value);
        }

        private string _password = string.Empty;
        public string Password
        {
            get => _password;
            set => SetProperty(ref _password, value);
        }

        private int _port = 554;
        public int Port
        {
            get => _port;
            set => SetProperty(ref _port, value);
        }

        private string _streamPath = "/cam/realmonitor?channel=1&subtype=0";
        public string StreamPath
        {
            get => _streamPath;
            set => SetProperty(ref _streamPath, value);
        }

        // ──────────────────────────────────────────────────────────────
        //  UI State
        // ──────────────────────────────────────────────────────────────

        private bool _isConnected;
        public bool IsConnected
        {
            get => _isConnected;
            private set
            {
                if (SetProperty(ref _isConnected, value))
                    OnPropertyChanged(nameof(IsDisconnected));
            }
        }
        public bool IsDisconnected => !_isConnected;

        private bool _isConnecting;
        public bool IsConnecting
        {
            get => _isConnecting;
            private set => SetProperty(ref _isConnecting, value);
        }

        private string _statusMessage = "Not connected";
        public string StatusMessage
        {
            get => _statusMessage;
            private set => SetProperty(ref _statusMessage, value);
        }

        private Brush _statusColor = Brushes.Gray;
        public Brush StatusColor
        {
            get => _statusColor;
            private set => SetProperty(ref _statusColor, value);
        }

        private string _resolvedUrl = string.Empty;
        public string ResolvedUrl
        {
            get => _resolvedUrl;
            private set => SetProperty(ref _resolvedUrl, value);
        }

        // ──────────────────────────────────────────────────────────────
        //  Diagnostics Log
        // ──────────────────────────────────────────────────────────────

        private string _diagnosticsLog = string.Empty;
        public string DiagnosticsLog
        {
            get => _diagnosticsLog;
            private set => SetProperty(ref _diagnosticsLog, value);
        }

        public bool HasDiagnostics => !string.IsNullOrEmpty(_diagnosticsLog);

        public IRelayCommand ClearDiagnosticsCommand { get; }

        // ──────────────────────────────────────────────────────────────
        //  Commands
        // ──────────────────────────────────────────────────────────────

        public IAsyncRelayCommand ConnectCommand { get; }
        public IRelayCommand DisconnectCommand { get; }

        // ──────────────────────────────────────────────────────────────
        //  Constructor
        // ──────────────────────────────────────────────────────────────

        public MainViewModel(ICameraService cameraService)
        {
            _cameraService = cameraService;

            _cameraService.StreamStarted  += OnStreamStarted;
            _cameraService.StreamStopped  += OnStreamStopped;
            _cameraService.StreamError    += OnStreamError;
            _cameraService.VlcLogReceived += OnVlcLog;

            ConnectCommand = new AsyncRelayCommand(
                ExecuteConnectAsync,
                () => !IsConnecting && !IsConnected);

            DisconnectCommand = new RelayCommand(
                ExecuteDisconnect,
                () => IsConnected || IsConnecting);

            ClearDiagnosticsCommand = new RelayCommand(() =>
            {
                DiagnosticsLog = string.Empty;
                OnPropertyChanged(nameof(HasDiagnostics));
            });

            // Pre-select the first preset (Dahua main)
            SelectedPreset = StreamPresets[0];
        }

        // ──────────────────────────────────────────────────────────────
        //  Connect / Disconnect
        // ──────────────────────────────────────────────────────────────

        private async Task ExecuteConnectAsync()
        {
            DiagnosticsLog = string.Empty;
            OnPropertyChanged(nameof(HasDiagnostics));

            IsConnecting = true;
            SetStatus("Checking network…", Brushes.Yellow);
            NotifyCommands();

            try
            {
                var config = new CameraConfig
                {
                    Host       = CameraHost.Trim(),
                    Username   = Username.Trim(),
                    Password   = Password,
                    Port       = Port,
                    StreamPath = StreamPath.Trim()
                };

                ResolvedUrl = config.BuildRtspUrl().Replace(config.Password, "****");
                AppendLog($"Connecting to: {ResolvedUrl}");

                SetStatus("Connecting…", Brushes.Yellow);
                await _cameraService.ConnectAsync(config);
            }
            catch (Exception ex)
            {
                IsConnecting = false;
                IsConnected  = false;
                SetStatus($"⚠ {ex.Message}", Brushes.OrangeRed);
                AppendLog($"ERROR: {ex.Message}");
                OnPropertyChanged(nameof(HasDiagnostics));
                NotifyCommands();
            }
        }

        private void ExecuteDisconnect()
        {
            _cameraService.Disconnect();
            IsConnected  = false;
            IsConnecting = false;
            ResolvedUrl  = string.Empty;
            SetStatus("Disconnected", Brushes.Gray);
            NotifyCommands();
        }

        // ──────────────────────────────────────────────────────────────
        //  VLC / Stream Events (dispatched to UI thread)
        // ──────────────────────────────────────────────────────────────

        private void OnStreamStarted(object? sender, EventArgs e) => Dispatch(() =>
        {
            IsConnecting = false;
            IsConnected  = true;
            SetStatus($"● Live  —  {CameraHost}", Brushes.LimeGreen);
            AppendLog("Stream playing successfully.");
            OnPropertyChanged(nameof(HasDiagnostics));
            NotifyCommands();
        });

        private void OnStreamStopped(object? sender, EventArgs e) => Dispatch(() =>
        {
            if (!IsConnected) return;
            IsConnected  = false;
            IsConnecting = false;
            SetStatus("Stream ended", Brushes.Gray);
            AppendLog("Stream stopped.");
            OnPropertyChanged(nameof(HasDiagnostics));
            NotifyCommands();
        });

        private void OnStreamError(object? sender, string message) => Dispatch(() =>
        {
            IsConnecting = false;
            IsConnected  = false;
            SetStatus("⚠ Stream error — see Diagnostics below", Brushes.OrangeRed);
            AppendLog(message);
            AppendLog(string.Empty);
            AppendLog("Troubleshooting tips:");
            AppendLog("  1. Verify IP address in your browser: http://" + CameraHost);
            AppendLog("  2. Try different stream paths in the preset dropdown");
            AppendLog("  3. Confirm username/password are correct");
            AppendLog("  4. Some Dahua cams need HTTP auth at port 80 first");
            OnPropertyChanged(nameof(HasDiagnostics));
            NotifyCommands();
        });

        private void OnVlcLog(object? sender, string logLine) => Dispatch(() =>
        {
            AppendLog(logLine);
            OnPropertyChanged(nameof(HasDiagnostics));
        });

        // ──────────────────────────────────────────────────────────────
        //  Helpers
        // ──────────────────────────────────────────────────────────────

        private void AppendLog(string line)
        {
            var prefix = string.IsNullOrEmpty(line) ? string.Empty
                         : $"[{DateTime.Now:HH:mm:ss}] ";
            DiagnosticsLog = string.IsNullOrEmpty(DiagnosticsLog)
                ? $"{prefix}{line}"
                : $"{DiagnosticsLog}\n{prefix}{line}";
        }

        private static void Dispatch(Action action)
        {
            if (Application.Current?.Dispatcher is Dispatcher d)
                d.BeginInvoke(action);
            else
                action();
        }

        private void SetStatus(string message, Brush color)
        {
            StatusMessage = message;
            StatusColor   = color;
        }

        private void NotifyCommands()
        {
            ConnectCommand.NotifyCanExecuteChanged();
            DisconnectCommand.NotifyCanExecuteChanged();
        }
    }

    /// <summary>A named stream path preset shown in the ComboBox.</summary>
    public record StreamPreset(string Label, string Path);
}
