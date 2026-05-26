using System.Windows;
using StarLinkPOC.Models;
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
        private readonly YoloDetectionService _detectionService;
        private readonly MainViewModel _viewModel;

        public MainWindow()
        {
            InitializeComponent();

            // Manual DI composition
            _cameraService = new CameraService();
            _detectionService = new YoloDetectionService(_cameraService.LibVLC);
            _viewModel     = new MainViewModel(_cameraService, _detectionService);

            DataContext = _viewModel;

            // Wire up the detection overlay
            _viewModel.DetectionsReady += OnDetectionsReady;

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
        //  Recording Folder Browser
        // ──────────────────────────────────────────────────────────────

        private void BtnBrowseFolder_Click(object sender, RoutedEventArgs e)
        {
            var dialog = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "Select Recordings Directory",
                InitialDirectory = _viewModel.RecordingDirectory
            };

            if (dialog.ShowDialog() == true)
            {
                _viewModel.RecordingDirectory = dialog.FolderName;
            }
        }

        // ──────────────────────────────────────────────────────────────
        //  YOLO ONNX Model Browser
        // ──────────────────────────────────────────────────────────────

        private void BtnBrowseModel_Click(object sender, RoutedEventArgs e)
        {
            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Title = "Select YOLO ONNX Model",
                Filter = "ONNX Model Files (*.onnx)|*.onnx|All Files (*.*)|*.*"
            };

            if (dialog.ShowDialog() == true)
            {
                _viewModel.ModelPath = dialog.FileName;
            }
        }

        // ──────────────────────────────────────────────────────────────
        //  AI Detection Overlay Drawing
        // ──────────────────────────────────────────────────────────────

        private void OnDetectionsReady(object? sender, List<Detection> detections)
        {
            // main VM dispatches this to the UI thread, so we can access Canvas directly
            DetectionCanvas.Children.Clear();

            if (!_viewModel.IsDetecting || !_viewModel.IsConnected) return;

            double canvasW = DetectionCanvas.ActualWidth;
            double canvasH = DetectionCanvas.ActualHeight;

            if (canvasW <= 0 || canvasH <= 0) return;

            // Map from the 640x480 coordinate space of the secondary detection feed to current Canvas size
            double scaleX = canvasW / 640.0;
            double scaleY = canvasH / 480.0;

            foreach (var det in detections)
            {
                double left = det.BoundingBox.Left * scaleX;
                double top = det.BoundingBox.Top * scaleY;
                double width = det.BoundingBox.Width * scaleX;
                double height = det.BoundingBox.Height * scaleY;

                // Clamp to canvas borders
                left = Math.Max(0, Math.Min(left, canvasW));
                top = Math.Max(0, Math.Min(top, canvasH));
                width = Math.Max(0, Math.Min(width, canvasW - left));
                height = Math.Max(0, Math.Min(height, canvasH - top));

                if (width <= 0 || height <= 0) continue;

                // Create the bounding box border
                var rect = new System.Windows.Shapes.Rectangle
                {
                    Width = width,
                    Height = height,
                    Stroke = System.Windows.Media.Brushes.LimeGreen,
                    StrokeThickness = 2.5,
                    Effect = new System.Windows.Media.Effects.DropShadowEffect
                    {
                        Color = System.Windows.Media.Colors.Black,
                        BlurRadius = 2,
                        ShadowDepth = 1,
                        Opacity = 0.8
                    }
                };

                System.Windows.Controls.Canvas.SetLeft(rect, left);
                System.Windows.Controls.Canvas.SetTop(rect, top);
                DetectionCanvas.Children.Add(rect);

                // Create the label text block
                var textBlock = new System.Windows.Controls.TextBlock
                {
                    Text = $"{det.Label} {det.Confidence:P0}",
                    Foreground = System.Windows.Media.Brushes.White,
                    Background = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromArgb(180, 0, 180, 0)),
                    FontSize = 10,
                    FontWeight = FontWeights.Bold,
                    Padding = new Thickness(4, 2, 4, 2),
                    Margin = new Thickness(0, -18, 0, 0)
                };

                System.Windows.Controls.Canvas.SetLeft(textBlock, left);
                System.Windows.Controls.Canvas.SetTop(textBlock, top);
                DetectionCanvas.Children.Add(textBlock);
            }
        }

        // ──────────────────────────────────────────────────────────────
        //  Cleanup on close — stop stream and release LibVLC resources
        // ──────────────────────────────────────────────────────────────

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            if (_viewModel.IsConnected || _viewModel.IsConnecting)
                _viewModel.DisconnectCommand.Execute(null);

            _detectionService.Dispose();
            _cameraService.Dispose();
        }
    }
}