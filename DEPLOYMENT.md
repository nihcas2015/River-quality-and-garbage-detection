# Deployment & Operations Guide

## 📋 Pre-Deployment Checklist

- [ ] Trained YOLOv8 model (`best.pt`) ready
- [ ] Raspberry Pi 4 units with camera modules
- [ ] Raspberry Pi 5 for central node
- [ ] ESP32 boards with DS18B20 temperature probes
- [ ] Gravity pH sensors
- [ ] Gravity analog pH sensors
- [ ] Power supplies for all devices
- [ ] Network connectivity (Ethernet or WiFi)
- [ ] MicroSD cards formatted and OS installed
- [ ] Static IP addresses assigned to Pis

## 🚀 Pi5 Central Node Deployment

### Step 1: Initial Setup

```bash
# SSH to Pi5
ssh pi@<pi5-ip>

# Update system
sudo apt update && sudo apt upgrade -y

# Enable required interfaces
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
```

### Step 2: Install Runtime

```bash
# Clone or download project
git clone <repository> ~/river_monitoring
cd ~/river_monitoring

# Run setup script
chmod +x pi5_setup.sh
./pi5_setup.sh

# Install additional tools
sudo apt install -y htop iotop ntp
```

### Step 3: Start Services

```bash
# Enable and start service
sudo systemctl enable river-central
sudo systemctl start river-central

# Verify
sudo systemctl status river-central

# Check API
curl http://localhost:5000/api/health
```

### Step 4: Monitor

```bash
# View real-time logs
sudo journalctl -u river-central -f

# Check resource usage
htop
```

## 🔧 Pi4 Edge Node Deployment

### Step 1: Node Preparation

```bash
# For each Pi4 node:
ssh pi@<pi4-ip>

# Update system
sudo apt update && sudo apt upgrade -y

# Run setup
chmod +x pi4_setup.sh
./pi4_setup.sh

# Enable camera and I2C
sudo raspi-config nonint do_camera 0
sudo raspi-config nonint do_i2c 0
```

### Step 2: Configuration

For each edge node:

```bash
cd ~/river_monitoring

# Create .env file
nano .env

# Key configurations:
# SERVER_URL=http://<pi5-ip>:5000
# EDGE_NODE_ID=pi4_edge_01  # Unique for each node
# CAMERA_INDEX=0             # Adjust if multiple cameras
```

### Step 3: Copy Models

```bash
# Copy trained YOLOv8 model
scp best.pt pi@<pi4-ip>:~/river_monitoring/
scp best.onnx pi@<pi4-ip>:~/river_monitoring/  # Optional ONNX format
```

### Step 4: Test Locally

```bash
# SSH to Pi4
ssh pi@<pi4-ip>

# Activate environment
source ~/river_monitoring/venv/bin/activate

# Test MQTT sensor data from ESP32
python3 -c "
import paho.mqtt.subscribe as subscribe
msg = subscribe.simple('river/sensors', hostname='localhost', msg_count=1)
print('Received:', msg.payload.decode())
"

# Test camera
raspistill -o test.jpg && echo 'Camera OK'

# Test model
python3 -c "
from pi4_edge_node.trash_detector import TrashDetector
detector = TrashDetector()
print('Model loaded successfully')
"
```

### Step 5: Start Edge Node

```bash
# Manual start (for testing)
cd ~/river_monitoring
source venv/bin/activate
python main_edge.py

# Wait for registration message:
# "Node pi4_edge_01 registered successfully"
```

## 📊 Dashboard Deployment

### Option 1: Docker Container

```bash
# On Pi5 or deployment server
docker run -d \
  -p 3000:3000 \
  -e REACT_APP_API_URL=http://<pi5-ip>:5000 \
  --name river-dashboard \
  river-dashboard:latest
```

### Option 2: Nginx Reverse Proxy

```bash
# Install nginx
sudo apt install -y nginx

# Create config
sudo nano /etc/nginx/sites-available/river

# Add:
server {
    listen 80;
    server_name _;

    # Dashboard
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # API
    location /api {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
    }

    # WebSocket
    location /socket.io {
        proxy_pass http://localhost:5000/socket.io;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

# Enable and test
sudo ln -s /etc/nginx/sites-available/river /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Option 3: PM2 (Node.js)

```bash
# Install PM2
npm install -g pm2

# Create ecosystem config
cat > ecosystem.config.js <<EOF
module.exports = {
  apps: [{
    name: 'river-dashboard',
    script: 'npm',
    args: 'start',
    cwd: '/home/pi/river_monitoring/dashboard/frontend',
    instances: 1,
    env: {
      NODE_ENV: 'production',
      PORT: 3000,
      REACT_APP_API_URL: 'http://localhost:5000'
    }
  }]
};
EOF

# Start
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## 📈 Performance Optimization

### CPU Optimization

```bash
# Check CPU frequency scaling
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Set to performance mode
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

### Memory Optimization

```bash
# Monitor memory
free -h

# Reduce swap usage (if needed)
sudo swapon -s
sudo swapoff /swapfile  # If too slow
```

### Network Optimization

```bash
# Check network stats
ethtool eth0

# Enable jumbo frames (if supported)
sudo ip link set eth0 mtu 9000
```

## 🔍 Monitoring & Logging

### System Health

```bash
# CPU/Memory monitoring
watch -n 1 'ps aux | grep python | grep -v grep'

# Disk usage
df -h

# Temperature
vcgencmd measure_temp
```

### Application Logs

```bash
# Pi4 edge node
tail -100f ~/river_monitoring/edge_node.log | grep ERROR

# Pi5 central node
sudo journalctl -u river-central -n 100 -o short

# Dashboard errors (if npm)
pm2 logs river-dashboard
```

### Remote Monitoring

```bash
# Set up syslog-ng for centralized logging
sudo apt install -y syslog-ng

# Configure to forward to central server
# /etc/syslog-ng/syslog-ng.conf
```

## 🔄 Maintenance Schedule

### Daily
- [ ] Check system status dashboard
- [ ] Monitor for alerts
- [ ] Verify all nodes online

### Weekly
- [ ] Review performance metrics
- [ ] Check disk space usage
- [ ] Review error logs

### Monthly
- [ ] Update packages
- [ ] Backup configurations
- [ ] Backup collected data
- [ ] Review anomaly trends
- [ ] Clean up old logs

### Quarterly
- [ ] Hardware inspection
- [ ] Sensor calibration check
- [ ] Model performance review
- [ ] Security audit

## 🚨 Troubleshooting

### Node Not Registering

```bash
# Check connectivity
curl -v http://<pi5-ip>:5000/api/health

# Check edge node logs
tail -f edge_node.log | grep -i error

# Restart edge node
pkill -f main_edge.py
source venv/bin/activate
python main_edge.py
```

### High Latency

```bash
# Check network
ping -c 10 <pi5-ip>
traceroute <pi5-ip>

# Check disk I/O
iostat -x 1

# Reduce detection frequency
# In main_edge.py: self.detection_interval = 5
```

### Memory Issues

```bash
# Check available memory
free -h

# Identify memory hogs
ps aux --sort=-%mem | head -10

# Reduce model precision
# Use ONNX quantized model instead
```

### WebSocket Connection Issues

```bash
# Check if socket.io is working
curl -i http://localhost:5000/socket.io/?EIO=4&transport=polling

# Enable Socket.IO debug logs
# In server.py: socketio = SocketIO(..., logger=True, engineio_logger=True)
```

## 📝 Data Backup & Recovery

### Backup Strategy

```bash
# Daily automated backup
crontab -e

# Add line:
0 2 * * * tar -czf /backup/river_$(date +\%Y\%m\%d).tar.gz /home/pi/river_monitoring

# Verify backups
ls -lh /backup/
```

### Recovery

```bash
# Restore from backup
tar -xzf /backup/river_20240115.tar.gz -C /

# Verify restored files
ls -la ~/river_monitoring/
```

## 🔐 Security Hardening

### SSH Security

```bash
# Generate SSH keys (client side)
ssh-keygen -t ed25519

# Disable password auth
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no

# Reload SSH
sudo systemctl restart ssh
```

### Firewall Rules

```bash
# UFW setup
sudo ufw enable
sudo ufw allow 22/tcp
sudo ufw allow 5000/tcp   # API
sudo ufw allow 3000/tcp   # Dashboard
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS

# Show rules
sudo ufw status numbered
```

### API Rate Limiting

```bash
# In server.py, add:
from flask_limiter import Limiter
limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route('/api/submit_data', methods=['POST'])
@limiter.limit("10/minute")
def submit_data():
    ...
```

## 📞 Emergency Procedures

### System Crash

```bash
# If Pi5 crashes:
1. Power cycle: unplug 30s, reconnect
2. SSH in when back up
3. Check logs: sudo journalctl -p 3 -xb
4. Restart service: sudo systemctl restart river-central

# If Pi4 crashes:
1. Power cycle
2. Check connectivity from Pi5
3. Monitor: watch -n 1 curl http://<pi4-ip>:5000/api/health
```

### Data Loss

```bash
# Restore from backup
tar -xzf latest_backup.tar.gz

# Restart services
docker-compose restart
```

### Network Isolation

```bash
# Nodes can work independently
# Each Pi4 will buffer data locally
# Resume communication when network restored
```

---

**Last Updated**: February 24, 2026
