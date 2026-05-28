"""Main application entrypoint containing UI presentation and event orchestration."""

import os
import cv2
import math
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

        # Spatial definition states
        self.is_defining_area = False
        self.roi_points = [(100, 100), (500, 100), (500, 500), (100, 500)]
        self.active_point_idx = None
        self.source_width = 640
        self.source_height = 480

        # Video File IO states
        self.video_filepath = None
        self.tk_image = None
        self.preview_frame = None

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

        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

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

        self.radio_video = ctk.CTkRadioButton(self.control_frame, text="Video File", variable=self.source_var,
                                              value="Video File", command=self._on_source_changed)
        self.radio_video.pack(pady=5, padx=20, anchor="w")

        # Dynamic File Picker Container
        self.file_container = ctk.CTkFrame(
            self.control_frame, fg_color="transparent")
        self.btn_select_file = ctk.CTkButton(
            self.file_container, text="Choose Video File", command=self._select_file)
        self.btn_select_file.pack(pady=5, fill="x")
        self.lbl_file_path = ctk.CTkLabel(
            self.file_container, text="No file selected", text_color="gray", font=("Arial", 10))
        self.lbl_file_path.pack(pady=2)

        self.progress_bar = ctk.CTkProgressBar(self.file_container)
        self.progress_bar.set(0)

        # Processing Controls
        self.btn_edit_area = ctk.CTkButton(
            self.control_frame, text="Edit Detection Area", command=self._toggle_edit_area)
        self.btn_edit_area.pack(pady=(30, 10), padx=20, fill="x")

        self.btn_start = ctk.CTkButton(self.control_frame, text="Start Processing",
                                       fg_color="green", hover_color="darkgreen", command=self._start_processing)
        self.btn_start.pack(pady=(20, 5), padx=20, fill="x")

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

    def _select_file(self):
        """Opens dialog to locate media and extracts a preview frame."""
        filepath = filedialog.askopenfilename(
            filetypes=[("Video Files", "*.mp4 *.avi *.mkv")])
        if filepath:
            self.video_filepath = filepath
            self.lbl_file_path.configure(
                text=os.path.basename(filepath), text_color="white")
            self.progress_bar.set(0)

            # Extract initial frame to allow ROI drawing before processing
            cap = cv2.VideoCapture(filepath)
            ret, frame = cap.read()
            if ret:
                self.preview_frame = frame
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
        if mode == "Video File" and not self.video_filepath:
            return

        self.is_processing = True
        self.btn_start.configure(state="disabled", fg_color="gray")
        self.btn_stop.configure(state="normal", fg_color="red")
        self.btn_edit_area.configure(state="disabled")

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
        self.btn_edit_area.configure(state="normal")
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
        """Batch processing routine for local files enforcing sequential frame preservation."""
        detector = YoloDetector(config.MODEL_PATH)
        cap = cv2.VideoCapture(self.video_filepath)

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        base_name = os.path.splitext(os.path.basename(self.video_filepath))[0]
        dir_name = os.path.dirname(self.video_filepath)
        out_path = os.path.join(dir_name, f"{base_name}_processed.mp4")

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

        frame_idx = 0
        while self.is_processing and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            detections = detector.infer(frame)
            status, color = detector.evaluate_roi(detections, self.roi_points)

            self._annotate_matrix(frame, detections, status, color)
            writer.write(frame)

            frame_idx += 1

            # Throttle UI updates to maintain batch processing speed
            if frame_idx % 5 == 0 or frame_idx == total_frames:
                progress = frame_idx / total_frames if total_frames > 0 else 0
                self.after(0, self._update_batch_progress,
                           frame.copy(), progress, status, color)

        writer.release()
        cap.release()
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
                self.frame_queue.put_nowait((raw_frame, self.roi_points))
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
        """Applies UI styling corresponding to spatial intersection rules."""
        if status == "OK":
            self.lbl_status.configure(text="OK", text_color="green")
        elif status == "NG":
            self.lbl_status.configure(text="NG", text_color="red")
        else:
            self.lbl_status.configure(text="IDLE", text_color="yellow")

    def _annotate_matrix(self, frame, detections, status, color):
        """Applies spatial visualizations directly to the BGR array in memory."""
        roi_poly = np.array(self.roi_points, np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [roi_poly], isClosed=True,
                      color=color, thickness=3)

        for det in detections:
            x1, y1, x2, y2 = map(int, det['box'])
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        if self.is_defining_area:
            for pt in self.roi_points:
                cv2.circle(frame, pt, 8, config.COLOR_WHITE, -1)
                cv2.circle(frame, pt, 8, config.COLOR_NG, 2)

    def _draw_tk_canvas(self, frame, detections, status, color):
        """Converts internal BGR format to Tkinter presentation."""
        # Annotate matrix just in case it wasn't done upstream (e.g. preview mode)
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

    def _toggle_edit_area(self):
        """Transitions application state to allow localized polygon manipulation."""
        self.is_defining_area = not self.is_defining_area
        if self.is_defining_area:
            self.btn_edit_area.configure(
                text="Lock Detection Area", fg_color="green")
        else:
            self.btn_edit_area.configure(
                text="Edit Detection Area", fg_color=["#3a7ebf", "#1f538d"])

            # Redraw preview frame immediately to drop the anchor points
            if not self.is_processing and self.source_var.get() == "Video File" and self.preview_frame is not None:
                self._draw_tk_canvas(
                    self.preview_frame.copy(), [], "IDLE", config.COLOR_IDLE)

    def _toggle_recording(self):
        """Forwards recording intent to the underlying IO processor."""
        is_recording = self.streamer.toggle_recording()
        if is_recording:
            self.btn_record.configure(text="Stop Recording", fg_color="gray")
        else:
            self.btn_record.configure(text="Record RTSP", fg_color="darkred")

    def _get_scaled_coordinates(self, event):
        """Translates Tkinter canvas coordinates into native hardware frame scale."""
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        if self.source_width == 0 or self.source_height == 0:
            return 0, 0

        scale = min(canvas_w / self.source_width,
                    canvas_h / self.source_height)
        offset_x = (canvas_w - (self.source_width * scale)) / 2.0
        offset_y = (canvas_h - (self.source_height * scale)) / 2.0

        frame_x = int((event.x - offset_x) / scale)
        frame_y = int((event.y - offset_y) / scale)

        return frame_x, frame_y

    def _on_mouse_down(self, event):
        if not self.is_defining_area:
            return

        fx, fy = self._get_scaled_coordinates(event)
        min_dist = 40
        self.active_point_idx = None

        for i, (px, py) in enumerate(self.roi_points):
            dist = math.hypot(px - fx, py - fy)
            if dist < min_dist:
                min_dist = dist
                self.active_point_idx = i

    def _on_mouse_drag(self, event):
        if not self.is_defining_area or self.active_point_idx is None:
            return

        fx, fy = self._get_scaled_coordinates(event)
        fx = max(0, min(self.source_width, fx))
        fy = max(0, min(self.source_height, fy))

        self.roi_points[self.active_point_idx] = (fx, fy)

        # Live redraw if editing while paused on a file
        if not self.is_processing and self.source_var.get() == "Video File" and self.preview_frame is not None:
            self._draw_tk_canvas(self.preview_frame.copy(),
                                 [], "IDLE", config.COLOR_IDLE)

    def _on_mouse_up(self, event):
        self.active_point_idx = None

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
