import cv2, os, glob, threading, time, subprocess, sys
import numpy as np
from datetime import datetime
from flask import Flask, Response, request, jsonify, send_from_directory
from functools import wraps

# =====================================================
#                     SETTINGS
# =====================================================
WIDTH, HEIGHT, FPS = 640, 480, 15
REC_DIR = os.path.expanduser("~/cctv/recordings")
MODEL_DIR = os.path.expanduser("~/cctv/models")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

# ---- Web page login ----
AUTH_USERNAME = "probots"
AUTH_PASSWORD = "Probots@1"      # change this to your own password

# ---- RTSP / MediaMTX login (must match mediamtx.yml, set up in Part 2) ----
RTSP_USERNAME = "probots"
RTSP_PASSWORD = "Probots@1"      # change this to your own password

ENABLE_RTSP = True              # MediaMTX must already be running before you start this script
RTSP_RETRY_SECONDS = 10

DETECT_EVERY_N_FRAMES = 6
CONFIDENCE_THRESHOLD = 0.4
SNAPSHOT_COOLDOWN = 10

STRIP_HEIGHT = 24
CLEAR_COLOR = (0, 0, 255)       # RED  = nobody detected here
PERSON_COLOR = (255, 0, 0)      # BLUE = person detected here
STRIPE_PERIOD = 40
STRIPE_SPEED = 3
TOTAL_HEIGHT = HEIGHT + STRIP_HEIGHT

# Every camera you want running, all the time. Add more entries here if needed.
CAMERAS = [
    {"id": "cam1", "label": "USB Cam (video0)", "type": "usb", "src": 0, "rtsp": "stream1"},
    {"id": "cam2", "label": "YJX-C5 (video2)",  "type": "usb", "src": 2, "rtsp": "stream2"},
    # {"id": "cam3", "label": "Store Front Door", "type": "ip",
    #  "src": "rtsp://admin:yourpassword@192.168.1.50:554/stream1", "rtsp": "stream3"},
]
# =====================================================

os.makedirs(REC_DIR, exist_ok=True)
print(f"[DEBUG] Recordings folder ready: {REC_DIR}")
print(f"[DEBUG] Web port: {PORT}, RTSP enabled: {ENABLE_RTSP}")

PROTOTXT = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
MODEL = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

print(f"[DEBUG] Loading MobileNet-SSD model from {MODEL_DIR} ...")
if not os.path.exists(PROTOTXT) or not os.path.exists(MODEL):
    print(f"[ERROR] Model files missing! Expected:\n  {PROTOTXT}\n  {MODEL}")
    sys.exit(1)

net = cv2.dnn.readNetFromCaffe(PROTOTXT, MODEL)
print("[DEBUG] MobileNet-SSD model loaded successfully.")

CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
           "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
           "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"]
PERSON_LABEL = "person"
VEHICLE_LABELS = {"car", "bus", "motorbike", "bicycle"}
RELEVANT_LABELS = VEHICLE_LABELS | {PERSON_LABEL}

model_lock = threading.Lock()

def detect_objects(frame):
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
    with model_lock:
        net.setInput(blob)
        detections = net.forward()
    results = []
    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence < CONFIDENCE_THRESHOLD:
            continue
        idx = int(detections[0, 0, i, 1])
        if idx < 0 or idx >= len(CLASSES):
            continue
        label = CLASSES[idx]
        if label not in RELEVANT_LABELS:
            continue
        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
        x1, y1, x2, y2 = box.astype("int")
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)
        results.append((label, float(confidence), x1, y1, x2, y2))
    return results

def draw_detections(frame, detections):
    for (label, conf, x1, y1, x2, y2) in detections:
        color = (0, 255, 0) if label == PERSON_LABEL else (0, 165, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{label}: {conf*100:.0f}%", (x1, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

def build_status_strip(width, detections, counter):
    strip = np.empty((STRIP_HEIGHT, width, 3), dtype=np.uint8)
    strip[:] = CLEAR_COLOR
    for (label, conf, x1, y1, x2, y2) in detections:
        if label == PERSON_LABEL:
            strip[:, x1:x2 + 1] = PERSON_COLOR
    cols = np.arange(width)
    offset = (counter * STRIPE_SPEED) % STRIPE_PERIOD
    stripe_mask = ((cols - offset) % STRIPE_PERIOD) < (STRIPE_PERIOD // 2)
    strip[:, stripe_mask] = ((strip[:, stripe_mask].astype(np.uint16) * 60) // 100 + 102).astype(np.uint8)
    return strip

def start_ffmpeg_pusher(rtsp_name):
    url = f"rtsp://{RTSP_USERNAME}:{RTSP_PASSWORD}@localhost:8554/{rtsp_name}"
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pixel_format", "bgr24",
        "-video_size", f"{WIDTH}x{TOTAL_HEIGHT}", "-framerate", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-f", "rtsp", url,
    ]
    print(f"[DEBUG] [{rtsp_name}] Starting ffmpeg RTSP pusher.")
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

def open_source(cam):
    print(f"[DEBUG] [{cam['id']}] Opening {cam['type']}:{cam['src']} ...")
    if cam["type"] == "usb":
        cap = cv2.VideoCapture(cam["src"], cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    else:
        cap = cv2.VideoCapture(cam["src"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if cap.isOpened():
        print(f"[DEBUG] [{cam['id']}] Opened successfully.")
    else:
        print(f"[ERROR] [{cam['id']}] Failed to open.")
    return cap

# ---- Shared state ----
app = Flask(__name__)

def check_auth(username, password):
    return username == AUTH_USERNAME and password == AUTH_PASSWORD

def authenticate():
    return Response(
        "Login required to view this camera system.", 401,
        {"WWW-Authenticate": 'Basic realm="CCTV Login"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

select_lock = threading.Lock()
selected_camera_id = CAMERAS[0]["id"]

cameras_state = {}
for cam in CAMERAS:
    cameras_state[cam["id"]] = {
        "lock": threading.Lock(),
        "cap": None,
        "latest_frame": None,
        "recording": False,
        "writer": None,
        "record_filename": None,
        "frame_counter": 0,
        "last_detections": [],
        "last_snapshot_time": 0,
    }

def camera_worker(cam):
    cid = cam["id"]
    st = cameras_state[cid]
    st["cap"] = open_source(cam)

    ffmpeg_proc = None
    last_rtsp_attempt = 0
    if ENABLE_RTSP:
        ffmpeg_proc = start_ffmpeg_pusher(cam["rtsp"])
        last_rtsp_attempt = time.time()

    while True:
        cap = st["cap"]
        if cap is None or not cap.isOpened():
            print(f"[WARN] [{cid}] Camera not open, retrying in 2s...")
            time.sleep(2)
            st["cap"] = open_source(cam)
            continue

        ok, frame = cap.read()
        if not ok:
            print(f"[WARN] [{cid}] Failed to read frame, reopening...")
            cap.release()
            time.sleep(1)
            st["cap"] = open_source(cam)
            continue

        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        st["frame_counter"] += 1
        counter = st["frame_counter"]

        if counter % DETECT_EVERY_N_FRAMES == 0:
            detections = detect_objects(frame)
            st["last_detections"] = detections
            if detections:
                found = ", ".join(f"{d[0]}({d[1]*100:.0f}%)" for d in detections)
                print(f"[DEBUG] [{cid}] Frame #{counter}: detected {found}")
        else:
            detections = st["last_detections"]

        draw_detections(frame, detections)
        cv2.putText(frame, f"{cam['label']}  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        strip = build_status_strip(WIDTH, detections, counter)
        frame = np.vstack([frame, strip])

        if any(d[0] == PERSON_LABEL for d in detections):
            now = time.time()
            if now - st["last_snapshot_time"] > SNAPSHOT_COOLDOWN:
                name = datetime.now().strftime(f"person_{cid}_%Y%m%d_%H%M%S.jpg")
                cv2.imwrite(os.path.join(REC_DIR, name), frame)
                st["last_snapshot_time"] = now
                print(f"[DEBUG] [{cid}] Auto-snapshot saved: {name}")

        with st["lock"]:
            st["latest_frame"] = frame.copy()
            if st["recording"] and st["writer"] is not None:
                st["writer"].write(frame)

        if ENABLE_RTSP:
            try:
                if ffmpeg_proc is not None:
                    ffmpeg_proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, ValueError, OSError):
                try:
                    ffmpeg_proc.kill(); ffmpeg_proc.wait(timeout=2)
                except Exception:
                    pass
                ffmpeg_proc = None
            if ffmpeg_proc is None and time.time() - last_rtsp_attempt > RTSP_RETRY_SECONDS:
                print(f"[WARN] [{cid}] RTSP pusher down, retrying...")
                last_rtsp_attempt = time.time()
                ffmpeg_proc = start_ffmpeg_pusher(cam["rtsp"])

        time.sleep(1.0 / FPS)

# =====================================================
#                   WEB ROUTES
# =====================================================
@app.route("/")
@requires_auth
def index():
    options = "".join(
        f'<option value="{c["id"]}" {"selected" if c["id"] == selected_camera_id else ""}>{c["label"]}</option>'
        for c in CAMERAS
    )
    return f"""
    <html><body style="font-family:sans-serif;background:#111;color:#eee;text-align:center">
    <h2>Store CCTV - Person and Vehicle Detection</h2>
    <img src="/video_feed" style="max-width:90%;border:2px solid #444">
    <p style="font-size:14px">Line under the video:
       <span style="color:#f44">RED = clear</span> |
       <span style="color:#48f">BLUE = person detected at that position</span></p>
    <label>Camera: </label>
    <select id="camSelect" onchange="switchCam()">{options}</select>
    <br><br>
    <button onclick="takePhoto()">Take Photo</button>
    <button id="recBtn" onclick="toggleRecord()">Start Recording</button>
    <br><br>
    <a style="color:#8cf" href="/recordings">View saved photos and recordings</a>
    <p id="status" style="color:#8f8"></p>
    <script>
        let recording = false;
        function takePhoto() {{
            fetch('/snapshot').then(r => r.json()).then(d => {{
                document.getElementById('status').innerText = 'Saved: ' + d.filename;
            }});
        }}
        function toggleRecord() {{
            let url = recording ? '/stop_recording' : '/start_recording';
            fetch(url).then(r => r.json()).then(d => {{
                recording = !recording;
                document.getElementById('recBtn').innerText = recording ? 'Stop Recording' : 'Start Recording';
                document.getElementById('status').innerText = d.message;
            }});
        }}
        function switchCam() {{
            let cid = document.getElementById('camSelect').value;
            fetch('/switch_camera?id=' + cid).then(r => r.json()).then(d => {{
                document.getElementById('status').innerText = d.message;
                document.getElementById('video').src = '/video_feed?_=' + Date.now();
            }});
        }}
    </script>
    </body></html>
    """.replace('<img src="/video_feed"', '<img id="video" src="/video_feed"')

def mjpeg_generator():
    while True:
        cid = selected_camera_id
        st = cameras_state[cid]
        with st["lock"]:
            frame = st["latest_frame"]
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(1.0 / FPS)

@app.route("/video_feed")
@requires_auth
def video_feed():
    return Response(mjpeg_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/switch_camera")
@requires_auth
def switch_camera():
    global selected_camera_id
    cid = request.args.get("id", CAMERAS[0]["id"])
    if cid not in cameras_state:
        return jsonify({"message": f"ERROR: unknown camera {cid}"})
    with select_lock:
        selected_camera_id = cid
    print(f"[DEBUG] Web page now viewing: {cid}")
    return jsonify({"message": f"Now viewing {cid}"})

@app.route("/snapshot")
@requires_auth
def snapshot():
    st = cameras_state[selected_camera_id]
    with st["lock"]:
        frame = st["latest_frame"]
    if frame is None:
        return jsonify({"filename": "ERROR: no frame available"})
    name = datetime.now().strftime(f"photo_{selected_camera_id}_%Y%m%d_%H%M%S.jpg")
    cv2.imwrite(os.path.join(REC_DIR, name), frame)
    print(f"[DEBUG] Manual snapshot taken: {name}")
    return jsonify({"filename": name})

@app.route("/start_recording")
@requires_auth
def start_recording():
    st = cameras_state[selected_camera_id]
    with st["lock"]:
        if st["recording"]:
            return jsonify({"message": "Already recording"})
        frame = st["latest_frame"]
        if frame is None:
            return jsonify({"message": "ERROR: camera not ready yet"})
        name = datetime.now().strftime(f"clip_{selected_camera_id}_%Y%m%d_%H%M%S.mp4")
        h, w = frame.shape[:2]
        st["writer"] = cv2.VideoWriter(os.path.join(REC_DIR, name),
                                       cv2.VideoWriter_fourcc(*"XVID"), FPS, (w, h))
        st["recording"] = True
        st["record_filename"] = name
        print(f"[DEBUG] Recording started: {name}")
        return jsonify({"message": f"Recording started: {name}"})

@app.route("/stop_recording")
@requires_auth
def stop_recording():
    st = cameras_state[selected_camera_id]
    with st["lock"]:
        if not st["recording"]:
            return jsonify({"message": "Not currently recording"})
        st["writer"].release()
        name = st["record_filename"]
        st["writer"] = None
        st["recording"] = False
        st["record_filename"] = None
        print(f"[DEBUG] Recording stopped and saved: {name}")
        return jsonify({"message": f"Recording saved: {name}"})

@app.route("/recordings")
@requires_auth
def recordings_list():
    files = sorted(os.listdir(REC_DIR), reverse=True)
    links = "".join(f'<li><a style="color:#8cf" href="/recordings/{f}">{f}</a></li>' for f in files)
    return f"""
    <html><body style="font-family:sans-serif;background:#111;color:#eee">
    <h2>Saved Photos and Recordings</h2>
    <ul>{links}</ul>
    <a style="color:#8cf" href="/">Back to live view</a>
    </body></html>
    """

@app.route("/recordings/<path:name>")
@requires_auth
def get_recording(name):
    return send_from_directory(REC_DIR, name, as_attachment=True)

if __name__ == "__main__":
    print("[DEBUG] Starting one capture thread per camera...")
    for cam in CAMERAS:
        threading.Thread(target=camera_worker, args=(cam,), daemon=True).start()
    print(f"[DEBUG] Starting web server on port {PORT} ...")
    app.run(host="0.0.0.0", port=PORT, threaded=True)