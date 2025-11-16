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
from threading import Condition
from flask import Flask, Response, redirect, request, render_template_string
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from libcamera import Transform  # Requires python3-libcamera; install if missing

os.environ["LIBCAMERA_LOG_LEVELS"] = "3"
CONFIG_FILE = 'cam_config.cfg'  # File to save/load rotation (INI format)

default_config = {
    'ftp-username': 'username',
    'ftp-password': 'password',
    'ftp-destination': 'ftp_destination_list',
    'camera_name': 'camera_name',
    'rotation': '0',
    'time_before_image': 'time_before_image',
    'output_width': 'width',
    'output_height': 'height',
    'output_extension': 'extension',
    'embed_timestamp': 'embed_timestamp',
    'file_name': 'file_name',
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
                print("Current config: ", key, " = ", value)
    # globals().update(configs)
    # print(globals())
    globals().update(configs)
    print(globals())

    for key, value in default_config.items():
        if key not in globals():
            globals()[key] = value
            configs[key] = value
    # save_config(configs)

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
            print(key, value)
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
            print("Save config: ", key, " = ", value)
            globals()[key] = value
        globals().update(configs)
        config['camera'] = configs # this will actually write the config out
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)

        for key, value in globals().items():
            if key in default_config.keys():
                print(key, "::", value)
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
<img id="photo" style="display: none; width: {WIDTH/8}px; height: {HEIGHT/8}px; margin-top: 10px;" />
<script>
document.getElementById('captureBtn').onclick = function() {{
    const photoImg = document.getElementById('photo');
    photoImg.src = '/capture.jpg?' + Date.now();
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
<p>The following form allows you to configure the camera rotation. Click "Save Configuration" to save the new rotation to the config file.</p>
<form method="POST" action="/save_config">
    <table>
        <tr><td colspan=2><h2>Transfer Configuration<h2></td></tr>
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
        <tr><td colspan=2><h2>Camera Config<h2></td></tr>
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
            <td>time_before_image:</td>
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
            <td><input type="text" name="output_extension" value="{globals()['output_extension']}"></td>
        </tr>
        <tr>
            <td>embed_timestamp:</td>
            <td><input type="text" name="embed_timestamp" value="{globals()['embed_timestamp']}"></td>
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
        </tr>
            <td>camera_timezone:</td>
            <td><input type="text" name="camera_timezone" value="{globals()['camera_timezone']}"></td>
        </tr>
        <tr>
            <td>camera_daylight_savings:</td>
            <td><input type="text" name="camera_daylight_savings" value="{globals()['camera_daylight_savings']}"></td>
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
            <td colspan=2><input type="submit" value="Save Configuration"></td>       
        </tr>
    </table>
</form>
<p><a href="/">Back to Stream</a></p>
<script>
if (window.location.search.includes('saved=1')) {{
    alert('Configuration saved!');
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
    # load_config()
    # return ("HI")
    return render_template_string(generate_config_page())


@app.route('/save_config', methods=['POST'])
def save_config_route():
    # rotation = int(request.form['rotation'])
    config_key_value = request.form
    try:
        save_config(config_key_value)
        return redirect('/config.html?saved=1')
    except Exception as e:
        print(e)
        return "Invalid rotation", 400
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
    background.save(output_buffer, format="jpeg")
    output_buffer.seek(0)

    return Response(output_buffer.getvalue(), mimetype='image/jpeg')

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

    font = ImageFont.truetype(font=font_path, size=18)
    left, top, right, bottom = font.getbbox(text=unicode_text, mode='string')
    text_width = right - left
    text_height = bottom - top

    # create a blank canvas with extra space between lines
    try:
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), globals()['text_background'])
    except Exception as ex:
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), 'black')

    # draw the text onto the text canvas, and use black as the text color
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((5,5), camera_name, globals()['text_color'], font)
    except Exception as ex:
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
    # Configure camera with detected max size
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (WIDTH, HEIGHT)},
        transform=transform
    )
    picam2.configure(config)

    # Start recording to output
    picam2.start_recording(JpegEncoder(q=85), FileOutput(output))

    # logging.basicConfig(level=logging.DEBUG)

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
