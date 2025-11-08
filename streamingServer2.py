from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
import io
from flask import Flask, Response
from threading import Thread
from time import sleep

app = Flask(__name__)

# Global camera instance
picam2 = None
encoder = None


def start_camera():
    global picam2, encoder
    picam2 = Picamera2()

    # Video config for streaming (balance res/framerate for smoothness)
    config = picam2.create_video_configuration(
        main={"size": (1280, 720)},  # 720p for web streaming
        encode="main"
    )
    picam2.configure(config)
    picam2.framerate = 15  # Lower FPS for CPU efficiency

    encoder = MJPEGEncoder(quality=85)  # JPG quality 1-100
    picam2.start_encoder(encoder, stream)  # Stream to global buffer
    picam2.start()
    print("MJPEG stream started on http://<pi-ip>:8000/stream.mjpg")


# Global stream buffer
stream = io.BytesIO()


def generate_frames():
    while True:
        if picam2 and picam2.started:
            stream.seek(0)
            stream.truncate(0)
            picam2.wait_all_requests()  # Ensure frame ready
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + stream.getvalue() + b'\r\n')
        sleep(0.1)


@app.route('/stream.mjpg')
def stream_mjpg():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    # Start camera in thread
    cam_thread = Thread(target=start_camera)
    cam_thread.start()
    sleep(2)  # Let camera init

    # Start Flask server
    app.run(host='0.0.0.0', port=8000, threaded=True)