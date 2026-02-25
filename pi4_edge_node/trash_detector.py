"""YOLOv8 trash detector — runs inference on Pi Camera V2 frames."""

import logging
import numpy as np
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
        """Open Pi Camera V2 using Picamera2 (required on Bookworm+)."""
        try:
            from picamera2 import Picamera2
            self.camera = Picamera2()
            cam_config = self.camera.create_still_configuration(
                main={"size": (config.FRAME_WIDTH, config.FRAME_HEIGHT),
                      "format": "RGB888"}
            )
            self.camera.configure(cam_config)
            self.camera.start()
            log.info("Pi Camera V2 opened via Picamera2 (%dx%d)",
                     config.FRAME_WIDTH, config.FRAME_HEIGHT)
            return True
        except Exception as e:
            log.error("Cannot open camera: %s", e)
            return False

    def detect(self):
        """Capture one frame and run YOLO inference. Returns dict."""
        if self.camera is None:
            return {"trash_count": 0, "detections": []}

        try:
            frame = self.camera.capture_array()
        except Exception as e:
            log.warning("Frame capture failed: %s", e)
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
            try:
                self.camera.stop()
            except Exception:
                pass
            log.info("Camera released")
