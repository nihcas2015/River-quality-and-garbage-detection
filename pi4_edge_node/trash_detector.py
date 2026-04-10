"""YOLOv8 trash detector — runs inference on Pi Camera V2 frames.

Supports three backends (tried in order):
  1. OpenCV DNN  — safest on Pi4, no PyTorch/onnxruntime needed
  2. ONNX        — via ultralytics + onnxruntime
  3. PyTorch .pt — original, may crash with 'Illegal instruction' on Pi4

Camera capture methods (tried in order):
  1. Picamera2 Python library (recommended for Bookworm)
  2. libcamera-still command-line (fallback)
  3. OpenCV cv2.VideoCapture() (last resort)
"""

import logging
import os
import subprocess
import tempfile
import numpy as np
import cv2
from PIL import Image
import config

# Try to import picamera2 (recommended for Pi4 with Bookworm)
PICAMERA2_AVAILABLE = False
try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    pass

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
        
        # Camera options
        self.camera = False
        self.picam2 = None        # Picamera2 instance
        self.camera_method = None # "picamera2", "libcamera", or "opencv"
        
        self._tmp = os.path.join(tempfile.gettempdir(), "river_frame.jpg")
        self._input_size = 640    # YOLOv8 default input

    def load_model(self):
        """Load the YOLOv8 model. Tries backends in safe order:
        OpenCV DNN → ONNX (ultralytics) → PyTorch .pt"""
        onnx_path = getattr(config, "MODEL_ONNX", "best.onnx")
        pt_path = getattr(config, "MODEL_PATH", "best.pt")
        
        log.info("🔍 Searching for models: onnx='%s', pt='%s'", onnx_path, pt_path)

        # ── 1. OpenCV DNN (safest — works on every Pi4) ──────
        if os.path.isfile(onnx_path):
            try:
                log.info("  [1/3] Trying OpenCV DNN with %s...", onnx_path)
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
                log.info("✓ Model loaded via OpenCV DNN: %s (BEST for Pi4)", onnx_path)
                return True
            except Exception as e:
                log.warning("⚠ OpenCV DNN failed: %s", e)
        else:
            log.debug("  [1/3] ONNX file not found: %s", onnx_path)

        # ── 2. ONNX via ultralytics (needs onnxruntime) ──────
        if os.path.isfile(onnx_path):
            try:
                log.info("  [2/3] Trying ultralytics ONNX with %s...", onnx_path)
                from ultralytics import YOLO
                self.model = YOLO(onnx_path, task="detect")
                self.model_type = "onnx"
                log.info("✓ Model loaded via ultralytics ONNX: %s", onnx_path)
                return True
            except Exception as e:
                log.warning("⚠ ONNX ultralytics failed: %s", e)
        else:
            log.debug("  [2/3] ONNX file not found: %s", onnx_path)

        # ── 3. PyTorch .pt (may crash on Pi4 Cortex-A72) ─────
        if os.path.isfile(pt_path):
            try:
                log.info("  [3/3] Trying PyTorch with %s...", pt_path)
                from ultralytics import YOLO
                self.model = YOLO(pt_path)
                self.model_type = "pt"
                log.warning("⚠ Model loaded via PyTorch (slower/risky on Pi4): %s", pt_path)
                log.warning("  → Consider converting to ONNX for better performance")
                return True
            except Exception as e:
                log.warning("⚠ PyTorch failed: %s", e)
        else:
            log.debug("  [3/3] PyTorch file not found: %s", pt_path)

        log.error("✗ CRITICAL: No models found! Check paths:")
        log.error("  → ONNX: %s", onnx_path)
        log.error("  → PyTorch: %s", pt_path)
        return False

    def open_camera(self):
        """Test Pi Camera V2 via picamera2 (recommended) or libcamera-still or OpenCV."""
        
        # ── 1. Try picamera2 (recommended for Bookworm) ──────────────────
        if PICAMERA2_AVAILABLE:
            try:
                log.info("  [1/3] Trying picamera2 Python library...")
                self.picam2 = Picamera2()
                config_dict = self.picam2.create_preview_configuration(
                    main={"format": "RGB888", 
                          "size": (config.FRAME_WIDTH, config.FRAME_HEIGHT)}
                )
                self.picam2.configure(config_dict)
                self.picam2.start()
                
                # Test capture
                test_frame = self.picam2.capture_array()
                if test_frame is not None and test_frame.shape[0] > 0:
                    self.camera = True
                    self.camera_method = "picamera2"
                    log.info("✓ Camera initialized via picamera2 (%dx%d) [BEST]",
                             config.FRAME_WIDTH, config.FRAME_HEIGHT)
                    return True
                else:
                    raise RuntimeError("No frame captured from picamera2")
            except Exception as e:
                log.warning("⚠ picamera2 failed: %s", e)
                if self.picam2:
                    try:
                        self.picam2.stop()
                    except:
                        pass
                self.picam2 = None
        else:
            log.debug("  [1/3] picamera2 not installed, trying alternatives...")
        
        # ── 2. Try libcamera-still (fallback) ──────────────────────────
        try:
            log.info("  [2/3] Trying libcamera-still command-line...")
            result = subprocess.run(
                ["which", "libcamera-still"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                # Test capture
                result = subprocess.run(
                    ["libcamera-still", "-n", "-t", "1",
                     "--width", str(config.FRAME_WIDTH),
                     "--height", str(config.FRAME_HEIGHT),
                     "-o", self._tmp],
                    capture_output=True, timeout=10,
                )
                if result.returncode == 0:
                    self.camera = True
                    self.camera_method = "libcamera"
                    log.info("✓ Camera initialized via libcamera-still (%dx%d)",
                             config.FRAME_WIDTH, config.FRAME_HEIGHT)
                    return True
                else:
                    stderr = result.stderr.decode().strip()
                    log.warning("⚠ libcamera-still test failed: %s", stderr)
        except Exception as e:
            log.debug("⚠ libcamera-still check failed: %s", e)
        
        # ── 3. Try OpenCV cv2.VideoCapture (last resort) ────────────────
        try:
            log.info("  [3/3] Trying OpenCV cv2.VideoCapture...")
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                # Try to read a frame
                ret, frame = cap.read()
                if ret and frame is not None:
                    self.camera = True
                    self.camera_method = "opencv"
                    self._cv_capture = cap
                    log.info("✓ Camera initialized via OpenCV cv2.VideoCapture (%dx%d)",
                             config.FRAME_WIDTH, config.FRAME_HEIGHT)
                    return True
                cap.release()
                log.warning("⚠ OpenCV camera opened but no frame captured")
        except Exception as e:
            log.debug("⚠ OpenCV capture failed: %s", e)
        
        # All methods failed
        log.error("✗ CRITICAL: No camera method available!")
        log.error("  Options:")
        log.error("    1. Install picamera2: pip install picamera2")
        log.error("    2. Install libcamera: sudo apt install -y libcamera-tools")
        log.error("    3. Use OpenCV: OpenCV should already be installed")
        log.error("  Check:")
        log.error("    - Is camera connected to CSI port?")
        log.error("    - Is camera enabled in raspi-config?")
        log.error("    - Run: libcamera-hello --list-cameras")
        return False

    def _capture_frame(self):
        """Capture a frame using the available camera method and return as numpy RGB."""
        try:
            if self.camera_method == "picamera2":
                return self._capture_picamera2()
            elif self.camera_method == "libcamera":
                return self._capture_libcamera()
            elif self.camera_method == "opencv":
                return self._capture_opencv()
            else:
                raise RuntimeError(f"Unknown camera method: {self.camera_method}")
        except Exception as e:
            log.error("✗ Frame capture error: %s", e)
            raise

    def _capture_picamera2(self):
        """Capture frame using picamera2."""
        try:
            frame = self.picam2.capture_array()
            if frame is None:
                raise RuntimeError("picamera2 returned None")
            # Convert BGR to RGB if needed
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                # RGB888 format should already be RGB
                pass
            log.debug("✓ Frame captured via picamera2: %dx%d", frame.shape[1], frame.shape[0])
            return frame
        except Exception as e:
            log.error("✗ picamera2 capture failed: %s", e)
            raise

    def _capture_libcamera(self):
        """Capture frame using libcamera-still command."""
        try:
            result = subprocess.run(
                ["libcamera-still", "-n", "-t", "1",
                 "--width", str(config.FRAME_WIDTH),
                 "--height", str(config.FRAME_HEIGHT),
                 "-o", self._tmp],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(f"libcamera-still failed: {result.stderr.decode().strip()}")
            
            if not os.path.exists(self._tmp):
                raise RuntimeError(f"Frame file not created: {self._tmp}")
            
            frame = np.array(Image.open(self._tmp).convert("RGB"))
            log.debug("✓ Frame captured via libcamera: %dx%d", frame.shape[1], frame.shape[0])
            return frame
        except subprocess.TimeoutExpired:
            log.error("✗ libcamera-still timeout")
            raise
        except Exception as e:
            log.error("✗ libcamera capture failed: %s", e)
            raise

    def _capture_opencv(self):
        """Capture frame using OpenCV cv2.VideoCapture."""
        try:
            ret, frame = self._cv_capture.read()
            if not ret or frame is None:
                raise RuntimeError("Failed to capture frame")
            
            # Convert BGR to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Resize to expected dimensions
            frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))
            
            log.debug("✓ Frame captured via OpenCV: %dx%d", frame.shape[1], frame.shape[0])
            return frame
        except Exception as e:
            log.error("✗ OpenCV capture failed: %s", e)
            raise

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
        if not self.camera:
            log.debug("⚠ Camera not initialized, skipping detection")
            return {"trash_count": 0, "detections": [], "class_counts": {}}
        
        if self.model is None and self.cv_net is None:
            log.debug("⚠ Model not initialized, skipping detection")
            return {"trash_count": 0, "detections": [], "class_counts": {}}

        try:
            frame = self._capture_frame()
        except Exception as e:
            log.warning("⚠ Frame capture failed: %s (will retry next cycle)", e)
            return {"trash_count": 0, "detections": [], "class_counts": {}}

        try:
            if self.model_type == "cv_dnn":
                log.debug("Running inference (OpenCV DNN)...")
                return self._detect_cv_dnn(frame)
            else:
                log.debug("Running inference (ultralytics)...")
                return self._detect_ultralytics(frame)
        except Exception as e:
            log.warning("⚠ Inference failed (%s): %s", self.model_type, e)
            return {"trash_count": 0, "detections": [], "class_counts": {}}

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
        
        # Release picamera2 if used
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
                log.info("✓ picamera2 released")
            except Exception as e:
                log.warning("⚠ Error releasing picamera2: %s", e)
        
        # Release OpenCV capture if used
        if self.camera_method == "opencv" and hasattr(self, '_cv_capture'):
            try:
                self._cv_capture.release()
                log.info("✓ OpenCV capture released")
            except Exception as e:
                log.warning("⚠ Error releasing OpenCV: %s", e)
        
        # Clean up temp file
        try:
            os.remove(self._tmp)
        except OSError:
            pass
        
        log.info("✓ Camera released (method: %s)", self.camera_method)
