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
    for key in ('camera_port', 'time_before_image', 'output_width', 'output_height', 'output_max_filesize_kb'):
        val = globals().get(key)
        try:
            int(val)
        except (ValueError, TypeError):
            defaults = {'camera_port': '8000', 'output_width': '0', 'output_height': '0', 'output_max_filesize_kb': '0', 'time_before_image': '10'}
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
    print("Save config: ", rotation)
    # config['camera'] = {'rotation': str(rotation)}
    try:
        for key, value in rotation.items():
            # print(key, value)
            try:
                configs[key] = value
            except Exception as e:
                print("Error updating configs:")
                print(e)
            # try:
            #     config[key] = value
            # except Exception as e:
            #     print("Error updating config:")
            #     print(e)
            # print("Save config: ", key, " = ", value)
            globals()[key] = value
        globals().update(configs)
        config['camera'] = configs # this will actually write the config out
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)

        # for key, value in globals().items():
        #     if key in default_config.keys():
        #         print(key, "::", value)
    except Exception as e:
        print("Error saving config")
        print(e)

    print("trying to load config again:")
    # load_config()
    print("trying to load config again END")

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

PAGE = f"""\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo (Rotated {ROTATION}°)</h1>
<img src="/stream.mjpg" width="{WIDTH/8}" height="{HEIGHT/8}" />
<p><a href="/full.html">Go to Fullscreen View</a> | <a href="/config.html">Configure Settings</a></p>
<button id="captureBtn">Capture Photo</button>
<button id="captureEmbeddedBtn">Capture Photo with Embedded Text</button>

<img id="photo" style="display: none; width: {WIDTH/8}px; height: {HEIGHT/8}px; margin-top: 10px;" />
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
    return f"""\
<html>
<head>
<title>Configure Rotation</title>
</head>
<body>
<h1>Camera Configuration</h1>

<div style="margin-bottom:16px;">
    <a href="/" style="display:inline-block; padding:8px 16px; background:#6c757d; color:#fff; text-decoration:none; border:none; border-radius:4px;">Back to Stream</a>
    <input type="button" id="topSaveBtn" value="Save Configuration" style="padding:8px 16px; background:#007bff; color:#fff; border:none; border-radius:4px; cursor:pointer;" onclick="document.getElementById('configForm').submit();">
    <a href="/export_config" style="display:inline-block; padding:8px 16px; background:#007bff; color:#fff; text-decoration:none; border-radius:4px;">Export Configuration</a>
    <button id="openImportBtn" style="padding:8px 16px; background:#28a745; color:#fff; border:none; border-radius:4px; cursor:pointer;">Import Configuration</button>
</div>

<form id="configForm" method="POST" action="/save_config">
    <table>
        <tr><td colspan=2><h2>Transfer Configuration</h2></td></tr>
        <tr>
            <td>ftp-mode:</td>
            <td><input type="text" name="ftp-mode" value="{globals()['ftp-mode']}"></td>
        </tr>
        <tr>
            <td>ftp-server:</td>
            <td><input type="text" name="ftp-server" value="{globals()['ftp-server']}"></td>
        </tr>
        <tr>
            <td>ftp-port:</td>
            <td><input type="text" name="ftp-port" value="{globals()['ftp-port']}"></td>
        </tr>
        <tr>
            <td>ftp-username:</td>
            <td><input type="text" name="ftp-username" value="{globals()['ftp-username']}"></td>
        </tr>
        <tr>
            <td>ftp-password:</td>
            <td><input type="password" name="ftp-password" value="{globals()['ftp-password']}"></td>
        </tr>
        <tr>
            <td>ftp-destination:</td>
            <td><input type="text" name="ftp-destination" value="{globals()['ftp-destination']}"></td>
        </tr>
        <tr><br></tr>
        <tr><td colspan=2><h2>Camera Config</h2></td></tr>
        <tr>
            <td>camera_name:</td>
            <td><input type="text" name="camera_name" value="{globals()['camera_name']}"></td>
        </tr>
        <tr>
            <td>Rotation (degrees):</td>
            <td>
                <select id="rotation" name="rotation">
                    <option value="0" " + ('selected' if {ROTATION} == 0 else '') + ">0</option>
                    <option value="90" " + ('selected' if {ROTATION} == 90 else '') + ">90</option>
                    <option value="180" " + ('selected' if {ROTATION} == 180 else '') + ">180</option>
                    <option value="270" " + ('selected' if {ROTATION} == 270 else '') + ">270</option>
                </select>
            </td>
        </tr>
        <tr>
            <td>time_before_image (seconds):</td>
            <td><input type="text" name="time_before_image" value="{globals()['time_before_image']}"></td>
        </tr>
        <tr>
            <td>output_width:</td>
            <td><input type="text" name="output_width" value="{globals()['output_width']}"></td>
        </tr>
        <tr>
            <td>output_height:</td>
            <td><input type="text" name="output_height" value="{globals()['output_height']}"></td>
        </tr>
        <tr>
            <td>output_extension:</td>
            <td>
                <select name="output_extension">
                    <option value="jpg" " + ('selected' if globals()['output_extension'] == 'jpg' else '') + ">jpg</option>
                    <option value="jpeg" " + ('selected' if globals()['output_extension'] == 'jpeg' else '') + ">jpeg</option>
                    <option value="png" " + ('selected' if globals()['output_extension'] == 'png' else '') + ">png</option>
                </select>
            </td>
        </tr>
        <tr>
            <td>embed_timestamp:</td>
            <td>
                <select name="embed_timestamp">
                    <option value="true" " + ('selected' if _bool_val('embed_timestamp') else '') + ">True</option>
                    <option value="false" " + ('selected' if not _bool_val('embed_timestamp') else '') + ">False</option>
                </select>
            </td>
        </tr>
        <tr>
            <td>file_name:</td>
            <td><input type="text" name="file_name" value="{globals()['file_name']}"></td>
        </tr>
        <tr>
            <td>text_size:</td>
            <td><input type="text" name="text_size" value="{globals()['text_size']}"></td>
        </tr>
        <tr>
            <td>text_color:</td>
            <td><input type="text" name="text_color" value="{globals()['text_color']}"></td>
        </tr>
        <tr>
            <td>text_background:</td>
            <td><input type="text" name="text_background" value="{globals()['text_background']}"></td>
        </tr>
        <tr>
            <td>camera_timezone:</td>
            <td>
                <input list="timezones" name="camera_timezone" value="{globals()['camera_timezone']}" placeholder="e.g. America/New_York">
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
            </td>
        </tr>
        <tr>
         <td>camera_daylight_savings:</td>
            <td>
                <select name="camera_daylight_savings">
                    <option value="true" " + ('selected' if _bool_val('camera_daylight_savings') else '') + ">True</option>
                    <option value="false" " + ('selected' if not _bool_val('camera_daylight_savings') else '') + ">False</option>
                </select>
            </td>
        </tr>
        <tr>
            <td>camera_port:</td>
            <td><input type="text" name="camera_port" value="{globals()['camera_port']}"></td>
        </tr>
        <tr>
            <td>camera_url:</td>
            <td><input type="text" name="camera_url" value="{globals()['camera_url']}"></td>
        </tr>
        <tr>
            <td colspan=2>
                <input type="submit" value="Save Configuration" style="padding:8px 16px; background:#007bff; color:#fff; border:none; border-radius:4px; cursor:pointer;">
            </td>
        </tr>
    </table>
</form>

<!-- Modal -->
<div id="importModal" style="display:none; position:fixed; z-index:999; left:0; top:0; width:100%; height:100%; overflow:auto; background:rgba(0,0,0,0.5);">
    <div style="background:#fff; margin:10% auto; padding:24px; border-radius:8px; width:90%; max-width:480px; position:relative;">
        <span id="closeImportBtn" style="position:absolute; top:8px; right:16px; font-size:24px; cursor:pointer; color:#999;">&times;</span>
        <h2 style="margin-top:0;">Import Configuration</h2>
        <p>Upload a previously exported configuration file to apply its settings.</p>
        <form method="POST" action="/import_config" enctype="multipart/form-data">
            <table>
                <tr>
                    <td style="padding:4px 12px 4px 0;">Select config file:</td>
                    <td><input type="file" name="config_file" accept=".cfg,.ini"></td>
                </tr>
                <tr>
                    <td colspan=2 style="padding-top:12px;">
                        <input type="submit" value="Import Configuration" style="padding:8px 16px; background:#28a745; color:#fff; border:none; border-radius:4px; cursor:pointer;">
                    </td>
                </tr>
            </table>
        </form>
    </div>
</div>
<script>
(function() {{
    var modal = document.getElementById('importModal');
    var openBtn = document.getElementById('openImportBtn');
    var closeBtn = document.getElementById('closeImportBtn');
    openBtn.onclick = function() {{ modal.style.display = 'block'; }};
    closeBtn.onclick = function() {{ modal.style.display = 'none'; }};
    window.onclick = function(e) {{ if (e.target === modal) modal.style.display = 'none'; }};

    // Unsaved-changes guard: compare current field values to originals
    var originalValues = {{
        'ftp-mode': '{globals()['ftp-mode']}',
        'ftp-server': '{globals()['ftp-server']}',
        'ftp-port': '{globals()['ftp-port']}',
        'ftp-username': '{globals()['ftp-username']}',
        'camera_name': '{globals()['camera_name']}',
        'rotation': '{ROTATION}',
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

    document.getElementById('configForm').addEventListener('change', function(e) {{
        hasChanges = true;
    }});

    window.addEventListener('beforeunload', function(e) {{
        if (hasChanges) {{
            e.preventDefault();
            e.returnValue = '';
        }}
    }});

    // Reset flag after save or import
    var params = new URLSearchParams(window.location.search);
    if (params.get('saved') === '1' || params.get('imported') === '1') {{
        hasChanges = false;
    }}
}})();
if (window.location.search.includes('imported=1')) {{
    alert('Configuration imported successfully!');
}} else if (window.location.search.includes('saved=1')) {{
    alert('Configuration saved!');
}}
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
        if new_port != old_port:
            print(f"Port changed from {old_port} to {new_port} — restarting server...")
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--restart-port', new_port])
        return redirect('/config.html?saved=1')

    # print(config_key_value)
    # for key, value in config_key_value.items():
    #     print(key, value)
    # exit(0)
    # if rotation in (0, 90, 180, 270):
    #     save_config(rotation)
    #     return redirect('/config.html?saved=1')
    # else:
    #     return "Invalid rotation", 400
    return config_key_value


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
                globals()[key] = value
        globals().update(dict(_cfg.items('camera')))
        return redirect('/config.html?imported=1')
    except Exception as e:
        return f'Error importing config: {e}', 500


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
    while True:
        try:
            if delay > 0:
                total_delayed = 0
                print(f"Background thread sleeping for {delay} seconds...")
                # Every 10 seconds in the delay we're going to print something so that
                # we can see the logs as they're delaying
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
    print("Config: Set rotation at /config.html (restart server to apply)")

    thread = Thread(target=background_capture_task, args=(int(globals()['time_before_image']),), daemon=True)
    thread.start()
    try:
        app.run(host='0.0.0.0', port=int(globals()['camera_port']), threaded=True, use_reloader=False)
    finally:
        picam2.stop_recording()
