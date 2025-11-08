from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
import io
from flask import Flask, Response, render_template_string
from threading import Thread
from time import sleep

app = Flask(__name__)

# Global camera instance
picam2 = None
encoder = None

# Global stream buffer
stream = io.BytesIO()


def start_camera():
    global picam2, encoder
    picam2 = Picamera2()

    # Video config for streaming (720p example; adjust as needed)
    config = picam2.create_video_configuration(
        main={"size": (1280, 720)},
        encode="main"
    )
    picam2.configure(config)
    picam2.framerate = 15  # Adjust for smoothness vs. CPU load

    # encoder = MJPEGEncoder(quality=85)  # JPG quality 1-100
    encoder = MJPEGEncoder()  # JPG quality 1-100
    picam2.start_encoder(encoder, stream)
    picam2.start()
    print("MJPEG stream ready. Access at http://<pi-ip>:8000/")


def generate_frames():
    while True:
        if picam2 and picam2.started:
            stream.seek(0)
            stream.truncate(0)
            picam2.wait_all_requests()  # Wait for frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + stream.getvalue() + b'\r\n')
        sleep(0.1)  # Frame rate control


@app.route('/stream.mjpg')
def stream_mjpg():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    # Simple HTML template with embedded stream (inline for no file needed)
    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Pi Camera Stream</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; background: #f0f0f0; }
            #stream { max-width: 100%; height: auto; border: 2px solid #333; margin: 20px; }
            h1 { color: #333; }
        </style>
    </head>
    <body>
        <h1>Live Raspberry Pi Camera Stream</h1>
        <img id="stream" src="/stream.mjpg" alt="Live Video Stream">
        <p>Embedded MJPEG stream from Picamera2. Refresh page to restart if needed.</p>
    </body>
    </html>
    '''
    return render_template_string(html_template)


if __name__ == '__main__':
    # Start camera in thread
    cam_thread = Thread(target=start_camera)
    cam_thread.start()
    sleep(2)  # Let camera initialize

    # Start Flask server
    app.run(host='0.0.0.0', port=8000, threaded=True, debug=False)