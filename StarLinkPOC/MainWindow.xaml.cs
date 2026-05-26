using System.Windows;
using StarLinkPOC.Services;
using StarLinkPOC.ViewModels;

namespace StarLinkPOC
{
    /// <summary>
    /// Interaction logic for MainWindow.xaml.
    /// Code-behind is kept minimal (MVVM): handles PasswordBox bridge,
    /// VideoView MediaPlayer wiring, and window cleanup.
    /// </summary>
    public partial class MainWindow : Window
    {
        private readonly CameraService _cameraService;
        private readonly MainViewModel _viewModel;

        public MainWindow()
        {
            InitializeComponent();

            // Manual DI composition
            _cameraService = new CameraService();
            _viewModel     = new MainViewModel(_cameraService);

            DataContext = _viewModel;

            // ── IMPORTANT ──────────────────────────────────────────────
            // VideoView.MediaPlayer is NOT a real DependencyProperty in
            // LibVLCSharp.WPF — it cannot be data-bound in XAML and MUST
            // be assigned from code. We assign it here AND in VideoView_Loaded
            // because HwndHost (which VideoView uses internally) sometimes
            // re-creates its child window handle after layout is complete.
            // ──────────────────────────────────────────────────────────
            VideoView.MediaPlayer = _cameraService.MediaPlayer;
        }

        // ──────────────────────────────────────────────────────────────
        //  VideoView Loaded — Re-assign MediaPlayer after HwndHost init
        // ──────────────────────────────────────────────────────────────

        private void VideoView_Loaded(object sender, RoutedEventArgs e)
        {
            // Re-apply in case the HwndHost window was (re)created after layout
            VideoView.MediaPlayer = _cameraService.MediaPlayer;
        }

        // ──────────────────────────────────────────────────────────────
        //  PasswordBox Bridge
        //  WPF PasswordBox.Password is intentionally not a DP (security),
        //  so we push the value to the ViewModel on every keystroke.
        // ──────────────────────────────────────────────────────────────

        private void PwdPassword_PasswordChanged(object sender, RoutedEventArgs e)
        {
            _viewModel.Password = PwdPassword.Password;
        }

        // ──────────────────────────────────────────────────────────────
        //  Cleanup on close — stop stream and release LibVLC resources
        // ──────────────────────────────────────────────────────────────

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            if (_viewModel.IsConnected || _viewModel.IsConnecting)
                _viewModel.DisconnectCommand.Execute(null);

            _cameraService.Dispose();
        }
    }
}