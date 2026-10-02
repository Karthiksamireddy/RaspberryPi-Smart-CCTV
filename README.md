# RaspberryPi-Smart-CCTV

An automated multi-camera surveillance and object detection system built for the Raspberry Pi. This project implements localized object detection, live web management, snapshots, MP4 recording, and authenticated RTSP streaming without relying on external cloud APIs. Powered by a local MobileNet-SSD Caffe model, MediaMTX, and FFmpeg, the system runs completely headlessly on startup using systemd background services.

---

## 📹 Video Demonstration

Check out the 37-second demonstration showing real-time multi-camera detection, web controller actions, and live streaming:

![System Demo](assets/demo.gif)

---


## Features

* **Real-Time Local Edge Detection:** Detects persons, cars, buses, motorbikes, and bicycles on-device using a MobileNet-SSD Caffe model.
* **Multi-Camera Support:** Processes multiple USB webcam streams simultaneously (`/dev/video0` and `/dev/video2`) using threaded workers.
* **Dynamic Motion Visualizer:** Renders a dynamic bottom status strip that changes from red to blue across coordinates where a person is detected.
* **Automated & Manual Recording:**
  * **Auto Snapshots:** Automatically saves time-stamped images to disk when a person is detected (with a 10-second cooldown).
  * **Web Controls:** Manually trigger photos or toggle MP4 video clip recordings directly from the browser dashboard.
* **Dual-Protocol Streaming:**
  * **HTTP/MJPEG Dashboard:** Access live video feeds, camera switches, and file downloads over an authenticated web interface.
  * **RTSP Feeds:** Pushes low-latency H.264 video streams to MediaMTX via FFmpeg.
* **Zero-Terminal Boot Operation:** Configured with Linux `systemd` background services to run automatically on power-on without requiring SSH or manual terminal input.

---

## Hardware Requirements

* **Raspberry Pi 3** (or newer, connected to external power supply)
* **2x USB Web Cameras** (for multi-angle capturing)
* **MicroSD Card** (with Raspberry Pi OS installed)
* **Laptop/PC** (for initial setup, viewing web feeds, or playing RTSP streams)

---

## Hardware Setup

1. Connect both USB cameras into the USB ports of the Raspberry Pi (`/dev/video0` and `/dev/video2`).
2. Position the cameras to cover the designated monitoring areas.
3. Ensure the Raspberry Pi is powered using a stable 5V power supply.
4. Connect the Pi to your local network or Wi-Fi hotspot.

---

## Software Setup

1. Install Raspberry Pi OS using the Raspberry Pi Imager.
2. Open the terminal on your Raspberry Pi and install the required dependencies:

<pre><code>sudo apt update
sudo apt install -y python3-opencv python3-flask python3-numpy ffmpeg</code></pre>

3. Setup MediaMTX RTSP Server:
Download MediaMTX and configure `~/mediamtx.yml` with internal authentication by adding the following settings:

<pre><code>authMethod: internal

authInternalUsers:
  - user: &lt;YOUR_RTSP_USERNAME&gt;
    pass: &lt;YOUR_RTSP_PASSWORD&gt;
    ips: []
    permissions:
      - action: publish
        path:
      - action: read
        path:
      - action: playback
        path:</code></pre>

4. Restart MediaMTX to save changes:

<pre><code>sudo systemctl restart mediamtx</code></pre>

---

## Installation & Usage

1. Clone this repository or copy the Python script `SELF_BUILD_CCTV.py` to your Raspberry Pi:

<pre><code>git clone https://github.com/YOUR_GITHUB_USERNAME/RaspberryPi-Smart-CCTV.git</code></pre>

2. Place the required Caffe model files inside `~/cctv/models/`:
* `MobileNetSSD_deploy.prototxt`
* `MobileNetSSD_deploy.caffemodel`

3. Edit parameters in `SELF_BUILD_CCTV.py` to set your credentials:

<pre><code>PORT = 5000                          # Web interface port
AUTH_USERNAME = "&lt;YOUR_WEB_USER&gt;"    # Web login username
AUTH_PASSWORD = "&lt;YOUR_WEB_PASS&gt;"    # Web login password
RTSP_USERNAME = "&lt;YOUR_RTSP_USER&gt;"   # MediaMTX RTSP username
RTSP_PASSWORD = "&lt;YOUR_RTSP_PASS&gt;"   # MediaMTX RTSP password</code></pre>

4. Run the script manually to test:

<pre><code>python3 SELF_BUILD_CCTV.py 5000</code></pre>

5. Configure Auto-Boot (`systemd`):
Create `/etc/systemd/system/cctv.service`:

<pre><code>[Unit]
Description=CCTV Multi-Camera Detection and Web Server
After=network.target mediamtx.service

[Service]
Type=simple
User=&lt;YOUR_PI_USER&gt;
WorkingDirectory=/home/&lt;YOUR_PI_USER&gt;/cctv
ExecStart=/usr/bin/python3 /home/&lt;YOUR_PI_USER&gt;/cctv/SELF_BUILD_CCTV.py 5000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target</code></pre>

Enable service:

<pre><code>sudo systemctl daemon-reload
sudo systemctl enable cctv.service
sudo systemctl start cctv.service</code></pre>

---

## Troubleshooting

* **Model files missing error:** Verify that `MobileNetSSD_deploy.prototxt` and `MobileNetSSD_deploy.caffemodel` exist inside `~/cctv/models/`.
* **Camera not found or failed to read frame:** Check USB connections with `ls /dev/video*`. Ensure `CAMERAS` source indices in the script match your connected USB video nodes (`/dev/video0`, `/dev/video2`).
* **RTSP stream fails to load in VLC:** Verify MediaMTX status with `sudo systemctl status mediamtx`. Ensure RTSP credentials in `SELF_BUILD_CCTV.py` match `~/mediamtx.yml`.
* **Web authentication failed:** Verify HTTP Basic Auth username and password entered in the browser match `AUTH_USERNAME` and `AUTH_PASSWORD` set in `SELF_BUILD_CCTV.py`.
* **Service crashes on boot:** Check live system logs using `sudo journalctl -u cctv.service -f`.

---

## Advantages & Limitations

| Advantages | Limitations |
| :--- | :--- |
| 100% local processing; no internet connection required | High CPU usage on Raspberry Pi during multi-stream detection |
| Zero API fees or usage limits | Frame rate limited to ~15 FPS for stability |
| Dual HTTP and RTSP streaming support | MobileNet-SSD accuracy depends on ambient lighting conditions |
| Automated head-less startup on power-on | Requires physical USB connection for cameras |
| Built-in web dashboard for manual recording & snapshots | Storage capacity constrained by MicroSD size |



