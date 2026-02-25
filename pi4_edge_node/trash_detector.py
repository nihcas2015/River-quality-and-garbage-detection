"""YOLOv8 trash detector — runs inference on Pi Camera V2 frames."""

import logging
import cv2
from ultralytics import YOLO
import config

log = logging.getLogger(__name__)


class TrashDetector:
    """Loads a YOLOv8 model and detects trash in camera frames."""

    def __init__(self):
        self.model = None
        self.camera = None

    def load_model(self):
        """Load the YOLOv8 model file."""
        try:
            self.model = YOLO(config.MODEL_PATH)
            log.info("YOLOv8 model loaded: %s", config.MODEL_PATH)
            return True
        except Exception as e:
            log.error("Failed to load model: %s", e)
            return False

    def open_camera(self):
        """Open Pi Camera V2 via OpenCV."""
        self.camera = cv2.VideoCapture(config.CAMERA_INDEX)
        if self.camera.isOpened():
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
            log.info("Camera opened (index %d)", config.CAMERA_INDEX)
            return True
        log.error("Cannot open camera")
        return False

    def detect(self):
        """Capture one frame and run YOLO inference. Returns dict."""
        if self.camera is None or not self.camera.isOpened():
            return {"trash_count": 0, "detections": []}

        ret, frame = self.camera.read()
        if not ret:
            log.warning("Frame capture failed")
            return {"trash_count": 0, "detections": []}

        results = self.model(frame, conf=config.CONFIDENCE, verbose=False)

        detections = []
        for r in results:
            for box in r.boxes:
                detections.append({
                    "class": r.names[int(box.cls[0])],
                    "confidence": round(float(box.conf[0]), 3),
                    "bbox": box.xyxy[0].tolist(),
                })

        return {
            "trash_count": len(detections),
            "detections": detections,
        }

    def release(self):
        if self.camera:
            self.camera.release()
            log.info("Camera released")
