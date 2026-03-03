"""YOLOv8 trash detector — runs inference on Pi Camera V2 frames.

Supports three backends (tried in order):
  1. OpenCV DNN  — safest on Pi4, no PyTorch/onnxruntime needed
  2. ONNX        — via ultralytics + onnxruntime
  3. PyTorch .pt — original, may crash with 'Illegal instruction' on Pi4
"""

import logging
import os
import subprocess
import tempfile
import numpy as np
import cv2
from PIL import Image
import config

log = logging.getLogger(__name__)

# Class names from config (or fall back to generic indices)
CLASS_NAMES = getattr(config, "YOLO_CLASSES", [])


# ── OpenCV DNN helpers (no PyTorch / no onnxruntime) ─────────

def _letterbox(img, new_shape=640):
    """Resize + pad image to square (letterbox) for YOLO input."""
    h, w = img.shape[:2]
    scale = new_shape / max(h, w)
    nw, nh = int(w * scale), int(h * scale)
    img_resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new_shape, new_shape, 3), 114, dtype=np.uint8)
    dw, dh = (new_shape - nw) // 2, (new_shape - nh) // 2
    canvas[dh:dh + nh, dw:dw + nw] = img_resized
    return canvas, scale, dw, dh


def _cv_nms(boxes, scores, conf_thresh, iou_thresh=0.45):
    """Apply Non-Maximum Suppression and return filtered indices."""
    indices = cv2.dnn.NMSBoxes(
        boxes.tolist(), scores.tolist(), conf_thresh, iou_thresh)
    if len(indices) == 0:
        return []
    return indices.flatten().tolist()


class TrashDetector:
    """Loads a YOLOv8 model and detects trash in camera frames."""

    def __init__(self):
        self.model = None         # ultralytics YOLO or None
        self.cv_net = None        # OpenCV DNN net (fallback)
        self.model_type = None    # "cv_dnn", "onnx", or "pt"
        self.camera = False
        self._tmp = os.path.join(tempfile.gettempdir(), "river_frame.jpg")
        self._input_size = 640    # YOLOv8 default input

    def load_model(self):
        """Load the YOLOv8 model. Tries backends in safe order:
        OpenCV DNN → ONNX (ultralytics) → PyTorch .pt"""
        onnx_path = getattr(config, "MODEL_ONNX", "best.onnx")

        # ── 1. OpenCV DNN (safest — works on every Pi4) ──────
        if os.path.isfile(onnx_path):
            try:
                net = cv2.dnn.readNetFromONNX(onnx_path)
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                # Quick sanity check — run a dummy forward pass
                dummy = np.zeros((1, 3, self._input_size, self._input_size),
                                 dtype=np.float32)
                net.setInput(dummy)
                net.forward()
                self.cv_net = net
                self.model_type = "cv_dnn"
                log.info("Model loaded via OpenCV DNN: %s (safe for Pi4)",
                         onnx_path)
                return True
            except Exception as e:
                log.warning("OpenCV DNN failed (%s), trying ultralytics...", e)

        # ── 2. ONNX via ultralytics (needs onnxruntime) ──────
        if os.path.isfile(onnx_path):
            try:
                from ultralytics import YOLO
                self.model = YOLO(onnx_path, task="detect")
                self.model_type = "onnx"
                log.info("Model loaded via ultralytics ONNX: %s", onnx_path)
                return True
            except Exception as e:
                log.warning("ONNX ultralytics failed (%s), trying .pt...", e)

        # ── 3. PyTorch .pt (may crash on Pi4 Cortex-A72) ─────
        try:
            from ultralytics import YOLO
            self.model = YOLO(config.MODEL_PATH)
            self.model_type = "pt"
            log.info("Model loaded via PyTorch: %s", config.MODEL_PATH)
            return True
        except Exception as e:
            log.error("All backends failed. Last error: %s", e)
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

    def _capture_frame(self):
        """Capture a frame using libcamera-still and return as numpy RGB."""
        subprocess.run(
            ["libcamera-still", "-n", "-t", "1",
             "--width", str(config.FRAME_WIDTH),
             "--height", str(config.FRAME_HEIGHT),
             "-o", self._tmp],
            capture_output=True, timeout=15,
        )
        return np.array(Image.open(self._tmp).convert("RGB"))

    def _detect_cv_dnn(self, frame):
        """Run inference using OpenCV DNN backend (no PyTorch needed)."""
        img, scale, dw, dh = _letterbox(frame, self._input_size)
        blob = cv2.dnn.blobFromImage(
            img, scalefactor=1.0 / 255.0,
            size=(self._input_size, self._input_size),
            swapRB=True, crop=False)
        self.cv_net.setInput(blob)
        output = self.cv_net.forward()   # shape: (1, 4+num_classes, num_preds)

        # YOLOv8 output: (1, 4+C, N) — transpose to (N, 4+C)
        if output.ndim == 3:
            output = output[0]                     # (4+C, N)
        preds = output.T                           # (N, 4+C)
        num_classes = preds.shape[1] - 4

        # Extract boxes (cx, cy, w, h) and class scores
        cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
        class_scores = preds[:, 4:]                # (N, C)
        max_scores = np.max(class_scores, axis=1)
        class_ids = np.argmax(class_scores, axis=1)

        # Filter by confidence
        conf_thresh = config.CONFIDENCE
        mask = max_scores >= conf_thresh
        if not np.any(mask):
            return {"trash_count": 0, "detections": [], "class_counts": {}}

        cx, cy, w, h = cx[mask], cy[mask], w[mask], h[mask]
        max_scores = max_scores[mask]
        class_ids = class_ids[mask]

        # Convert cx,cy,w,h → x1,y1,w,h for NMS
        boxes_xywh = np.stack([cx - w / 2, cy - h / 2, w, h], axis=1)

        # NMS
        keep = _cv_nms(boxes_xywh, max_scores, conf_thresh, 0.45)
        if not keep:
            return {"trash_count": 0, "detections": [], "class_counts": {}}

        detections = []
        class_counts = {}
        for i in keep:
            x1 = (cx[i] - w[i] / 2 - dw) / scale
            y1 = (cy[i] - h[i] / 2 - dh) / scale
            x2 = (cx[i] + w[i] / 2 - dw) / scale
            y2 = (cy[i] + h[i] / 2 - dh) / scale
            cid = int(class_ids[i])
            cls_name = (CLASS_NAMES[cid] if cid < len(CLASS_NAMES)
                        else f"class_{cid}")
            detections.append({
                "class": cls_name,
                "confidence": round(float(max_scores[i]), 3),
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
            })
            class_counts[cls_name] = class_counts.get(cls_name, 0) + 1

        return {
            "trash_count": len(detections),
            "detections": detections,
            "class_counts": class_counts,
        }

    def _detect_ultralytics(self, frame):
        """Run inference via ultralytics YOLO (ONNX or .pt)."""
        results = self.model(frame, conf=config.CONFIDENCE, verbose=False)
        detections = []
        class_counts = {}
        for r in results:
            for box in r.boxes:
                cls_name = r.names[int(box.cls[0])]
                detections.append({
                    "class": cls_name,
                    "confidence": round(float(box.conf[0]), 3),
                    "bbox": box.xyxy[0].tolist(),
                })
                class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
        return {
            "trash_count": len(detections),
            "detections": detections,
            "class_counts": class_counts,
        }

    def detect(self):
        """Capture one frame and run YOLO inference (auto-selects backend)."""
        if not self.camera or (self.model is None and self.cv_net is None):
            return {"trash_count": 0, "detections": []}

        try:
            frame = self._capture_frame()
        except Exception as e:
            log.warning("Frame capture failed: %s", e)
            return {"trash_count": 0, "detections": []}

        try:
            if self.model_type == "cv_dnn":
                return self._detect_cv_dnn(frame)
            else:
                return self._detect_ultralytics(frame)
        except Exception as e:
            log.warning("Inference failed (%s): %s", self.model_type, e)
            return {"trash_count": 0, "detections": []}

    # ── Federated Learning helpers ────────────────────────────

    def get_head_weights(self):
        """Extract flattened weights from the YOLOv8 detection head.
        Only works with PyTorch .pt model; returns None for DNN/ONNX."""
        if self.model is None or self.model_type == "cv_dnn":
            log.debug("Weight extraction not available for %s backend",
                      self.model_type)
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
        """Replace detection-head weights with aggregated global weights.
        Only works with PyTorch .pt model."""
        if self.model is None or flat_weights is None:
            return False
        if self.model_type == "cv_dnn":
            log.debug("Weight application not available for cv_dnn backend")
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
