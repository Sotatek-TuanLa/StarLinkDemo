"""Handles asynchronous video capture for real-time RTSP streams."""

import os
import cv2
import time
import threading
import datetime

import config


class VideoStreamer:
    """Manages thread-safe video capture and optional file recording for live streams."""

    def __init__(self):
        """Initializes threading locks and streamer state variables."""
        # Force TCP for RTSP to prevent UDP packet loss smearing
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        self.cap = None
        self.running = False
        self.latest_frame = None
        self.lock = threading.Lock()

        self.video_writer = None
        self.is_recording = False
        self.is_paused = True

        self.width = 640
        self.height = 480

    def connect(self, source):
        """Establishes connection to the video source.

        Args:
            source: String representation of the RTSP URL.

        Returns:
            A boolean indicating if the source was opened successfully.
        """
        if self.cap:
            self.cap.release()

        self.cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)

        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            ret, frame = self.cap.read()
            if ret:
                self.latest_frame = frame

            return True
        return False

    def start(self):
        """Spawns the background extraction thread."""
        self.running = True
        thread = threading.Thread(target=self._update, daemon=True)
        thread.start()

    def play(self):
        """Resumes frame extraction."""
        self.is_paused = False

    def pause(self):
        """Suspends frame extraction."""
        self.is_paused = True

    def _update(self):
        """Background thread loop retrieving frames from the hardware buffer."""
        while self.running:
            if self.is_paused:
                time.sleep(0.05)
                continue

            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    with self.lock:
                        self.latest_frame = frame
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)

    def read(self):
        """Retrieves a thread-safe copy of the most recently extracted frame.

        Returns:
            A numpy array representing the image, or None if unavailable.
        """
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None

    def toggle_recording(self):
        """Toggles the state of video output recording.

        Returns:
            A boolean representing the active recording state.
        """
        self.is_recording = not self.is_recording

        if self.is_recording:
            os.makedirs(config.OUTPUT_DIR, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(
                config.OUTPUT_DIR, f"record_{timestamp}.mp4")

            fps = self.cap.get(cv2.CAP_PROP_FPS)
            fps = fps if fps > 0 else 30.0

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(
                filepath, fourcc, fps, (self.width, self.height))
        else:
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None

        return self.is_recording

    def write_frame(self, frame):
        """Commits a rendered frame to the disk buffer if recording is active.

        Args:
            frame: A numpy array representing the annotated image.
        """
        if self.is_recording and self.video_writer:
            self.video_writer.write(frame)

    def stop(self):
        """Safely tears down the extraction thread and file handlers."""
        self.running = False
        if self.is_recording:
            self.toggle_recording()
        if self.cap:
            self.cap.release()
