# 🚀 Quick Reference Guide

## File Structure Overview

```
river_monitoring/
├── pi4_edge_node/              # Edge Node Code
│   ├── main_edge.py            # Main entry point
│   ├── sensor_reader.py        # MQTT subscriber (ESP32 data)
│   ├── trash_detector.py       # YOLOv8 model
│   ├── federated_client.py     # Server communication
│   ├── config.py               # Configuration
│   ├── requirements.txt        # Python deps
│   └── pi4_setup.sh            # Setup script
│
├── pi5_central_node/           # Central Node Code
│   ├── server.py               # Flask API + WebSocket
│   ├── federated_server.py     # FedAvg logic
│   └── requirements.txt        # Python deps
│
├── dashboard/frontend/         # React Dashboard
│   ├── src/
│   │   ├── components/         # UI components
│   │   ├── pages/              # Page components
│   │   ├── api/                # API client
│   │   ├── styles/             # CSS files
│   │   ├── App.js              # Main app
│   │   └── index.js            # Entry point
│   ├── public/index.html
│   └── package.json            # npm dependencies
│
├── README.md                   # Full documentation
├── INSTALLATION.md             # Setup guide
├── DEPLOYMENT.md               # Production guide
├── SUMMARY.md                  # Overview
│
├── docker-compose.yml          # Docker orchestration
├── Dockerfile.pi5              # Pi5 container
├── Dockerfile.dashboard        # Dashboard container
├── setup.sh                    # Complete setup
├── best.pt                     # YOUR trained model
└── best.onnx                   # Optional ONNX model
```

---

## 🔑 Key Commands

### Pi5 Central Node
```bash
# Install
chmod +x pi5_setup.sh && ./pi5_setup.sh

# Start
sudo systemctl start river-central
sudo systemctl stop river-central
sudo systemctl restart river-central

# Monitor
sudo journalctl -u river-central -f
sudo systemctl status river-central

# Check API
curl http://localhost:5000/api/health
curl http://localhost:5000/api/federation_status
```

### Pi4 Edge Node
```bash
# Install
cd ~/river_monitoring
chmod +x pi4_setup.sh && ./pi4_setup.sh

# Configure
nano .env
# Update: SERVER_URL, EDGE_NODE_ID, CAMERA_INDEX

# Test
python3 -c "from pi4_edge_node.sensor_reader import SensorReader; print(SensorReader().get_all_sensor_data())"

# Run
source venv/bin/activate
python main_edge.py

# Monitor
tail -f edge_node.log
```

### Dashboard
```bash
# Development
cd dashboard/frontend
npm install
npm start         # http://localhost:3000

# Production (Docker)
docker build -f Dockerfile.dashboard -t river-dashboard .
docker run -p 3000:3000 river-dashboard

# Production (PM2)
npm install -g pm2
pm2 start npm -- start --name dashboard
pm2 save
pm2 startup
```

### Docker
```bash
# Complete setup
chmod +x setup.sh && ./setup.sh

# Manual Docker control
docker-compose build
docker-compose up -d
docker-compose down
docker-compose logs -f

# Individual services
docker-compose up -d pi5-central
docker-compose up -d dashboard
docker-compose logs pi5-central
```

---

## 📡 API Quick Reference

### Health & Status
```bash
GET  /api/health                          # Server status
GET  /api/federation_status               # Fed status + nodes
```

### Federated Learning
```bash
POST /api/register_node                   # Register edge node
POST /api/heartbeat                       # Node heartbeat
POST /api/submit_data                     # Send sensor/detection
POST /api/upload_weights                  # Upload model weights
GET  /api/get_weights                     # Get global weights
```

### Dashboard Data
```bash
GET  /api/dashboard/river_data            # Aggregated metrics
GET  /api/dashboard/latest_readings       # All nodes latest data
GET  /api/dashboard/alerts                # Recent alerts
GET  /api/dashboard/trash_history         # Trash events
GET  /api/dashboard/node_status           # All nodes status
```

### WebSocket Events
```
connect          → Client connected
subscribe_updates → Join 'dashboard' room
dashboard_update → Real-time data (~5s)
data_update      → New sensor/detection
alert            → New alert
```

---

## ⚙️ Configuration Cheatsheet

### Pi4 .env File
```env
SERVER_URL=http://192.168.1.100:5000           # Pi5 IP
EDGE_NODE_ID=pi4_edge_01                       # Unique name
MQTT_BROKER=localhost                          # Mosquitto broker
MQTT_TOPIC=river/sensors                       # ESP32 publish topic
CAMERA_INDEX=0                                 # Camera device
MODEL_PATH=./best.pt                           # Model file
CONFIDENCE_THRESHOLD=0.5                       # Detection
SENSOR_INTERVAL=5                              # Read sensors
DETECTION_INTERVAL=2                           # Run detection
COMMUNICATION_INTERVAL=30                      # Send to Pi5
```

### Sensor Thresholds (sensor_reader.py)
```python
TEMP_MIN = 4    TEMP_MAX = 35      # °C
PH_MIN = 6.0    PH_MAX = 9.0       # pH scale
# MQTT_TOPIC = river/sensors       # ESP32 publish topic
```

### Dashboard ENV (frontend/.env)
```env
REACT_APP_API_URL=http://localhost:5000
```

---

## 🐛 Troubleshooting Quick Fixes

| Issue | Solution |
|-------|----------|
| Pi4 can't reach Pi5 | Check IP: `ping 192.168.1.100` |
| API returns 404 | Ensure server running: `curl http://localhost:5000` |
| No sensor data | Check I2C: `i2cdetect -y 1` |
| Camera not working | Test: `raspistill -o test.jpg` |
| Model load fails | Verify path: `ls -la best.pt` |
| High latency | Reduce `DETECTION_INTERVAL` |
| Memory issues | Reduce model size or detection frequency |
| Dashboard won't load | Check REACT_APP_API_URL in .env |

---

## 📊 Typical Data Flow

```
Every 5s:  Pi4 receives MQTT data (Temp, pH)
                    ↓
Every 2s:  Pi4 runs YOLOv8 detection on camera
                    ↓
Every 30s: Pi4 sends data to Pi5
          Pi5 aggregates all nodes
          Pi5 broadcasts update via WebSocket
                    ↓
Dashboard receives & displays in real-time
```

---

## 🎯 Common Customizations

### Change Detection Frequency
**File:** `pi4_edge_node/main_edge.py`
```python
self.detection_interval = 2  # Change from 2 to 1 for faster
```

### Add New Sensor
**File:** `pi4_edge_node/sensor_reader.py`
```python
def read_new_sensor(self):
    # Your sensor reading code
    return value
```

### Modify Dashboard Theme
**File:** `dashboard/frontend/src/styles/index.css`
```css
:root {
  --primary: #3b82f6;    /* Change colors */
  --danger: #ef4444;
}
```

### Change Anomaly Threshold
**File:** `pi4_edge_node/sensor_reader.py` (detect_anomalies method)
```python
if temp < 5 or temp > 30:  # Change thresholds
    anomalies['temp_anomaly'] = True
```

---

## 📈 System Monitoring

### Pi4 Status
```bash
# Connected to server?
curl http://<pi5-ip>:5000/api/federation_status | grep <node-id>

# Running sensors?
ps aux | grep python | grep main_edge

# Disk space?
df -h

# Temperature?
vcgencmd measure_temp

# Memory?
free -h
```

### Pi5 Status
```bash
# Server running?
sudo systemctl status river-central

# API responsive?
curl http://localhost:5000/api/health

# Database/data?
ls -la data/

# Resource usage?
top
```

---

## 🔐 Important Security Notes

1. **Never commit .env files** to git
2. **Change default credentials** if enabled
3. **Use static IPs** for reliability
4. **Firewall ports** in production
5. **Enable SSH keys** (disable password auth)
6. **Regular backups** of configuration
7. **Monitor logs** regularly
8. **Update packages** monthly

---

## 📞 When Things Go Wrong

### Step 1: Check Logs
```bash
# Pi4
tail -100f ~/river_monitoring/edge_node.log

# Pi5
sudo journalctl -u river-central -n 100
```

### Step 2: Verify Connectivity
```bash
# Can Pi4 reach Pi5?
ping <pi5-ip>
curl http://<pi5-ip>:5000/api/health
```

### Step 3: Check Services
```bash
# Is service running?
ps aux | grep python | grep -v grep

# Is port open?
netstat -tulpn | grep 5000
```

### Step 4: Restart
```bash
# Clean restart
killall python
source venv/bin/activate
python main_edge.py
```

### Step 5: Still Stuck?
- Read logs carefully for error messages
- Check documentation: README.md
- Review troubleshooting guide: DEPLOYMENT.md
- Verify configuration: .env file
- Test components individually

---

## 🎓 Learning Resources

- **Docker**: https://docker.com
- **Flask**: https://flask.palletsprojects.com
- **React**: https://react.dev
- **YOLOv8**: https://ultralytics.com
- **Raspberry Pi**: https://raspberrypi.com

---

## 📝 Version Info

- **System**: Federated River Monitoring v1.0
- **Python**: 3.9+
- **Node**: 18+
- **Docker**: 20+
- **Created**: February 24, 2026

---

**Save this file for quick reference! 📌**
