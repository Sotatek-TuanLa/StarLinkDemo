"""Contains YOLO model wrappers and inference logic."""

import cv2
import queue
import numpy as np
from ultralytics import YOLO

import config


class YoloDetector:
    """Encapsulates YOLO inference and spatial reasoning logic."""

    def __init__(self, model_path):
        """Loads the model weights into memory.

        Args:
            model_path: Absolute or relative path to the .pt file.
        """
        self.model = YOLO(model_path)

    def infer(self, frame):
        """Executes a single forward pass on the image.

        Args:
            frame: A numpy array of the target image.

        Returns:
            A list of bounding box dictionaries containing coordinates and class ID.
        """
        results = self.model(
            frame, conf=config.CONFIDENCE_THRESHOLD, verbose=False)
        detections = []

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cls_id = int(box.cls[0].item())

                detections.append({
                    'box': [x1, y1, x2, y2],
                    'class': cls_id
                })

        return detections

    def evaluate_roi(self, detections, roi_points):
        """Checks intersection between detected objects and the user-defined area.

        Args:
            detections: List of detection dictionaries.
            roi_points: List of spatial coordinates defining the polygon.

        Returns:
            A tuple containing the string status state and its associated BGR color.
        """
        if not roi_points or len(roi_points) < 3:
            return "IDLE", config.COLOR_IDLE

        roi_poly = np.array(roi_points, np.int32).reshape((-1, 1, 2))
        status = "IDLE"
        color = config.COLOR_IDLE

        for det in detections:
            x1, y1, x2, y2 = det['box']
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

            is_touching = any(
                cv2.pointPolygonTest(roi_poly, (cx, cy), False) >= 0
                for cx, cy in corners
            )

            if is_touching:
                if det['class'] != 0:
                    status = "NG"
                    color = config.COLOR_NG
                    break
                else:
                    status = "OK"
                    color = config.COLOR_OK

        return status, color


def detection_worker(frame_queue, result_queue, model_path):
    """Isolated process entrypoint for asynchronous inference execution.

    Args:
        frame_queue: Queue providing tuples of (frame, roi_points).
        result_queue: Queue outputting synced tuples of (frame, detections, status, color).
        model_path: Path string to the YOLO weights.
    """
    # Delay instantiation until subprocess execution to avoid PyTorch memory locks
    detector = YoloDetector(model_path)

    while True:
        try:
            data = frame_queue.get()
            if data is None:
                break

            frame, roi_points = data
            detections = detector.infer(frame)
            status, color = detector.evaluate_roi(detections, roi_points)

            # Purge outdated frames from the result queue to enforce low latency
            while not result_queue.empty():
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    break

            result_queue.put((frame, detections, status, color))

        except Exception as e:
            print(f"Worker exception: {e}")
            break
