"""Contains YOLO model wrappers and inference logic."""

import cv2
import queue
from ultralytics import YOLO

import config


class YoloDetector:
    """Encapsulates YOLO inference and basic detection validation."""

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
            A list of bounding box coordinates [x1, y1, x2, y2].
        """
        results = self.model(
            frame, conf=config.CONFIDENCE_THRESHOLD, verbose=False)
        detections = []

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append([int(x1), int(y1), int(x2), int(y2)])

        return detections

    def evaluate_detections(self, detections):
        """Evaluates overall frame status based on presence of detections.

        Args:
            detections: List of detection bounding boxes.

        Returns:
            A tuple containing the string status state and its associated BGR color.
        """
        if len(detections) > 0:
            return "NG", config.COLOR_NG

        return "OK", config.COLOR_OK


def detection_worker(frame_queue, result_queue, model_path):
    """Isolated process entrypoint for asynchronous inference execution.

    Args:
        frame_queue: Queue providing frames for inference.
        result_queue: Queue outputting synced tuples of (frame, detections, status, color).
        model_path: Path string to the YOLO weights.
    """
    detector = YoloDetector(model_path)

    while True:
        try:
            frame = frame_queue.get()
            if frame is None:
                break

            detections = detector.infer(frame)
            status, color = detector.evaluate_detections(detections)

            while not result_queue.empty():
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    break

            result_queue.put((frame, detections, status, color))

        except Exception as e:
            print(f"Worker exception: {e}")
            break
