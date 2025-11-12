#!/usr/bin/python3

import io
import logging
from threading import Condition
import os

import piexif
import configparser
from flask import Flask, render_template_string, Response, request, jsonify

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

ROTATION = 270  # Use 0, 90, 180 or 270
WIDTH = 640
HEIGHT = 480

rotation_header = bytes()
if ROTATION == 90 or ROTATION == 270:
    WIDTH, HEIGHT = HEIGHT, WIDTH
if ROTATION:
    code = 6 if ROTATION == 90 else 8 if ROTATION == 270 else 3
    exif_bytes = piexif.dump({'0th': {piexif.ImageIFD.Orientation: code}})
    exif_len = len(exif_bytes) + 2
    rotation_header = bytes.fromhex('ffe1') + exif_len.to_bytes(2, 'big') + exif_bytes

PAGE = """\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
<style>
.btn-capture {{
    background-color: #4CAF50;
    border: none;
    color: white;
    padding: 15px 32px;
    text-align: center;
    text-decoration: none;
    display: inline-block;
    font-size: 16px;
    margin: 10px 2px;
    cursor: pointer;
    border-radius: 4px;
    font-weight: bold;
}}
.btn-capture:hover {{
    background-color: #45a049;
}}
.btn-capture:active {{
    background-color: #3e8e41;
}}
</style>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<img src="stream.mjpg" width="{WIDTH}" height="{HEIGHT}" />
<br><br>
<button class="btn-capture" onclick="takePicture()">TAKE A PICTURE</button>
<br>
<a href="/fullres">View Full Resolution</a> | <a href="/config">Configuration</a>
<script>
function takePicture() {
    fetch('/capture', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Picture captured successfully!\\nSaved as: ' + data.filename);
        } else {
            alert('Error capturing picture: ' + data.error);
        }
    })
    .catch(error => {
        alert('Error: ' + error);
    });
}
</script>
</body>
</html>
"""

CONFIG_PAGE = """\
<html>
<head>
<title>Camera Configuration</title>
<style>
body {
    font-family: Arial, sans-serif;
    background: #f4f4f4;
    margin: 0;
    padding: 20px;
}
.container {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    padding: 30px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
h1 {
    color: #333;
    border-bottom: 2px solid #4CAF50;
    padding-bottom: 10px;
}
h2 {
    color: #666;
    margin-top: 30px;
    margin-bottom: 15px;
    font-size: 18px;
}
.form-group {
    margin-bottom: 15px;
}
label {
    display: block;
    margin-bottom: 5px;
    color: #555;
    font-weight: bold;
}
input[type="text"], input[type="number"] {
    width: 100%;
    padding: 8px;
    border: 1px solid #ddd;
    border-radius: 4px;
    box-sizing: border-box;
}
input[type="checkbox"] {
    margin-right: 5px;
}
.btn {
    background-color: #4CAF50;
    border: none;
    color: white;
    padding: 12px 30px;
    text-align: center;
    text-decoration: none;
    display: inline-block;
    font-size: 16px;
    margin: 20px 5px 0 0;
    cursor: pointer;
    border-radius: 4px;
}
.btn:hover {
    background-color: #45a049;
}
.btn-secondary {
    background-color: #777;
}
.btn-secondary:hover {
    background-color: #555;
}
.section {
    background: #f9f9f9;
    padding: 20px;
    margin-bottom: 20px;
    border-radius: 4px;
    border-left: 4px solid #4CAF50;
}
.message {
    padding: 10px;
    margin: 10px 0;
    border-radius: 4px;
}
.success {
    background: #d4edda;
    color: #155724;
    border: 1px solid #c3e6cb;
}
.error {
    background: #f8d7da;
    color: #721c24;
    border: 1px solid #f5c6cb;
}
</style>
</head>
<body>
<div class="container">
    <h1>Camera Configuration</h1>
    <div id="message"></div>
    <form id="configForm">
        {form_content}
    </form>
    <button class="btn" onclick="saveConfig()">Save Configuration</button>
    <button class="btn btn-secondary" onclick="window.location.href='/'">Back to Home</button>
</div>

<script>
function saveConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    const config = {};
    
    for (let [key, value] of formData.entries()) {
        config[key] = value;
    }
    
    // Handle checkboxes
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        config[cb.name] = cb.checked ? 'true' : 'false';
    });
    
    fetch('/config/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        const msgDiv = document.getElementById('message');
        if (data.success) {
            msgDiv.innerHTML = '<div class="message success">Configuration saved successfully!</div>';
        } else {
            msgDiv.innerHTML = '<div class="message error">Error: ' + data.error + '</div>';
        }
        setTimeout(() => msgDiv.innerHTML = '', 3000);
    })
    .catch(error => {
        document.getElementById('message').innerHTML = '<div class="message error">Error: ' + error + '</div>';
    });
}
</script>
</body>
</html>
"""

FULLRES_PAGE = """\
<html>
<head>
<title>picamera2 Full Resolution</title>
<style>
body {
    margin: 0;
    padding: 20px;
    background: #000;
    text-align: center;
}
h1 {
    color: #fff;
    font-family: Arial, sans-serif;
}
img {
    max-width: 100%;
    height: auto;
    border: 2px solid #333;
}
a {
    color: #4CAF50;
    text-decoration: none;
    font-family: Arial, sans-serif;
    font-size: 16px;
}
a:hover {
    text-decoration: underline;
}
</style>
</head>
<body>
<h1>Full Resolution Video Stream</h1>
<img src="stream.mjpg" />
<br><br>
<a href="/">Back to Normal View</a>
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf[:2] + rotation_header + buf[2:]
            self.condition.notify_all()


app = Flask(__name__)
picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
output = StreamingOutput()
picam2.start_recording(MJPEGEncoder(), FileOutput(output))


@app.route('/')
def index():
    return render_template_string(PAGE)


@app.route('/fullres')
def fullres():
    return render_template_string(FULLRES_PAGE)


@app.route('/capture', methods=['POST'])
def capture():
    """
    Placeholder method for capturing a picture.
    TODO: Implement picture capture functionality
    """
    try:
        # TODO: Add your picture capture logic here
        # Example implementation:
        # 1. Stop the current stream temporarily
        # 2. Capture a high-resolution image using picam2.capture_file()
        # 3. Save to a file with timestamp
        # 4. Restart the stream
        # 5. Return success response
        
        return {'success': False, 'error': 'Capture method not yet implemented'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


@app.route('/config')
def config():
    """Display the configuration page"""
    config_file = get_config_file_path()
    config_parser = configparser.ConfigParser()
    
    try:
        config_parser.read(config_file)
    except Exception as e:
        return f"Error reading config file: {e}"
    
    # Build form HTML
    form_html = ""
    for section in config_parser.sections():
        form_html += f'<div class="section"><h2>{section}</h2>'
        for key in config_parser.options(section):
            value = config_parser[section][key]
            input_id = f"{section}_{key}"
            
            # Determine input type based on value
            if value.lower() in ('true', 'false'):
                checked = 'checked' if value.lower() == 'true' else ''
                form_html += f'''
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="{input_id}" {checked}>
                        {key}
                    </label>
                </div>
                '''
            else:
                form_html += f'''
                <div class="form-group">
                    <label for="{input_id}">{key}:</label>
                    <input type="text" id="{input_id}" name="{input_id}" value="{value}">
                </div>
                '''
        form_html += '</div>'
    
    return render_template_string(CONFIG_PAGE, form_content=form_html)


@app.route('/config/save', methods=['POST'])
def save_config():
    """Save the configuration to file"""
    try:
        data = request.get_json()
        config_file = get_config_file_path()
        config_parser = configparser.ConfigParser()
        config_parser.read(config_file)
        
        # Update configuration
        for key, value in data.items():
            # Parse section and key from "SECTION_key" format
            parts = key.split('_', 1)
            if len(parts) == 2:
                section, option = parts
                if section in config_parser.sections():
                    config_parser.set(section, option, value)
        
        # Write back to file
        with open(config_file, 'w') as f:
            config_parser.write(f)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def get_config_file_path():
    """Get the path to the config file"""
    # Check if running on Pi with /boot/cam_config.cfg
    if os.path.exists("/boot/cam_config.cfg"):
        return "/boot/cam_config.cfg"
    # Otherwise use local config
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "cam_config.cfg")


@app.route('/stream.mjpg')
def stream():
    def generate():
        try:
            while True:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                yield (b'--FRAME\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                       b'\r\n' + frame + b'\r\n')
        except Exception as e:
            logging.warning('Streaming error: %s', str(e))

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=FRAME')


if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=8000, threaded=True)
    finally:
        picam2.stop_recording()