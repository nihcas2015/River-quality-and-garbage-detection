"""YOLOv8 trash detector — runs inference on Pi Camera V2 frames."""

import logging
import os
import subprocess
import tempfile
import numpy as np
from PIL import Image
from ultralytics import YOLO
import config

log = logging.getLogger(__name__)


class TrashDetector:
    """Loads a YOLOv8 model and detects trash in camera frames."""

    def __init__(self):
        self.model = None
        self.camera = False       # True when camera test passes
        self._tmp = os.path.join(tempfile.gettempdir(), "river_frame.jpg")

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
        """Test Pi Camera V2 via libcamera-still (CSI, Bookworm compatible)."""
        try:
            result = subprocess.run(
                ["libcamera-still", "-n", "-t", "1",
                 "--width", str(config.FRAME_WIDTH),
                 "--height", str(config.FRAME_HEIGHT),
                 "-o", self._tmp],
                capture_output=True, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode().strip())
            self.camera = True
            log.info("Pi Camera V2 OK via libcamera-still (%dx%d)",
                     config.FRAME_WIDTH, config.FRAME_HEIGHT)
            return True
        except Exception as e:
            log.error("Cannot open camera: %s", e)
            return False

    def detect(self):
        """Capture one frame via libcamera-still and run YOLO inference."""
        if not self.camera or self.model is None:
            return {"trash_count": 0, "detections": []}

        try:
            subprocess.run(
                ["libcamera-still", "-n", "-t", "1",
                 "--width", str(config.FRAME_WIDTH),
                 "--height", str(config.FRAME_HEIGHT),
                 "-o", self._tmp],
                capture_output=True, timeout=15,
            )
            frame = np.array(Image.open(self._tmp).convert("RGB"))
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

    # ── Federated Learning helpers ────────────────────────────

    def get_head_weights(self):
        """Extract flattened weights from the YOLOv8 detection head."""
        if self.model is None:
            return None
        try:
            import torch
            head = self.model.model.model[-1]   # Detect layer
            weights = []
            for p in head.parameters():
                weights.extend(p.detach().cpu().numpy().flatten().tolist())
            log.info("Extracted %d head-weight values", len(weights))
            return weights
        except Exception as e:
            log.error("Weight extraction failed: %s", e)
            return None

    def apply_head_weights(self, flat_weights):
        """Replace detection-head weights with aggregated global weights."""
        if self.model is None or flat_weights is None:
            return False
        try:
            import torch
            head = self.model.model.model[-1]
            idx = 0
            for p in head.parameters():
                numel = p.numel()
                chunk = flat_weights[idx:idx + numel]
                p.data.copy_(torch.tensor(chunk, dtype=p.dtype).reshape(p.shape))
                idx += numel
            log.info("Applied %d global head-weight values", idx)
            return True
        except Exception as e:
            log.error("Weight application failed: %s", e)
            return False

    def release(self):
        self.camera = False
        try:
            os.remove(self._tmp)
        except OSError:
            pass
        log.info("Camera released")
