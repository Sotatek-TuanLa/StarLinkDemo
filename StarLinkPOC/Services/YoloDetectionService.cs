using System.Runtime.InteropServices;
using System.Windows;
using LibVLCSharp.Shared;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using StarLinkPOC.Models;

namespace StarLinkPOC.Services
{
    /// <summary>
    /// Runs YOLOv8 ONNX inference on frames captured from a headless LibVLC player.
    /// The main VideoView player is untouched — this uses its own secondary player
    /// so the live display is never interrupted.
    /// </summary>
    public sealed class YoloDetectionService : IYoloDetectionService
    {
        // ── ONNX ──────────────────────────────────────────────────────
        private InferenceSession? _session;

        /// <summary>YOLOv8 standard input size (can be overridden by model metadata).</summary>
        private int _modelInputW = 640;
        private int _modelInputH = 640;

        /// <summary>Class names from model metadata, falls back to numeric ids.</summary>
        private readonly Dictionary<int, string> _classNames = new();

        // ── LibVLC secondary (headless) player ────────────────────────
        private readonly LibVLC _libVlc;
        private MediaPlayer?   _player;
        private Media?         _media;

        /// <summary>
        /// Raw RGBA frame buffer that LibVLC writes decoded pixels into.
        /// GCHandle pins it so the native callback can safely hold the pointer.
        /// </summary>
        private byte[]?  _frameBuffer;
        private GCHandle _frameBufferHandle;
        private int _captureW;
        private int _captureH;

        // ── Inference throttling ──────────────────────────────────────
        /// <summary>Only run inference on every N-th displayed frame (~6 fps at 30 fps stream).</summary>
        private const int InferenceEveryNFrames = 5;
        private long _displayCallCount;
        /// <summary>Gate so we never queue more than one inference at a time.</summary>
        private int _inferenceRunning; // interlocked flag (0 = free, 1 = busy)

        // ── Interface ────────────────────────────────────────────────
        public bool    IsRunning  { get; private set; }
        public string? ModelPath  { get; set; }

        public event EventHandler<List<Detection>>? DetectionsUpdated;
        public event EventHandler<string>?          StatusMessage;

        // ── Constructor ───────────────────────────────────────────────
        public YoloDetectionService(LibVLC libVlc)
        {
            _libVlc = libVlc;
        }

        // ── Public API ────────────────────────────────────────────────

        public async Task StartAsync(string rtspUrl)
        {
            if (IsRunning) Stop();
            if (string.IsNullOrWhiteSpace(ModelPath) || !System.IO.File.Exists(ModelPath))
                throw new InvalidOperationException("Please select a valid ONNX model file first.");

            // Load the ONNX session on a thread pool thread to avoid UI freeze
            _session = await Task.Run(() => LoadSession(ModelPath));
            FireStatus($"Model loaded: {System.IO.Path.GetFileName(ModelPath)}  " +
                       $"({_modelInputW}×{_modelInputH}, {_classNames.Count} classes)");

            // Set up the capture dimensions (downsample to reduce bandwidth)
            _captureW = 640;
            _captureH = 480;

            // Allocate pinned frame buffer: RGBA = 4 bytes per pixel
            _frameBuffer = new byte[_captureW * _captureH * 4];
            _frameBufferHandle = GCHandle.Alloc(_frameBuffer, GCHandleType.Pinned);

            // Create headless player with video callbacks
            _player = new MediaPlayer(_libVlc);
            _player.SetVideoFormat("RGBA", (uint)_captureW, (uint)_captureH, (uint)(_captureW * 4));
            _player.SetVideoCallbacks(LockCallback, null, DisplayCallback);

            _media = new Media(_libVlc, rtspUrl, FromType.FromLocation);
            _media.AddOption(":network-caching=500");
            _media.AddOption(":rtsp-tcp");
            _media.AddOption(":rtsp-timeout=10");
            _media.AddOption(":avcodec-hw=none");
            // Disable all audio — we only need pixels
            _media.AddOption(":no-audio");

            _displayCallCount = 0;
            _inferenceRunning = 0;
            IsRunning = true;

            _player.Play(_media);
            FireStatus("AI detection started.");
        }

        public void Stop()
        {
            IsRunning = false;

            if (_player != null)
            {
                if (_player.IsPlaying) _player.Stop();
                _player.Dispose();
                _player = null;
            }

            _media?.Dispose();
            _media = null;

            if (_frameBufferHandle.IsAllocated)
                _frameBufferHandle.Free();

            _frameBuffer = null;

            _session?.Dispose();
            _session = null;
            _classNames.Clear();

            FireStatus("AI detection stopped.");
        }

        // ── LibVLC Callbacks ──────────────────────────────────────────

        /// <summary>LibVLC calls this to get the buffer address it should write pixels into.</summary>
        private IntPtr LockCallback(IntPtr opaque, IntPtr planes)
        {
            if (_frameBuffer == null) return IntPtr.Zero;
            var ptr = _frameBufferHandle.AddrOfPinnedObject();
            // Write the pointer value into the planes array (LibVLC expects double-pointer)
            Marshal.WriteIntPtr(planes, ptr);
            return ptr;
        }

        /// <summary>LibVLC calls this when a frame is ready to display.</summary>
        private void DisplayCallback(IntPtr opaque, IntPtr picture)
        {
            if (!IsRunning || _frameBuffer == null || _session == null) return;

            // Throttle: only infer every N frames
            var count = Interlocked.Increment(ref _displayCallCount);
            if (count % InferenceEveryNFrames != 0) return;

            // Non-blocking: skip if a previous inference is still running
            if (Interlocked.CompareExchange(ref _inferenceRunning, 1, 0) != 0) return;

            // Copy the frame buffer snapshot (LibVLC may overwrite it immediately)
            var snapshot = new byte[_frameBuffer.Length];
            Array.Copy(_frameBuffer, snapshot, snapshot.Length);
            var w = _captureW;
            var h = _captureH;

            // Run inference asynchronously
            Task.Run(() =>
            {
                try
                {
                    var detections = RunInference(snapshot, w, h);
                    DetectionsUpdated?.Invoke(this, detections);
                }
                catch (Exception ex)
                {
                    FireStatus($"[YOLO Error] {ex.Message}");
                }
                finally
                {
                    Interlocked.Exchange(ref _inferenceRunning, 0);
                }
            });
        }

        // ── ONNX Inference ────────────────────────────────────────────

        private InferenceSession LoadSession(string modelPath)
        {
            var options = new SessionOptions();
            // Attempt GPU (CUDA) first, fall back to CPU silently
            try
            {
                options.AppendExecutionProvider_CUDA(0);
                FireStatus("Using GPU (CUDA) for inference.");
            }
            catch
            {
                FireStatus("GPU unavailable, using CPU for inference.");
            }

            var session = new InferenceSession(modelPath, options);

            // Read model input dimensions from metadata
            var inputMeta = session.InputMetadata;
            if (inputMeta.Count > 0)
            {
                var dims = inputMeta.Values.First().Dimensions;
                if (dims.Length >= 4 && dims[2] > 0 && dims[3] > 0)
                {
                    _modelInputH = dims[2];
                    _modelInputW = dims[3];
                }
            }

            // Parse class names from model custom metadata (Ultralytics stores them as JSON dict)
            try
            {
                var meta = session.ModelMetadata.CustomMetadataMap;
                if (meta.TryGetValue("names", out var namesJson))
                {
                    // Format is like: {0: 'person', 1: 'bicycle', ...}
                    // Simple regex-free parse
                    ParseClassNames(namesJson);
                }
            }
            catch { /* ignore */ }

            return session;
        }

        private void ParseClassNames(string namesJson)
        {
            // Strip braces
            namesJson = namesJson.Trim('{', '}', ' ');
            foreach (var entry in namesJson.Split(','))
            {
                var parts = entry.Split(':');
                if (parts.Length < 2) continue;
                var idStr   = parts[0].Trim().Trim('\'', '"', ' ');
                var nameStr = parts[1].Trim().Trim('\'', '"', ' ');
                if (int.TryParse(idStr, out var id))
                    _classNames[id] = nameStr;
            }
        }

        private List<Detection> RunInference(byte[] rgbaFrame, int frameW, int frameH)
        {
            if (_session == null) return [];

            // ── Step 1: Pre-process ──────────────────────────────────
            // Resize from (frameW×frameH) to model input (_modelInputW×_modelInputH)
            // Convert RGBA → normalised RGB float32 tensor [1, 3, H, W]
            var tensor = Preprocess(rgbaFrame, frameW, frameH, _modelInputW, _modelInputH);

            var inputName = _session.InputMetadata.Keys.First();
            var inputs    = new List<NamedOnnxValue>
            {
                NamedOnnxValue.CreateFromTensor(inputName, tensor)
            };

            // ── Step 2: Inference ─────────────────────────────────────
            using var results   = _session.Run(inputs);
            var       outputRaw = results.First().AsEnumerable<float>().ToArray();
            // YOLOv8 output shape: [1, 84, 8400]  (84 = 4 box + 80 classes)
            var outputShape = results.First().AsTensor<float>().Dimensions.ToArray();

            // ── Step 3: Post-process ──────────────────────────────────
            return Postprocess(outputRaw, outputShape, frameW, frameH, 0.25f, 0.45f);
        }

        private static DenseTensor<float> Preprocess(byte[] rgba, int srcW, int srcH, int dstW, int dstH)
        {
            var tensor = new DenseTensor<float>([1, 3, dstH, dstW]);

            // Bilinear resize + normalise in one pass
            float xScale = (float)srcW / dstW;
            float yScale = (float)srcH / dstH;

            for (int dy = 0; dy < dstH; dy++)
            {
                float sy = dy * yScale;
                int   y0 = (int)sy;
                int   y1 = Math.Min(y0 + 1, srcH - 1);
                float fy = sy - y0;

                for (int dx = 0; dx < dstW; dx++)
                {
                    float sx = dx * xScale;
                    int   x0 = (int)sx;
                    int   x1 = Math.Min(x0 + 1, srcW - 1);
                    float fx = sx - x0;

                    // Bilinear interpolation for R, G, B channels
                    for (int c = 0; c < 3; c++)
                    {
                        float p00 = rgba[(y0 * srcW + x0) * 4 + c];
                        float p01 = rgba[(y0 * srcW + x1) * 4 + c];
                        float p10 = rgba[(y1 * srcW + x0) * 4 + c];
                        float p11 = rgba[(y1 * srcW + x1) * 4 + c];

                        float px = p00 * (1 - fx) * (1 - fy)
                                 + p01 * fx       * (1 - fy)
                                 + p10 * (1 - fx) * fy
                                 + p11 * fx       * fy;

                        tensor[0, c, dy, dx] = px / 255f;
                    }
                }
            }
            return tensor;
        }

        private List<Detection> Postprocess(
            float[] raw, int[] shape, int frameW, int frameH,
            float confThreshold, float iouThreshold)
        {
            // shape expected: [1, numFeatures, numAnchors]
            // numFeatures = 4 (box) + numClasses
            int numFeatures = shape.Length >= 2 ? shape[1] : 84;
            int numAnchors  = shape.Length >= 3 ? shape[2] : 8400;
            int numClasses  = numFeatures - 4;

            float scaleX = (float)frameW / _modelInputW;
            float scaleY = (float)frameH / _modelInputH;

            var candidates = new List<(Rect box, float conf, int classId)>();

            for (int a = 0; a < numAnchors; a++)
            {
                // Box coords stored at feature indices 0-3 for anchor a
                float cx = raw[0 * numAnchors + a];
                float cy = raw[1 * numAnchors + a];
                float bw = raw[2 * numAnchors + a];
                float bh = raw[3 * numAnchors + a];

                // Find the best class score
                float bestConf = 0f;
                int   bestCls  = 0;
                for (int c = 0; c < numClasses; c++)
                {
                    float score = raw[(4 + c) * numAnchors + a];
                    if (score > bestConf) { bestConf = score; bestCls = c; }
                }

                if (bestConf < confThreshold) continue;

                // Scale box to original frame coordinates
                float x = (cx - bw / 2f) * scaleX;
                float y = (cy - bh / 2f) * scaleY;
                float w = bw * scaleX;
                float h = bh * scaleY;

                candidates.Add((new Rect(x, y, w, h), bestConf, bestCls));
            }

            // ── Non-Maximum Suppression (greedy) ─────────────────────
            candidates.Sort((a, b) => b.conf.CompareTo(a.conf));
            var kept = new List<Detection>();

            while (candidates.Count > 0)
            {
                var best = candidates[0];
                candidates.RemoveAt(0);
                var label = _classNames.TryGetValue(best.classId, out var n) ? n : $"Class {best.classId}";
                kept.Add(new Detection(best.classId, label, best.conf, best.box));

                candidates.RemoveAll(c => Iou(c.box, best.box) > iouThreshold);
            }

            return kept;
        }

        private static float Iou(Rect a, Rect b)
        {
            var interX = Math.Max(0, Math.Min(a.Right,  b.Right)  - Math.Max(a.Left,  b.Left));
            var interY = Math.Max(0, Math.Min(a.Bottom, b.Bottom) - Math.Max(a.Top,   b.Top));
            double inter = interX * interY;
            if (inter <= 0) return 0f;
            double union = a.Width * a.Height + b.Width * b.Height - inter;
            return (float)(inter / union);
        }

        // ── Helpers ───────────────────────────────────────────────────

        private void FireStatus(string msg) =>
            StatusMessage?.Invoke(this, msg);

        // ── IDisposable ───────────────────────────────────────────────
        private bool _disposed;
        public void Dispose()
        {
            if (_disposed) return;
            Stop();
            _disposed = true;
        }
    }
}
