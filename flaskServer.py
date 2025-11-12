#!/usr/bin/python3

# Rewritten with Flask: MJPEG streaming server using Picamera2.
# Dynamically detects max supported video size from camera sensor modes.
# Added: Configuration page (/config.html) to set rotation; saves/loads from 'config.ini' using ConfigParser.
# On startup, loads rotation from file (default 270 if missing).
# Capture photo button on index page; fetches /capture.jpg and displays below stream.
# Routes: / (redirect to /index.html), /index.html (HTML page with capture button), /full.html (fullscreen stream page), /stream.mjpg (multipart stream), /capture.jpg (single JPEG capture), /config.html (config form), /save_config (POST to save rotation).
# Supports rotation via libcamera Transform.
# Fix: Simplified get_max_video_size() to handle SensorMode dict structure; removed format description access to avoid AttributeError (format is str, not dict with 'description').

import io
import logging
import configparser
import os
from threading import Condition
from flask import Flask, Response, redirect, request, render_template_string
from io import BytesIO

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from libcamera import Transform  # Requires python3-libcamera; install if missing

os.environ["LIBCAMERA_LOG_LEVELS"] = "3"
CONFIG_FILE = 'config.ini'  # File to save/load rotation (INI format)


def load_config():
    """Load rotation from config file; default to 270."""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if config.has_section('camera') and config.has_option('camera', 'rotation'):
            return config.getint('camera', 'rotation', fallback=270)
    else:
        raise FileNotFoundError(f"Config file '{CONFIG_FILE}' not found; using default rotation 270")
    return 270


def save_config(rotation):
    """Save rotation to config file."""
    config = configparser.ConfigParser()
    config['camera'] = {'rotation': str(rotation)}
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)
    return True


# Load rotation from config
ROTATION = load_config()


def get_max_video_size(picam2):
    """Dynamically find the largest sensor mode size (suitable for video)."""
    max_size = (0, 0)
    for mode in picam2.sensor_modes:
        size = mode['size']
        area = size[0] * size[1]
        if area > max_size[0] * max_size[1]:
            max_size = size
    return max_size


# Initialize camera early to query modes
picam2_temp = Picamera2()
NATIVE_SIZE = get_max_video_size(picam2_temp)
picam2_temp.close()  # Clean up temp instance

# Determine output dimensions (swap for 90/270)
if ROTATION in (90, 270):
    WIDTH, HEIGHT = NATIVE_SIZE[1], NATIVE_SIZE[0]
else:
    WIDTH, HEIGHT = NATIVE_SIZE

# Create appropriate Transform
if ROTATION == 0:
    transform = Transform()
elif ROTATION == 180:
    transform = Transform(hflip=1, vflip=1)
elif ROTATION == 90:
    transform = Transform(vflip=1)
elif ROTATION == 270:
    transform = Transform(hflip=1)
else:
    raise ValueError("Unsupported rotation; use 0, 90, 180, or 270")

PAGE = f"""\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo (Rotated {ROTATION}°)</h1>
<img src="/stream.mjpg" width="{WIDTH/8}" height="{HEIGHT/8}" />
<p><a href="/full.html">Go to Fullscreen View</a> | <a href="/config.html">Configure Rotation</a></p>
<button id="captureBtn">Capture Photo</button>
<img id="photo" style="display: none; width: {WIDTH/8}px; height: {HEIGHT/8}px; margin-top: 10px;" />
<script>
document.getElementById('captureBtn').onclick = function() {{
    const photoImg = document.getElementById('photo');
    photoImg.src = '/capture.jpg?' + Date.now();
    photoImg.style.display = 'block';
}};
</script>
</body>
</html>
"""

FULL_PAGE = f"""\
<html>
<head>
<title>Picamera2 Fullscreen Stream (Rotated {ROTATION}°)</title>
<style>
body {{ margin: 0; padding: 0; background: black; overflow: hidden; }}
img {{ width: 100vw; height: 100vh; object-fit: contain; display: block; }}
#controls {{ position: fixed; top: 10px; right: 10px; z-index: 1; }}
button {{ padding: 10px; background: rgba(255,255,255,0.8); border: none; cursor: pointer; }}
</style>
</head>
<body>
<img id="stream" src="/stream.mjpg" />
<div id="controls">
<button onclick="toggleFullscreen()">Fullscreen</button>
<button onclick="window.location.href='/'">Back to Index</button>
</div>
<script>
function toggleFullscreen() {{
    const elem = document.getElementById('stream');
    if (!document.fullscreenElement) {{
        elem.requestFullscreen().catch(err => console.log('Fullscreen failed:', err));
    }} else {{
        document.exitFullscreen();
    }}
}}
</script>
</body>
</html>
"""

CONFIG_PAGE = f"""\
<html>
<head>
<title>Configure Rotation</title>
</head>
<body>
<h1>Camera Configuration</h1>
<form method="POST" action="/save_config">
    <label for="ISP Config">ISP Config</label>
    ftp-username: <input type="text" name="ftp-username" value="username"><br>
    ftp-password: <input type="text" name="ftp-password" value="password"><br>
    ftp-destinatin: <input type="text" name="ftp-destination" value="ftp_destination_list"><br>
    <label for="Camera Config">Camera Config</label>
    time_berfore_image (secods): <br>
    <label for="rotation">Rotation (degrees):</label>
    <select id="rotation" name="rotation">
        <option value="0" " + ('selected' if {ROTATION} == 0 else '') + ">0</option>
        <option value="90" " + ('selected' if {ROTATION} == 90 else '') + ">90</option>
        <option value="180" " + ('selected' if {ROTATION} == 180 else '') + ">180</option>
        <option value="270" " + ('selected' if {ROTATION} == 270 else '') + ">270</option>
    </select>
    <br><br>
    <button type="submit">Save Configuration</button>
</form>
<p><a href="/">Back to Stream</a></p>
<script>
if (window.location.search.includes('saved=1')) {{
    alert('Configuration saved! Restart the server to apply changes.');
}}
</script>
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            logging.debug(f"New frame written: {len(buf)} bytes")
            self.condition.notify_all()


# Flask app setup
app = Flask(__name__)

# Global output instance
output = StreamingOutput()


@app.route('/')
def index_redirect():
    return redirect('/index.html', code=301)


@app.route('/index.html')
def index():
    return PAGE


@app.route('/full.html')
def full():
    return FULL_PAGE


@app.route('/config.html')
def config():
    # return ("HI")
    return render_template_string(CONFIG_PAGE)


@app.route('/save_config', methods=['POST'])
def save_config_route():
    rotation = int(request.form['rotation'])
    if rotation in (0, 90, 180, 270):
        save_config(rotation)
        return redirect('/config.html?saved=1')
    else:
        return "Invalid rotation", 400


def gen_frames():
    """Generator for streaming frames as multipart/x-mixed-replace."""
    while True:
        with output.condition:
            output.condition.wait()
            frame = output.frame
        content_length = b'Content-Length: ' + str(len(frame)).encode('utf-8') + b'\r\n\r\n'
        yield (b'--FRAME\r\n'
               b'Content-Type: image/jpeg\r\n'
               + content_length
               + frame + b'\r\n')


@app.route('/stream.mjpg')
def stream():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=FRAME',
                    headers={'Age': 0,
                             'Cache-Control': 'no-cache, private',
                             'Pragma': 'no-cache'})


@app.route('/capture.jpg')
def capture_photo():
    """Capture a single high-quality JPEG still from the camera."""
    photo_buffer = BytesIO()
    picam2.capture_file(photo_buffer, encoder=JpegEncoder(q=95))  # Higher quality for stills
    photo_buffer.seek(0)
    return Response(photo_buffer.getvalue(), mimetype='image/jpeg')


if __name__ == '__main__':
    # Configure camera with detected max size
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (WIDTH, HEIGHT)},
        transform=transform
    )
    picam2.configure(config)

    # Start recording to output
    picam2.start_recording(JpegEncoder(q=85), FileOutput(output))

    logging.basicConfig(level=logging.DEBUG)

    print(f"Loaded rotation from config: {ROTATION}°")
    print(f"Detected max native size: {NATIVE_SIZE}")
    print(f"Server starting on http://0.0.0.0:8000 (local: http://localhost:8000)")
    print(f"Streaming rotated {ROTATION}° video at {WIDTH}x{HEIGHT}")
    print("New: Fullscreen view at /full.html")
    print("Capture: Button on index page saves/displays latest photo")
    print("Config: Set rotation at /config.html (restart server to apply)")

    try:
        app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False)
    finally:
        picam2.stop_recording()
