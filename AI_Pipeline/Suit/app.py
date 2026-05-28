"""Main application entrypoint containing UI presentation and event orchestration."""

import os
import cv2
import queue
import threading
import numpy as np
import multiprocessing as mp
import customtkinter as ctk
from tkinter import filedialog
from PIL import Image, ImageTk

import config
from detector import detection_worker, YoloDetector
from streamer import VideoStreamer

ctk.set_appearance_mode(config.THEME_MODE)
ctk.set_default_color_theme(config.THEME_COLOR)


class ModernDetectionUI(ctk.CTk):
    """Graphical interface tying together inference pipelines and video buffering."""

    def __init__(self):
        """Constructs inter-process queues and state mechanisms."""
        super().__init__()

        self.title(config.WINDOW_TITLE)
        self.geometry(config.WINDOW_GEOMETRY)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Pipeline states
        self.streamer = VideoStreamer()
        self.frame_queue = mp.Queue(maxsize=config.MAX_QUEUE_SIZE)
        self.result_queue = mp.Queue(maxsize=config.MAX_QUEUE_SIZE)
        self.detection_process = None
        self.is_processing = False

        self.source_width = 640
        self.source_height = 480

        # Video File IO states
        self.video_filepaths = []
        self.tk_image = None

        self._build_ui()
        self._on_source_changed()

    def _build_ui(self):
        """Inflates the dynamic UI elements."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Video Canvas Layer
        self.video_frame = ctk.CTkFrame(self)
        self.video_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.canvas = ctk.CTkCanvas(
            self.video_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Interaction Panel
        self.control_frame = ctk.CTkFrame(self, width=320)
        self.control_frame.grid(row=0, column=1, padx=10, pady=10, sticky="ns")
        self.control_frame.grid_propagate(False)

        # Input Mode Selection
        ctk.CTkLabel(self.control_frame, text="Input Source",
                     font=("Arial", 16, "bold")).pack(pady=(20, 10))
        self.source_var = ctk.StringVar(value="Camera (RTSP)")

        ctk.CTkRadioButton(self.control_frame, text="Camera (RTSP)", variable=self.source_var,
                           value="Camera (RTSP)", command=self._on_source_changed).pack(pady=5, padx=20, anchor="w")

        self.radio_video = ctk.CTkRadioButton(self.control_frame, text="Video Files", variable=self.source_var,
                                              value="Video Files", command=self._on_source_changed)
        self.radio_video.pack(pady=5, padx=20, anchor="w")

        # Dynamic File Picker Container
        self.file_container = ctk.CTkFrame(
            self.control_frame, fg_color="transparent")
        self.btn_select_file = ctk.CTkButton(
            self.file_container, text="Choose Video Files", command=self._select_files)
        self.btn_select_file.pack(pady=5, fill="x")
        self.lbl_file_path = ctk.CTkLabel(
            self.file_container, text="No files selected", text_color="gray", font=("Arial", 10))
        self.lbl_file_path.pack(pady=2)

        self.progress_bar = ctk.CTkProgressBar(self.file_container)
        self.progress_bar.set(0)

        # Processing Controls
        self.btn_start = ctk.CTkButton(self.control_frame, text="Start Processing",
                                       fg_color="green", hover_color="darkgreen", command=self._start_processing)
        self.btn_start.pack(pady=(30, 5), padx=20, fill="x")

        self.btn_stop = ctk.CTkButton(
            self.control_frame, text="Stop", fg_color="gray", state="disabled", command=self._stop_processing)
        self.btn_stop.pack(pady=5, padx=20, fill="x")

        # Status and Recording
        ctk.CTkLabel(self.control_frame, text="Status", font=(
            "Arial", 16, "bold")).pack(pady=(20, 5))
        self.lbl_status = ctk.CTkLabel(self.control_frame, text="WAITING", font=(
            "Arial", 24, "bold"), text_color="yellow")
        self.lbl_status.pack(pady=5)

        self.btn_record = ctk.CTkButton(self.control_frame, text="Record RTSP",
                                        fg_color="darkred", hover_color="red", command=self._toggle_recording)

    def _on_source_changed(self):
        """Updates control panel layout based on input modality."""
        self._stop_processing()

        if self.source_var.get() == "Camera (RTSP)":
            self.file_container.pack_forget()
            self.progress_bar.pack_forget()
            self.btn_record.pack(side="bottom", pady=30, padx=20, fill="x")
            self._connect_rtsp()
        else:
            self.btn_record.pack_forget()
            self.file_container.pack(
                pady=10, padx=20, fill="x", after=self.radio_video)

    def _connect_rtsp(self):
        """Initializes hardware capture and updates scaling boundaries."""
        self.streamer.connect(config.DEFAULT_RTSP)
        self.source_width = self.streamer.width
        self.source_height = self.streamer.height
        if not self.streamer.running:
            self.streamer.start()

    def _select_files(self):
        """Opens dialog to locate media and updates UI file count."""
        filepaths = filedialog.askopenfilenames(
            filetypes=[("Video Files", "*.mp4 *.avi *.mkv")])

        if filepaths:
            self.video_filepaths = list(filepaths)
            self.lbl_file_path.configure(
                text=f"{len(self.video_filepaths)} file(s) selected", text_color="white")
            self.progress_bar.set(0)

            # Display preview of the first frame of the first video
            cap = cv2.VideoCapture(self.video_filepaths[0])
            ret, frame = cap.read()
            if ret:
                self.source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self._draw_tk_canvas(
                    frame.copy(), [], "IDLE", config.COLOR_IDLE)
            cap.release()

    def _start_processing(self):
        """Routes execution architecture based on selected media type."""
        if self.is_processing:
            return

        mode = self.source_var.get()
        if mode == "Video Files" and not self.video_filepaths:
            return

        self.is_processing = True
        self.btn_start.configure(state="disabled", fg_color="gray")
        self.btn_stop.configure(state="normal", fg_color="red")

        if mode == "Camera (RTSP)":
            self.streamer.play()
            self.detection_process = mp.Process(
                target=detection_worker,
                args=(self.frame_queue, self.result_queue, config.MODEL_PATH),
                daemon=True
            )
            self.detection_process.start()
            self._rtsp_loop()
        else:
            self.progress_bar.pack(pady=10, fill="x")
            threading.Thread(target=self._process_video_thread,
                             daemon=True).start()

    def _stop_processing(self):
        """Halts active background processes and file handlers."""
        self.is_processing = False
        self.btn_start.configure(state="normal", fg_color="green")
        self.btn_stop.configure(state="disabled", fg_color="gray")
        self.lbl_status.configure(text="WAITING", text_color="yellow")

        if self.source_var.get() == "Camera (RTSP)":
            self.streamer.pause()

            try:
                self.frame_queue.put_nowait(None)
            except queue.Full:
                self.frame_queue.get()
                self.frame_queue.put(None)

            if self.detection_process:
                self.detection_process.join(timeout=2)
                if self.detection_process.is_alive():
                    self.detection_process.terminate()

            while not self.result_queue.empty():
                try:
                    self.result_queue.get_nowait()
                except queue.Empty:
                    break

    def _process_video_thread(self):
        """Batch processing routine for local files combining them into a single output."""
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(
            config.OUTPUT_DIR, "combined_processed_output.mp4")

        # Pre-calculate total frames for accurate progress bar
        total_frames = 0
        for filepath in self.video_filepaths:
            cap = cv2.VideoCapture(filepath)
            total_frames += int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()

        # Initialize VideoWriter using parameters from the first video
        first_cap = cv2.VideoCapture(self.video_filepaths[0])
        width = int(first_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(first_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = first_cap.get(cv2.CAP_PROP_FPS) or 30.0
        first_cap.release()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

        detector = YoloDetector(config.MODEL_PATH)
        current_frame_idx = 0

        for filepath in self.video_filepaths:
            if not self.is_processing:
                break

            cap = cv2.VideoCapture(filepath)
            while self.is_processing and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                detections = detector.infer(frame)
                status, color = detector.evaluate_detections(detections)

                # Append annotations and text overlay to the frame
                self._annotate_matrix(frame, detections, status, color)
                writer.write(frame)

                current_frame_idx += 1

                # Throttle UI updates to maintain batch processing speed
                if current_frame_idx % 5 == 0 or current_frame_idx == total_frames:
                    progress = current_frame_idx / total_frames if total_frames > 0 else 0
                    self.after(0, self._update_batch_progress,
                               frame.copy(), progress, status, color)

            cap.release()

        writer.release()
        self.after(0, self._stop_processing)

    def _update_batch_progress(self, frame, progress, status, color):
        """Cross-thread bridge to safely update Tkinter widgets during batch processing."""
        self.progress_bar.set(progress)
        self._update_status_label(status)
        self._draw_tk_canvas(frame, [], status, color)

    def _rtsp_loop(self):
        """Synchronizes RTSP capture and sub-process inference output."""
        if not self.is_processing:
            return

        raw_frame = self.streamer.read()
        if raw_frame is not None:
            try:
                self.frame_queue.put_nowait(raw_frame)
            except queue.Full:
                pass

        try:
            sync_frame, detections, status, color = self.result_queue.get_nowait()
            self._annotate_matrix(sync_frame, detections, status, color)
            self.streamer.write_frame(sync_frame)
            self._update_status_label(status)
            self._draw_tk_canvas(sync_frame, detections, status, color)
        except queue.Empty:
            pass

        self.after(15, self._rtsp_loop)

    def _update_status_label(self, status):
        """Applies UI styling corresponding to detection status."""
        if status == "OK":
            self.lbl_status.configure(text="OK", text_color="green")
        elif status == "NG":
            self.lbl_status.configure(text="NG", text_color="red")
        else:
            self.lbl_status.configure(text="IDLE", text_color="yellow")

    def _annotate_matrix(self, frame, detections, status, color):
        """Applies spatial visualizations directly to the BGR array in memory."""
        # Draw target bounding boxes
        for det in detections:
            x1, y1, x2, y2 = det
            cv2.rectangle(frame, (x1, y1), (x2, y2), config.COLOR_NG, 2)

        # Draw Global Status Text Overlay
        text = f"STATUS: {status}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 3

        text_size, _ = cv2.getTextSize(text, font, font_scale, thickness)
        text_w, text_h = text_size

        # Calculate top-right coordinates
        margin_x = 20
        margin_y = 30
        frame_h, frame_w = frame.shape[:2]

        origin_x = frame_w - text_w - margin_x
        origin_y = margin_y + text_h

        # Draw solid black background for contrast
        cv2.rectangle(frame,
                      (origin_x - 10, origin_y - text_h - 10),
                      (origin_x + text_w + 10, origin_y + 10),
                      (0, 0, 0), -1)

        cv2.putText(frame, text, (origin_x, origin_y), font,
                    font_scale, color, thickness, cv2.LINE_AA)

    def _draw_tk_canvas(self, frame, detections, status, color):
        """Converts internal BGR format to Tkinter presentation."""
        self._annotate_matrix(frame, detections, status, color)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        if canvas_w > 10 and canvas_h > 10:
            image.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)

        self.tk_image = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_w // 2, canvas_h // 2, anchor="center", image=self.tk_image)

    def _toggle_recording(self):
        """Forwards recording intent to the underlying IO processor."""
        is_recording = self.streamer.toggle_recording()
        if is_recording:
            self.btn_record.configure(text="Stop Recording", fg_color="gray")
        else:
            self.btn_record.configure(text="Record RTSP", fg_color="darkred")

    def _on_closing(self):
        """Garbage collection triggers for application closure."""
        self._stop_processing()
        self.streamer.stop()
        self.destroy()


if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    mp.freeze_support()

    app = ModernDetectionUI()
    app.mainloop()
