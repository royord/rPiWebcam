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
import time
from threading import Condition, Thread
from flask import Flask, Response, redirect, request, render_template_string
from io import BytesIO
from flask import send_file
import sys
import netifaces as ni
import lib.file_transfer as ft

from PIL import Image, ImageDraw, ImageFont
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from libcamera import Transform  # Requires python3-libcamera; install if missing

os.environ["LIBCAMERA_LOG_LEVELS"] = "3"
CONFIG_FILE = 'cam_config.cfg'  # File to save/load rotation (INI format)

default_config = {
    'ftp-mode': 'sftp',
    'ftp-server': 'ftp_server',
    'ftp-port': '22',
    'ftp-username': 'username',
    'ftp-password': 'password',
    'ftp-destination': 'ftp_destination_list',
    'camera_name': 'camera_name',
    'rotation': '0',
    'time_before_image': '10',
    'time_before_first_image': '120',
    'output_width': None,
    'output_height': None,
    'output_extension': 'extension',
    'output_quality':'100',
    'output_filetype':'jpg',
    'output_max_filesize_kb':0,
    'output_folder':'image_dir',
    'embed_timestamp': 'embed_timestamp',
    'file_name': 'file_name',
    'text_size': '18',
    'text_color': 'silver',
    'text_background': 'black',
    'camera_timezone': 'camera_timezone',
    'camera_daylight_savings': 'camera_daylight_savings',
    'camera_port': '8000',
    'camera_url': 'camera_urls'
}

def load_config():
    """Load rotation from config file; default to 270."""
    configs = {}

    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if config.has_section('camera') and config.has_option('camera', 'rotation'):
            for key, value in config.items('camera'):
                configs[key] = config.get('camera', key)
                # print("Current config: ", key, " = ", value)

    for key, value in default_config.items():
        if key not in globals():
            globals()[key] = value
            configs[key] = value
            save_config(configs)

    globals().update(configs)

    # Validate critical integer fields; default to safe values if corrupted
    for key in ('camera_port', 'time_before_image', 'time_before_first_image', 'output_width', 'output_height', 'output_max_filesize_kb'):
        val = globals().get(key)
        try:
            int(val)
        except (ValueError, TypeError):
            defaults = {'camera_port': '8000', 'output_width': '0', 'output_height': '0', 'output_max_filesize_kb': '0', 'time_before_image': '10', 'time_before_first_image': '120'}
            globals()[key] = defaults.get(key, '0')


def current_time():
    current_time = time.localtime()
    return current_time

def cam_time():
    """
    Time in the following format:
    Sat, 15 Nov 2020 10:43:50

    :return:
    """
    cam_time = time.strftime('%a, %d %b %Y %H:%M:%S', current_time())
    return cam_time

def save_config(rotation):
    """Save rotation to config file."""
    config = configparser.ConfigParser()
    configs = {}
    try:
        for key, value in rotation.items():
            # Convert 'true'/'false' strings to actual booleans for checkbox fields
            if key in ('embed_timestamp', 'camera_daylight_savings'):
                if value == 'true':
                    value = True
                elif value == 'false':
                    value = False
            configs[key] = value
            globals()[key] = value
        globals().update(configs)
        config['camera'] = configs
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)
    except Exception as e:
        print(f"Error saving config: {e}")
        import traceback
        traceback.print_exc()

    # print("--==GLOBALS==--")
    # for key, value in globals().items():
    #     print(key, '::', value)
    # print("--==GLOBALS==--")

    return True

# Load rotation from config
# ROTATION = load_config()
load_config()
# print(globals())
# print("Rotation: ", ROTATION)
try:
    ROTATION = int(globals()['rotation'])
except Exception as e:
    print(e)
    ROTATION = 270

print("Rotation: ", ROTATION)

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

# Set default output dimensions to max sensor size
default_config['output_width'] = str(NATIVE_SIZE[0])
default_config['output_height'] = str(NATIVE_SIZE[1])

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

# Module-level camera instance (initialised in __main__ block)
picam2 = None

PAGE = f"""\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
h1 {{ margin: 0 0 16px; font-size: 20px; color: #333; }}
.stream-box {{ background: #000; border-radius: 8px; overflow: hidden; max-width: 720px; }}
.stream-box img {{ width: 100%; display: block; }}
.controls {{ max-width: 720px; margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
.controls a, .controls button {{
    padding: 8px 16px; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; text-decoration: none; color: #fff;
}}
.controls button {{ background: #007bff; }}
.controls a {{ background: #6c757d; }}
#photo {{ display: none; max-width: 720px; margin-top: 12px; border-radius: 8px; }}
</style>
</head>
<body>
<h1>picamera2 MJPEG Streaming (Rotated {ROTATION}&deg;)</h1>
<div class="stream-box">
    <img src="/stream.mjpg" />
</div>
<div class="controls">
    <button id="captureBtn">Capture Photo</button>
    <button id="captureEmbeddedBtn">Capture with Text</button>
    <a href="/full.html">Fullscreen</a>
    <a href="/config.html">Configure Settings</a>
</div>
<img id="photo" />
<script>
document.getElementById('captureBtn').onclick = function() {{
    const photoImg = document.getElementById('photo');
    photoImg.src = '/capture.jpg?' + Date.now();
    photoImg.style.display = 'block';
}};
document.getElementById('captureEmbeddedBtn').onclick = function() {{
    const photoImg = document.getElementById('photo');
    photoImg.src = '/capture_embedded.jpg?' + Date.now();
    photoImg.style.display = 'block';
}};
if (window.location.search.includes('saved=1')) {{
    alert('Configuration saved!');
}}
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

def generate_config_page():
    def _opt(selected, values):
        """Return 'selected' if value matches."""
        return 'selected' if selected in values else ''

    return f"""\
<html>
<head>
<title>Camera Configuration</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
h1 {{ margin: 0 0 20px; font-size: 22px; color: #333; }}
.two-pane {{ display: flex; gap: 20px; align-items: flex-start; }}
.live-pane {{
    flex: 0 0 640px; position: sticky; top: 20px;
}}
.settings-pane {{
    flex: 1; min-width: 0;
}}
.pane-label {{
    font-size: 13px; font-weight: 600; color: #888; text-transform: uppercase; letter-spacing: 0.5px;
    margin-bottom: 8px;
}}
.tab-btns {{ display: flex; gap: 0; border-bottom: 2px solid #dee2e6; background: #fff; margin-bottom: 20px; }}
.tab-btn {{
    padding: 10px 24px; border: none; background: none; font-size: 15px; cursor: pointer;
    color: #666; border-bottom: 3px solid transparent; margin-bottom: -2px; transition: all .15s;
}}
.tab-btn:hover {{ color: #007bff; }}
.tab-btn.active {{ color: #007bff; border-bottom-color: #007bff; font-weight: 500; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.field {{ margin-bottom: 16px; }}
.field label {{ display: block; font-size: 13px; font-weight: 500; color: #555; margin-bottom: 4px; }}
.field input[type="text"],
.field input[type="password"],
.field input[type="number"],
.field select {{
    width: 100%; max-width: 400px; padding: 8px 12px; border: 1px solid #ced4da; border-radius: 4px;
    font-size: 14px; box-sizing: border-box;
}}
.field input:focus, .field select:focus {{ outline: none; border-color: #007bff; box-shadow: 0 0 0 2px rgba(0,123,255,.15); }}
.field select {{ background: #fff; }}
.field .hint {{ font-size: 12px; color: #888; margin-top: 4px; max-width: 400px; }}
.section-title {{ font-size: 16px; font-weight: 600; color: #333; margin: 24px 0 16px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
.section-title:first-child {{ margin-top: 0; }}
.btn {{
    padding: 8px 20px; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; text-decoration: none;
    display: inline-block;
}}
.btn-primary {{ background: #007bff; color: #fff; }}
.btn-success {{ background: #28a745; color: #fff; }}
.btn-secondary {{ background: #6c757d; color: #fff; text-decoration: none; }}
.btn-group {{ margin-top: 20px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.stream-preview {{ background: #000; border-radius: 8px; overflow: hidden; }}
.stream-preview img {{ width: 100%; display: block; }}
.modal-overlay {{
    display: none; position: fixed; z-index: 999; left: 0; top: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.5);
}}
.modal {{
    background: #fff; margin: 10% auto; padding: 24px; border-radius: 8px;
    width: 90%; max-width: 480px; position: relative;
}}
.modal h2 {{ margin-top: 0; }}
.modal .close {{ position: absolute; top: 8px; right: 16px; font-size: 24px; cursor: pointer; color: #999; }}
.toast {{
    position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%) translateY(20px);
    background: #2d6a4e; color: #fff; padding: 12px 28px; border-radius: 6px;
    font-size: 15px; font-weight: 500; opacity: 0; pointer-events: none;
    transition: opacity .3s, transform .3s; z-index: 1000;
    box-shadow: 0 4px 12px rgba(0,0,0,.25);
}}
.toast.show {{
    opacity: 1; transform: translateX(-50%) translateY(0);
}}
@media (max-width: 900px) {{
    .two-pane {{ flex-direction: column; }}
    .live-pane {{ flex: none; width: 100%; position: static; }}
}}
</style>
</head>
<body>
<h1>Camera Configuration</h1>

<form id="configForm" method="POST" action="/save_config">
    <input type="hidden" name="_active_tab" id="_active_tab" value="camera">

<!-- Two-pane layout -->
<div class="two-pane">

<!-- Left pane: Live View (always visible) -->
<div class="live-pane">
    <div class="pane-label">Live View</div>
    <div class="stream-preview">
        <img src="/stream.mjpg" />
    </div>
    <div class="btn-group">
        <button type="button" class="btn btn-primary" onclick="capturePhoto('/capture.jpg')">Capture Photo</button>
        <button type="button" class="btn btn-primary" onclick="capturePhoto('/capture_embedded.jpg')">Capture with Text</button>
        <a href="/full.html" class="btn btn-secondary">Fullscreen View</a>
    </div>
    <div id="livePhoto" style="display:none; margin-top:16px;">
        <img id="livePhotoImg" style="max-width:100%; border-radius:8px; box-shadow: 0 2px 8px rgba(0,0,0,.15);">
    </div>
    <script>
    function capturePhoto(url) {{
        var img = document.getElementById('livePhotoImg');
        img.src = url + '?' + Date.now();
        document.getElementById('livePhoto').style.display = 'block';
    }}
    </script>
</div>

<!-- Right pane: Settings tabs -->
<div class="settings-pane">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div class="pane-label">Settings</div>
        <button type="button" class="btn btn-primary" id="saveBtn">Save Configuration</button>
    </div>
    <div class="tab-btns">
        <button type="button" class="tab-btn active" onclick="switchTab(event, 'tab-camera')">Camera Settings</button>
        <button type="button" class="tab-btn" onclick="switchTab(event, 'tab-transfer')">Transfer Settings</button>
        <button type="button" class="tab-btn" onclick="switchTab(event, 'tab-system')">System</button>
    </div>
<!-- Tab 2: Camera Settings -->
<div id="tab-camera" class="tab-content active">
    <div class="field">
        <label for="camera_name">Camera Name</label>
        <input type="text" name="camera_name" id="camera_name" value="{globals()['camera_name']}" placeholder="e.g. front_porch">
        <div class="hint">No spaces — use underscores. Used in filenames and embedded text.</div>
    </div>

    <div class="field">
        <label for="rotation">Rotation</label>
        <select name="rotation" id="rotation">
            <option value="0" {_opt(int(globals()['rotation']), [0])}>0&deg;</option>
            <option value="90" {_opt(int(globals()['rotation']), [90])}>90&deg;</option>
            <option value="180" {_opt(int(globals()['rotation']), [180])}>180&deg;</option>
            <option value="270" {_opt(int(globals()['rotation']), [270])}>270&deg;</option>
        </select>
        <div class="hint">Applies immediately.</div>
    </div>

    <div class="field">
        <label for="time_before_first_image">Delay Before First Photo (seconds)</label>
        <input type="number" name="time_before_first_image" id="time_before_first_image" value="{globals()['time_before_first_image']}" min="0">
        <div class="hint">Initial wait before the first scheduled capture. Set to 0 to capture immediately on startup.</div>
    </div>

    <div class="field">
        <label for="time_before_image">Scheduled Capture Interval (seconds)</label>
        <input type="number" name="time_before_image" id="time_before_image" value="{globals()['time_before_image']}" min="0">
        <div class="hint">Gap between consecutive scheduled captures.</div>
    </div>

    <div class="section-title">Output Settings</div>

    <div class="field">
        <label for="output_width">Output Width (pixels)</label>
        <input type="number" name="output_width" id="output_width" value="{globals()['output_width']}" min="0">
        <div class="hint">Defaults to camera sensor max width.</div>
    </div>

    <div class="field">
        <label for="output_height">Output Height (pixels)</label>
        <input type="number" name="output_height" id="output_height" value="{globals()['output_height']}" min="0">
        <div class="hint">Defaults to camera sensor max height.</div>
    </div>

    <div class="field">
        <label for="output_extension">Output Format</label>
        <select name="output_extension">
            <option value="jpg" {_opt(globals()['output_extension'], ['jpg'])}>JPEG (.jpg)</option>
            <option value="jpeg" {_opt(globals()['output_extension'], ['jpeg'])}>JPEG (.jpeg)</option>
            <option value="png" {_opt(globals()['output_extension'], ['png'])}>PNG (.png)</option>
        </select>
    </div>

    <div class="field">
        <label for="embed_timestamp">Embed Timestamp</label>
        <select name="embed_timestamp">
            <option value="true" {_opt(True, [_bool_val('embed_timestamp')])}>True</option>
            <option value="false" {_opt(False, [not _bool_val('embed_timestamp')])}>False</option>
        </select>
    </div>

    <div class="field">
        <label for="file_name">File Name Prefix</label>
        <input type="text" name="file_name" id="file_name" value="{globals()['file_name']}" placeholder="e.g. frontporch">
    </div>

    <div class="section-title">Text Overlay</div>

    <div class="field">
        <label for="text_size">Text Size (points)</label>
        <input type="number" name="text_size" id="text_size" value="{globals()['text_size']}" min="6" max="120">
    </div>

    <div class="field">
        <label for="text_color">Text Color</label>
        <input type="text" name="text_color" id="text_color" value="{globals()['text_color']}" placeholder="e.g. silver, white, #ffffff">
    </div>

    <div class="field">
        <label for="text_background">Text Background</label>
        <input type="text" name="text_background" id="text_background" value="{globals()['text_background']}" placeholder="e.g. black, rgba(0,0,0,0.5)">
    </div>
</div>

<!-- Tab 2: Transfer Settings -->
<div id="tab-transfer" class="tab-content">
    <div class="section-title">FTP / SFTP Configuration</div>

    <div class="field">
        <label for="ftp-mode">Transfer Protocol</label>
        <select name="ftp-mode">
            <option value="sftp" {_opt(globals()['ftp-mode'], ['sftp'])}>SFTP</option>
            <option value="ftp" {_opt(globals()['ftp-mode'], ['ftp'])}>FTP</option>
        </select>
    </div>

    <div class="field">
        <label for="ftp-server">Server</label>
        <input type="text" name="ftp-server" id="ftp-server" value="{globals()['ftp-server']}" placeholder="e.g. ftp.example.com or IP address">
    </div>

    <div class="field">
        <label for="ftp-port">Port</label>
        <input type="number" name="ftp-port" id="ftp-port" value="{globals()['ftp-port']}" min="1" max="65535">
        <div class="hint">22 for SFTP, 21 for FTP</div>
    </div>

    <div class="field">
        <label for="ftp-username">Username</label>
        <input type="text" name="ftp-username" id="ftp-username" value="{globals()['ftp-username']}">
    </div>

    <div class="field">
        <label for="ftp-password">Password</label>
        <input type="password" name="ftp-password" id="ftp-password" value="{globals()['ftp-password']}">
    </div>

    <div class="field">
        <label for="ftp-destination">Destination Path(s)</label>
        <input type="text" name="ftp-destination" id="ftp-destination" value="{globals()['ftp-destination']}" placeholder="e.g. /home/user/pics, /backup/cam">
        <div class="hint">Comma-separated list of remote paths. Include trailing / for subdirectory mode.</div>
    </div>

    <div class="btn-group">
        <button type="button" class="btn btn-success" id="testConnectionBtn">Test Connection</button>
        <span id="testResult" style="font-size:14px; margin-left:8px;"></span>
    </div>
    <script>
    (function() {{
        document.getElementById('testConnectionBtn').addEventListener('click', function() {{
            var btn = document.getElementById('testConnectionBtn');
            var result = document.getElementById('testResult');
            btn.disabled = true;
            btn.textContent = 'Testing...';
            result.textContent = '';
            var form = document.getElementById('configForm');
            var fd = new FormData(form);
            fetch('/test_connection', {{
                method: 'POST',
                body: fd
            }}).then(function(r) {{ return r.text().then(function(t) {{ return {{status:r.status, data:t}}; }}); }})
            .then(function(r) {{
                if (r.status === 200) {{
                    try {{ var j = JSON.parse(r.data); }} catch(e) {{ var j = {{status:'ok', message:r.data}}; }}
                    if (j.status === 'ok') {{
                        result.textContent = j.message;
                        result.style.color = '#28a745';
                    }} else {{
                        result.textContent = j.message;
                        result.style.color = '#dc3545';
                    }}
                }} else {{
                    result.textContent = r.data;
                    result.style.color = '#dc3545';
                }}
            }}).catch(function(e) {{
                result.textContent = 'Network error: ' + e.message;
                result.style.color = '#dc3545';
            }}).finally(function() {{
                btn.disabled = false;
                btn.textContent = 'Test Connection';
            }});
        }});
    }})();
    </script>
</div>

<!-- Tab 4: System -->
<div id="tab-system" class="tab-content">
    <div class="section-title">Time & Date</div>

    <div class="field">
        <label for="camera_timezone">Timezone</label>
        <input list="timezones" name="camera_timezone" id="camera_timezone" value="{globals()['camera_timezone']}" placeholder="e.g. America/Los_Angeles">
        <datalist id="timezones">
            <option value="America/New_York">
            <option value="America/Chicago">
            <option value="America/Denver">
            <option value="America/Los_Angeles">
            <option value="America/Anchorage">
            <option value="Pacific/Honolulu">
            <option value="America/Phoenix">
            <option value="America/Toronto">
            <option value="America/Vancouver">
            <option value="America/Regina">
            <option value="America/Mexico_City">
            <option value="America/Bogota">
            <option value="America/Lima">
            <option value="America/Sao_Paulo">
            <option value="America/Argentina/Buenos_Aires">
            <option value="America/Santiago">
            <option value="Europe/London">
            <option value="Europe/Dublin">
            <option value="Europe/Lisbon">
            <option value="Europe/Paris">
            <option value="Europe/Berlin">
            <option value="Europe/Rome">
            <option value="Europe/Madrid">
            <option value="Europe/Amsterdam">
            <option value="Europe/Brussels">
            <option value="Europe/Vienna">
            <option value="Europe/Zurich">
            <option value="Europe/Prague">
            <option value="Europe/Warsaw">
            <option value="Europe/Stockholm">
            <option value="Europe/Copenhagen">
            <option value="Europe/Oslo">
            <option value="Europe/Helsinki">
            <option value="Europe/Athens">
            <option value="Europe/Istanbul">
            <option value="Europe/Moscow">
            <option value="Asia/Dubai">
            <option value="Asia/Kolkata">
            <option value="Asia/Shanghai">
            <option value="Asia/Hong_Kong">
            <option value="Asia/Singapore">
            <option value="Asia/Tokyo">
            <option value="Asia/Seoul">
            <option value="Asia/Taipei">
            <option value="Asia/Bangkok">
            <option value="Asia/Jakarta">
            <option value="Asia/Manila">
            <option value="Australia/Sydney">
            <option value="Australia/Melbourne">
            <option value="Australia/Brisbane">
            <option value="Australia/Perth">
            <option value="Pacific/Auckland">
            <option value="Pacific/Fiji">
        </datalist>
    </div>

    <div class="field">
        <label for="camera_daylight_savings">Daylight Saving Time</label>
        <select name="camera_daylight_savings">
            <option value="true" {_opt(True, [_bool_val('camera_daylight_savings')])}>True</option>
            <option value="false" {_opt(False, [not _bool_val('camera_daylight_savings')])}>False</option>
        </select>
    </div>

    <div class="section-title">Network</div>

    <div class="field">
        <label for="camera_port">HTTP Port</label>
        <input type="number" name="camera_port" id="camera_port" value="{globals()['camera_port']}" min="1" max="65535">
        <div class="hint">Changing this port restarts the server automatically.</div>
    </div>

    <div class="field">
        <label for="camera_url">Camera URL</label>
        <input type="text" name="camera_url" id="camera_url" value="{globals()['camera_url']}" placeholder="e.g. http://camuser.dyndns.org:8000">
    </div>

    <div class="section-title">Backup & Restore</div>

    <div class="btn-group">
        <a href="/export_config" class="btn btn-success">Export Configuration</a>
        <button type="button" class="btn btn-primary" id="openImportBtn">Import Configuration</button>
    </div>
</div>
</div>
</div>

</form>

<!-- Import Modal -->
<div id="importModal" class="modal-overlay">
    <div class="modal">
        <span class="close" id="closeImportBtn">&times;</span>
        <h2>Import Configuration</h2>
        <p>Upload a previously exported configuration file to apply its settings.</p>
        <form method="POST" action="/import_config" enctype="multipart/form-data">
            <div class="field">
                <label for="config_file">Configuration File</label>
                <input type="file" name="config_file" id="config_file" accept=".cfg,.ini">
            </div>
            <div class="btn-group">
                <input type="submit" value="Import" class="btn btn-primary">
            </div>
        </form>
    </div>
</div>

<script>
// Tab switching (right pane only)
function switchTab(e, tabId) {{
    e.currentTarget.closest('.settings-pane').querySelectorAll('.tab-content').forEach(function(t) {{ t.classList.remove('active'); }});
    e.currentTarget.closest('.settings-pane').querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    document.getElementById(tabId).classList.add('active');
    e.currentTarget.classList.add('active');
    // Persist active tab for form submission and localStorage
    var name = tabId.replace('tab-', '');
    try {{ document.getElementById('_active_tab').value = name; localStorage.setItem('configActiveTab', name); }} catch(e) {{}}
}}

// Save button: AJAX save then reload page
(function() {{
    var saveBtn = document.getElementById('saveBtn');
    if (saveBtn) {{
        saveBtn.addEventListener('click', function() {{
            var form = document.getElementById('configForm');
            var fd = new FormData(form);
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            fetch('/save_config', {{
                method: 'POST',
                body: fd
            }}).then(function(r) {{
                if (r.status === 200) {{
                    // Show toast, then reload to refresh all values
                    var toast = document.createElement('div');
                    toast.className = 'toast';
                    toast.textContent = 'Configuration saved!';
                    document.body.appendChild(toast);
                    requestAnimationFrame(function() {{ toast.classList.add('show'); }});
                    setTimeout(function() {{
                        toast.classList.remove('show');
                        setTimeout(function() {{ toast.remove(); }}, 400);
                    }}, 2000);
                    window.location.reload();
                }} else {{
                    return r.text().then(function(t) {{ alert('Save failed: ' + t); }}, function() {{ alert('Save failed'); }});
                }}
            }}).catch(function(e) {{
                alert('Save failed: ' + e.message);
            }}).finally(function() {{
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Configuration';
            }});
        }});
    }}
}})();

// Restore tab and show toast on load
(function() {{
    var params = new URLSearchParams(window.location.search);
    var saved = params.get('saved');
    var tabParam = params.get('tab');

    // Show toast for save/import
    if (saved === '1') {{
        var toast = document.createElement('div');
        toast.id = 'saveToast';
        toast.className = 'toast';
        toast.textContent = 'Configuration saved!';
        document.body.appendChild(toast);
        requestAnimationFrame(function() {{ toast.classList.add('show'); }});
        setTimeout(function() {{
            toast.classList.remove('show');
            setTimeout(function() {{ toast.remove(); }}, 400);
        }}, 5000);
        // Clear the saved param so toast doesn't reappear on accidental refresh
        var url = new URL(window.location);
        url.searchParams.delete('saved');
        if (url.searchParams.get('tab')) url.searchParams.delete('tab');
        window.history.replaceState({{}}, '', url);
    }}
    if (params.get('imported') === '1') {{
        var toast = document.createElement('div');
        toast.id = 'saveToast';
        toast.className = 'toast';
        toast.textContent = 'Configuration imported successfully!';
        document.body.appendChild(toast);
        requestAnimationFrame(function() {{ toast.classList.add('show'); }});
        setTimeout(function() {{
            toast.classList.remove('show');
            setTimeout(function() {{ toast.remove(); }}, 400);
        }}, 5000);
        var url = new URL(window.location);
        url.searchParams.delete('imported');
        if (url.searchParams.get('tab')) url.searchParams.delete('tab');
        window.history.replaceState({{}}, '', url);
    }}

    // Restore active tab: URL param > localStorage > default 'camera'
    var activeTab = null;
    if (tabParam) activeTab = tabParam;
    else {{
        try {{ activeTab = localStorage.getItem('configActiveTab'); }} catch(e) {{}}
    }}
    if (!activeTab) activeTab = 'camera';

    // Always sync hidden field
    try {{ document.getElementById('_active_tab').value = activeTab; }} catch(e) {{}}

    if (activeTab !== 'camera') {{
        var btns = document.querySelector('.settings-pane').querySelectorAll('.tab-btn');
        var contents = document.querySelector('.settings-pane').querySelectorAll('.tab-content');
        btns.forEach(function(b) {{ b.classList.remove('active'); }});
        contents.forEach(function(t) {{ t.classList.remove('active'); }});
        var target = document.getElementById('tab-' + activeTab);
        if (target) {{
            target.classList.add('active');
            for (var i = 0; i < btns.length; i++) {{
                if (btns[i].getAttribute('onclick') && btns[i].getAttribute('onclick').indexOf("'tab-" + activeTab + "')") > -1) {{
                    btns[i].classList.add('active');
                    break;
                }}
            }}
        }}
    }}
}})();

// Import modal
(function() {{
    var modal = document.getElementById('importModal');
    var openBtn = document.getElementById('openImportBtn');
    var closeBtn = document.getElementById('closeImportBtn');
    openBtn.onclick = function() {{ modal.style.display = 'block'; }};
    closeBtn.onclick = function() {{ modal.style.display = 'none'; }};
    window.onclick = function(e) {{ if (e.target === modal) modal.style.display = 'none'; }};
}})();

// Unsaved-changes guard
(function() {{
    var originalValues = {{
        'ftp-mode': '{globals()['ftp-mode']}',
        'ftp-server': '{globals()['ftp-server']}',
        'ftp-port': '{globals()['ftp-port']}',
        'ftp-username': '{globals()['ftp-username']}',
        'camera_name': '{globals()['camera_name']}',
        'rotation': '{globals()['rotation']}',
        'time_before_first_image': '{globals()['time_before_first_image']}',
        'time_before_image': '{globals()['time_before_image']}',
        'output_width': '{globals()['output_width']}',
        'output_height': '{globals()['output_height']}',
        'output_extension': '{globals()['output_extension']}',
        'embed_timestamp': _bool_val('embed_timestamp') ? 'true' : 'false',
        'file_name': '{globals()['file_name']}',
        'text_size': '{globals()['text_size']}',
        'text_color': '{globals()['text_color']}',
        'text_background': '{globals()['text_background']}',
        'camera_timezone': '{globals()['camera_timezone']}',
        'camera_daylight_savings': _bool_val('camera_daylight_savings') ? 'true' : 'false',
        'camera_port': '{globals()['camera_port']}',
        'camera_url': '{globals()['camera_url']}',
    }};
    var hasChanges = false;

    document.getElementById('configForm').addEventListener('input', function(e) {{ hasChanges = true; }}, true);
    document.getElementById('configForm').addEventListener('change', function(e) {{ hasChanges = true; }}, true);

    window.addEventListener('beforeunload', function(e) {{
        if (hasChanges) {{
            e.preventDefault();
            e.returnValue = '';
        }}
    }});

    var params = new URLSearchParams(window.location.search);
    if (params.get('saved') === '1' || params.get('imported') === '1') {{
        hasChanges = false;
    }}
}})();

</script>
</body>
</html>
"""

def connection_check(interface):
    """
    Update needed
    """
    ni.gateways()
    interfaces = ni.interfaces()

    if interface in interfaces:
        try:
            ip = ni.ifaddresses(interface)[ni.AF_INET][0]['addr']
            # ni.ifaddresses(interface)[ni.]
            print(f'{interface} IP address: {ip}')
            if len(ip) > 7:
                print(f"Using {interface} connection")

                requests.head('http://google.com', timeout=5)
                print("True connection to the internet is established")
                # true_connection = True
                return ip
        except Exception as ex:
            print(f"Connect_Exception: {interface}")
            print(ex)

        # Needs to ensure a real connection to the internet or continue
        # to the next adapter.
    return False

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            logging.debug(f"New frame written: {len(buf)} bytes")
            self.condition.notify_all()

def update_rtc_time():
    """
    Update the time from the internet and then set the hardware
    clock. Note that this can't be checked until on a linux system.
    """
    loop_time_set = 10
    is_set = False
    # Get the time off of the internet.
    # os.system("sudo ntpdate time-a-g.nist.gov time-b-g.nist.gov time-c-g.nist.gov time-d-g.nist.gov time-d-g.nist.gov time-e-g.nist.gov time-e-g.nist.gov time-a-wwv.nist.gov time-b-wwv.nist.gov time-c-wwv.nist.gov time-d-wwv.nist.gov time-d-wwv.nist.gov time-e-wwv.nist.gov time-e-wwv.nist.gov time-a-b.nist.gov time-b-b.nist.gov time-c-b.nist.gov time-d-b.nist.gov time-d-b.nist.gov time-e-b.nist.gov time-e-b.nist.gov time.nist.gov utcnist.colorado.edu utcnist2.colorado.edu")
    while loop_time_set > 0 and is_set == False:
        try:
            ## Raspberry Pi 5 method of setting time
            ## Want to update the time every time the script is run
            os.system("sudo timedatectl set-ntp False")
            os.system("sudo timedatectl set-ntp True")
            is_set = True
        except:
            print("couldn't update time from timedatectl command")
        try:
            if not is_set:
                os.system("sudo systemctl restart systemd-timesyncd")
                is_set = True
        except:
            print("couldn't update time from systemctl command")

        try:
            if not is_set:
                os.system("sudo ntpdate -q 0.us.pool.ntp.org")
                is_set = True
        except Exception as ex:
            print("couldn't find time")
        # Set the hardware clock
        try:
            if not is_set:
                os.system("sudo hwclock -w")
                is_set = True
        except Exception as ex:
            print("couldn't hwclock -w")

        try:
            if not is_set:
                os.system("sudo hwclock -s")
                is_set = True
        except Exception as ex:
            print("couldn't hwclock -s")
        time.sleep(5)
        loop_time_set -= 1
    return

def reconfigure_camera():
    """Reconfigure the camera with the current ROTATION setting.

    Called from /save_config when rotation changes. Stops recording,
    recomputes WIDTH/HEIGHT and transform, then restarts recording.
    """
    global picam2, WIDTH, HEIGHT, transform

    if picam2 is None:
        print("Camera not initialised — cannot reconfigure")
        return

    old_rotation = ROTATION
    new_rotation = int(globals().get('rotation', '0'))

    if new_rotation not in (0, 90, 180, 270):
        print(f"Invalid rotation {new_rotation} — keeping current")
        return

    if new_rotation == old_rotation:
        return

    print(f"Reconfiguring camera: {old_rotation}° -> {new_rotation}°")
    picam2.stop_recording()

    # Recalculate dimensions (swap for 90/270)
    if new_rotation in (90, 270):
        WIDTH, HEIGHT = NATIVE_SIZE[1], NATIVE_SIZE[0]
    else:
        WIDTH, HEIGHT = NATIVE_SIZE

    # Build new transform
    if new_rotation == 0:
        transform = Transform()
    elif new_rotation == 180:
        transform = Transform(hflip=1, vflip=1)
    elif new_rotation == 90:
        transform = Transform(vflip=1)
    elif new_rotation == 270:
        transform = Transform(hflip=1)

    config = picam2.create_video_configuration(
        main={"size": (WIDTH, HEIGHT)},
        transform=transform
    )
    picam2.configure(config)
    picam2.start_recording(JpegEncoder(q=60), FileOutput(output))

    print(f"Camera reconfigured: {WIDTH}x{HEIGHT}, rotated {new_rotation}°")


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
    # load_config()
    # return ("HI")
    return render_template_string(generate_config_page())


@app.route('/save_config', methods=['POST'])
def save_config_route():
    # rotation = int(request.form['rotation'])
    config_key_value = request.form
    # try:
    #     save_config(config_key_value)
    #     return redirect('/config.html?saved=1')
    # except Exception as e:
    #     print(e)
    #     return "Invalid rotation", 400

    old_port = globals().get('camera_port', '8000')
    new_port = config_key_value.get('camera_port', old_port)
    old_rotation = int(globals().get('rotation', '0'))
    new_rotation_str = config_key_value.get('rotation', str(old_rotation))

    error_text = """"""
    for key, value in config_key_value.items():
        if key == "rotation":
            if not value.isnumeric():
                error_text += f"Invalid rotation: {value}\n"
            if not int(value) in (0, 90, 180, 270):
                error_text += f"Invalid rotation: {value}\n"
        elif key == "time_before_image":
            if not value.isnumeric():
                error_text += f"Invalid time_before_image: {value}\n"
        elif key == "time_before_first_image":
            if not value.isnumeric():
                error_text += f"Invalid time_before_first_image: {value}\n"
        elif key == "output_width":
            if not value.isnumeric():
                error_text += f"Invalid output_width: {value}\n"
        elif key == "output_height":
            if not value.isnumeric():
                error_text += f"Invalid output_height: {value}\n"
        elif key == "output_extension":
            if not value in ("jpg", "jpeg", "png"):
                error_text += f"Invalid output_extension: {value}\n"
        elif key == "camera_name":
            if ' ' in value:
                error_text += f"Invalid camera_name please use '_' (underscore) instead of spaces.\n"
        elif key == "camera_port":
            if not value.isnumeric() or not 1 <= int(value) <= 65535:
                error_text += f"Invalid camera_port: {value}\n"

    if len(error_text) > 0:
        return error_text, 400
    else:
        save_config(config_key_value)
        if int(new_rotation_str) != old_rotation:
            reconfigure_camera()
        if new_port != old_port:
            print(f"Port changed from {old_port} to {new_port} — restarting server...")
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--restart-port', new_port])
        return '', 200


@app.route('/export_config')
def export_config():
    """Return the current config file as a downloadable file."""
    return send_file(
        CONFIG_FILE,
        as_attachment=True,
        download_name='camera_config.cfg',
        mimetype='text/plain',
    )


@app.route('/import_config', methods=['POST'])
def import_config():
    """Import configuration from an uploaded .cfg file."""
    if 'config_file' not in request.files:
        return 'No file provided', 400
    uploaded = request.files['config_file']
    if uploaded.filename == '':
        return 'No file selected', 400
    if not (uploaded.filename.endswith('.cfg') or uploaded.filename.endswith('.ini')):
        return 'Invalid file type; expected .cfg or .ini', 400
    try:
        with open(CONFIG_FILE, 'w') as f:
            f.write(uploaded.read().decode('utf-8'))
        # Reload globals from the new config file
        _cfg = configparser.ConfigParser()
        _cfg.read(CONFIG_FILE)
        if _cfg.has_section('camera'):
            for key, value in _cfg.items('camera'):
                # Convert 'True'/'False' strings to booleans
                if key in ('embed_timestamp', 'camera_daylight_savings'):
                    if value == 'True':
                        value = True
                    elif value == 'False':
                        value = False
                globals()[key] = value
        globals().update({k: v for k, v in _cfg.items('camera')
                         if k not in ('embed_timestamp', 'camera_daylight_savings')})
        return redirect('/config.html?imported=1')
    except Exception as e:
        return f'Error importing config: {e}', 500


def test_ftp_connection(server, port, username, password):
    """Test an FTP connection and return (success, message)."""
    import ftplib
    try:
        ftp = ftplib.FTP(server, port)
        ftp.login(username, password)
        ftp.quit()
        return True, f"Connected to {server}:{port} as {username}"
    except Exception as ex:
        return False, f"FTP failed: {ex}"


def test_sftp_connection(server, port, username, password):
    """Test an SFTP connection and return (success, message)."""
    import paramiko
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=server, port=int(port), username=username, password=password, timeout=10)
        ssh.close()
        return True, f"Connected to {server}:{port} as {username}"
    except Exception as ex:
        return False, f"SFTP failed: {ex}"


@app.route('/test_connection', methods=['POST'])
def test_connection():
    """Test FTP/SFTP connection with the provided settings."""
    ftmode = request.form.get('ftp-mode', 'sftp').lower()
    server = request.form.get('ftp-server', '')
    port = request.form.get('ftp-port', '22')
    username = request.form.get('ftp-username', '')
    password = request.form.get('ftp-password', '')

    if not all([server, username]):
        return 'Missing server or username', 400

    print(f"Testing {ftmode.upper()} connection to {server}:{port} as {username}")
    if ftmode == 'sftp':
        ok, msg = test_sftp_connection(server, port, username, password)
    else:
        ok, msg = test_ftp_connection(server, port, username, password)

    status = 'ok' if ok else 'error'
    return f'{{"status":"{status}","message":"{msg}"}}', 200 if ok else 400, {'Content-Type': 'application/json'}


def _bool_val(key):
    """Convert a config value to a checkbox-checked state."""
    return str(globals().get(key, '')).lower() == 'true'


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
    print("""Capture a single high-quality JPEG still from the camera.""")
    photo_buffer = BytesIO()
    picam2.capture_file(photo_buffer, name="main", format="jpeg")
    photo_buffer.seek(0)
    return Response(photo_buffer.getvalue(), mimetype='image/jpeg')

def file_date_string():
    string = time.strftime('%Y%m%d_%H%M%S', current_time())
    return string

@app.route('/capture_embedded.jpg')
def capture_embedded_photo():
    """Capture a single high-quality JPEG still from the camera, with embedded text."""
    print("""Capture a single high-quality JPEG still from the camera, with embedded text.""")
    photo_buffer = BytesIO()
    picam2.capture_file(photo_buffer, name="main", format="jpeg")
    photo_buffer.seek(0)

    background = Image.open(photo_buffer)
    img_text = create_embed_text()
    background.paste(img_text, (0, 0))

    output_buffer = BytesIO()
    background.save(output_buffer, format="jpeg", quality=100)
    output_buffer.seek(0)
    destination = ""
    file_name = f"{globals()['output_folder']}/{globals()['camera_name']}_{file_date_string()}.jpg"
    for dest in globals()['ftp-destination'].split(','):
        if dest.endswith('/'):
            destination = dest[:-1]
            destination = f"{destination}/{globals()['camera_name']}_{file_date_string()}.jpg"
        else:
            destination = f"{dest}"

        print(f"Transfering: {file_name}")
        print(f"Destination: {destination}")

        background.save(file_name, format="jpeg")
        if destination != "":
            try:
                trasfer = ft.FileTransfer(
                    globals()['ftp-server'],
                    globals()['ftp-username'],
                    globals()['ftp-password'],
                    'SFTP',
                    file_name,
                    # globals()['ftp-destination'],
                    destination,
                    globals()['ftp-port'],
                )
            except Exception as ex:
                print("Couldn't transfer file to FTP server.")
                print(ex)

    return Response(output_buffer.getvalue(), mimetype='image/jpeg')

def background_capture_task(delay):
    first = True
    while True:
        try:
            if delay > 0:
                # Use time_before_first_image on the first capture, then time_before_image
                if first:
                    wait = int(globals().get('time_before_first_image', '0'))
                    if wait > 0:
                        print(f"Waiting {wait}s before first capture...")
                        total = 0
                        while total < wait:
                            time.sleep(1)
                            total += 1
                            if total % 10 == 0:
                                print(f"Waiting {wait - total}s before first capture...")
                    first = False
                else:
                    total_delayed = 0
                    print(f"Background thread sleeping for {delay} seconds...")
                    while total_delayed < delay:
                        time.sleep(1)
                        total_delayed += 1
                        if total_delayed % 10 == 0:
                            print(f"Background thread sleeping for {delay} seconds... {total_delayed} seconds elapsed.")
            capture_embedded_photo()
        except Exception as ex:
            print("Error in background thread.")
            print(ex)
            time.sleep(30)

def create_embed_text():
    """
    This method is going to create the text that is going to be put onto the
    photo ONLY. When the text is created it will then be embedded into the image.

    Enhance with the path that the file should be saved to so that images aren't in the
    root folder.
    """
    camera_name = globals()['camera_name']
    script_dir = os.path.dirname(__file__)
    if len(globals()['embed_timestamp']) > 2:
        camera_name = globals()['camera_name'] + ' - ' + cam_time()

    # sample text and font
    unicode_text = camera_name
    # font_path = f'{self.script_dir}/fonts/AmazeFont.otf'
    font_path = f'{script_dir}/fonts/AmazeFont.otf'

    try:
        font = ImageFont.truetype(font=font_path, size=int(globals()['text_size']))
    except Exception as ex:
        print("Couldn't load font size: ", globals()['text_size'], " using default size: 18")
        print(ex)
        font = ImageFont.truetype(font=font_path, size=18)
    left, top, right, bottom = font.getbbox(text=unicode_text, mode='string')
    text_width = right - left
    text_height = bottom - top

    # create a blank canvas with extra space between lines
    try:
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), globals()['text_background'])
    except Exception as ex:
        # For if the background color isn't able to be loaded.'
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), 'black')

    # draw the text onto the text canvas, and use black as the text color
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((5,5), camera_name, globals()['text_color'], font)
    except Exception as ex:
        # For if the font color isn't able to be loaded.
        draw.text((5,5), camera_name, 'silver', font)

    # save the blank canvas to a file
    # output_dir = f"{globals()['output_dir']}/text.{globals()['output_ext']}"
    # try:
    #     os.remove(output_dir)
    # except Exception as ex:
    #     pass
    # canvas.save(output_dir)

    return canvas

if __name__ == '__main__':
    # Handle restart with port override
    if '--restart-port' in sys.argv:
        restart_port = sys.argv[sys.argv.index('--restart-port') + 1]
        globals()['camera_port'] = restart_port
        print(f"Restarting on port {restart_port}...")

    # Configure camera with detected max size
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (WIDTH, HEIGHT)},
        transform=transform
    )
    picam2.configure(config)

    # Start recording to output
    # picam2.start_recording(JpegEncoder(q=85), FileOutput(output))
    picam2.start_recording(JpegEncoder(q=60), FileOutput(output))

    # logging.basicConfig(level=logging.DEBUG)

    print(f"Loaded rotation from config: {ROTATION}°")
    print(f"Detected max native size: {NATIVE_SIZE}")
    print(f"Server starting on http://0.0.0.0:{globals()['camera_port']} (local: http://localhost:{globals()['camera_port']})")
    print(f"Streaming rotated {ROTATION}° video at {WIDTH}x{HEIGHT}")
    print("New: Fullscreen view at /full.html")
    print("Capture: Button on index page saves/displays latest photo")
    print("Config: Set rotation at /config.html (applies immediately)")

    thread = Thread(target=background_capture_task, args=(int(globals()['time_before_image']),), daemon=True)
    thread.start()
    try:
        app.run(host='0.0.0.0', port=int(globals()['camera_port']), threaded=True, use_reloader=False)
    finally:
        picam2.stop_recording()
