from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder  # Changed from MJPEGEncoder
from picamera2.outputs import Output
import io
from flask import Flask, Response, render_template_string
from threading import Thread
from time import sleep
import libcamera  # Optional: for transform

app = Flask(__name__)

# Global camera instance
picam2 = None
encoder = None
stream_buffer = None


class MjpegOutput(Output):
    """Custom Output that writes MJPEG frames to a BytesIO buffer."""

    def __init__(self, buffer):
        super().__init__()
        self.buffer = buffer

    def output(self, request):
        """Called when a frame is ready; appends JPG to buffer."""
        if request.completed_requests:
            # Get the encoded buffer (bytes) from the request
            encoded_data = request.completed_requests[0].buffers()[0].planes()[0].readable().tobytes()
            self.buffer.write(encoded_data)
            self.buffer.seek(0)  # Reset for reading


def start_camera():
    global picam2, encoder, stream_buffer
    picam2 = Picamera2()

    # Video config for streaming (720p example; adjust as needed)
    config = picam2.create_video_configuration(
        main={"size": (1280, 720)},
        encode="main"
    )
    # Optional: Add rotation
    # config.transform = libcamera.Transform(hflip=1, vflip=1)
    picam2.configure(config)
    picam2.framerate = 10  # Adjust for smoothness vs. CPU load

    # Create BytesIO buffer and custom output
    stream_buffer = io.BytesIO()
    mjpeg_out = MjpegOutput(stream_buffer)

    # Use JpegEncoder with direct quality (1-100); no 'quality' kwarg needed later
    encoder = JpegEncoder(q=85, num_threads=4)  # q=85 for your desired quality; threads for speed
    picam2.start_encoder(encoder, mjpeg_out)  # No extra quality param
    picam2.start()
    print("MJPEG stream ready (using JpegEncoder). Access at http://<pi-ip>:8000/")


def generate_frames():
    while True:
        if picam2 and picam2.started and stream_buffer:
            stream_buffer.seek(0)
            data = stream_buffer.read()  # Read current frame
            if data:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
        sleep(0.1)  # Frame rate control


@app.route('/stream.mjpg')
def stream_mjpg():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    # Simple HTML template with embedded stream
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
        <p>Embedded MJPEG stream from Picamera2 (JpegEncoder). Refresh if needed.</p>
    </body>
    </html>
    '''
    return render_template_string(html_template)


if __name__ == '__main__':
    # Start camera in thread
    cam_thread = Thread(target=start_camera)
    try:
        cam_thread.start()
    except RuntimeError as e:
        print(e)
    sleep(2)  # Let camera initialize

    # Start Flask server
    app.run(host='0.0.0.0', port=8000, threaded=True, debug=False)