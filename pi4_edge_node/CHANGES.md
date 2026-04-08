# Changes Made to Pi4 Edge Node

## What Changed

### trash_detector.py
**Replaced subprocess CLI (libcamera-still/rpicam-still/raspistill) with direct rpicamera2 library**

Key changes:
1. **Import rpicamera2** instead of subprocess
2. **open_camera()** - Now uses `Picamera2()` directly (faster, more reliable)
3. **_capture_frame()** - Uses `camera.capture_array()` instead of disk writes
4. **Model loading** - Tries ONNX first (safest), then .pt fallback
5. **Removed all subprocess calls** - No more temp files or CLI overhead

### Model Priority (Updated)
1. **ONNX + OpenCV DNN** - Fastest, safest on Pi4 (no Illegal instruction)
2. **ONNX + ultralytics** - Fallback if DNN fails
3. **PyTorch .pt** - Last resort (may have compatibility issues)

### requirements.txt
- Removed subprocess calls references
- Now expects picamera2 to be installed via `sudo apt-get install -y python3-picamera2`
- Simplified to: ONNX (preferred) or .pt (fallback)

---

## What to Replace

**In your pi4_edge_node folder, replace:**

1. `trash_detector.py` - Completely rewritten to use rpicamera2
2. `requirements.txt` - Updated dependencies
3. Delete these files (no longer needed):
   - `check_camera.sh`
   - `CAMERA_SETUP.md`
   - `CAMERA_FIX_SUMMARY.md`
   - `QUICK_FIX.md`

---

## How It Works Now

### Setup (One time)
```bash
# Install camera library
sudo apt-get install -y python3-picamera2

# Install Python deps
cd pi4_edge_node
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
python3 main_edge.py
```

### What Happens
1. **Startup:**
   - Loads ONNX model (fast, safe)
   - If ONNX fails, tries .pt model
   - Opens rpicamera2 (direct library, no subprocess)
   
2. **Detection loop:**
   - Captures frame directly from camera RAM
   - Runs inference (whichever model worked)
   - Sends detections to Pi5

---

## Benefits

✅ **Faster** - No disk writes, direct RAM capture  
✅ **More reliable** - Uses library instead of CLI  
✅ **Flexible** - Supports both ONNX and .pt models  
✅ **Cleaner** - No temporary files or subprocess overhead  
✅ **Better logging** - Clear model loading priority  

---

## If Models Don't Work

**If ONNX fails:** Automatically tries .pt  
**If .pt fails:** YOLO inference disabled, system still runs sensors/fed learning  
**If camera fails:** Clear error message telling you what to fix

---

## File Sizes (Approximate)

- `best.onnx` - ~40-50 MB (OpenCV DNN: fastest on Pi4)
- `best.pt` - ~45-55 MB (PyTorch: fallback only)

Both should fit in Pi4 RAM (4GB).
