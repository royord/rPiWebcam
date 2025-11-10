# https://github.com/garyexplains/examples/blob/master/RPiCameraPython/mjpeg_cam.py
import io
import picamera2
from picamera2.encoders import MJPEGEncoder
import libcamera
import logging
import socketserver
from threading import Condition
from http import server
import http


def streaming():
    # res_set = '640x480'
    # res_set = '1280x960'
    res_set = '4056x3040'
    res_x = res_set.split('x')[0]
    res_y = res_set.split('x')[1]

    FOCUS_PAGE=f"""\
    <html>
    <head>
    <title>PiCamera Image Preview</title>
    </head>
    <body>
    <h1>PiCamera Image Preview</h1><br>
    <img src="stream.mjpg" width="{res_x}" height="{res_y}" /><br>
    <a href="index.html">Home</a>
    </body>
    </html>
    """

    PAGE="""\
    <html>
    <head>
    <title>PiCamera Image Preview</title>
    </head>
    <body>
    <h1>PiCamera Image Preview</h1><br>
    <img src="stream.mjpg" width="640" height="480" /><br>
    <a href="focus.html">Click here to focus</a>
    </body>
    </html>
    """
    
    class StreamingOutput(object):
        def __init__(self):
            self.frame = None
            self.buffer = io.BytesIO()
            self.condition = Condition()
    
        def write(self, buf):
            if buf.startswith(b'\xff\xd8'):
                # New frame, copy the existing buffer's content and notify all
                # clients it's available
                self.buffer.truncate()
                with self.condition:
                    self.frame = self.buffer.getvalue()
                    self.condition.notify_all()
                self.buffer.seek(0)
            return self.buffer.write(buf)
    
    class StreamingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(301)
                self.send_header('Location', '/index.html')
                self.end_headers()
            elif self.path == '/index.html':
                content = PAGE.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == '/focus.html':
                content = FOCUS_PAGE.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == '/stream.mjpg':
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                self.end_headers()
                try:
                    while True:
                        with output.condition:
                            output.condition.wait()
                            frame = output.frame
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                except Exception as e:
                    logging.warning(
                        'Removed streaming client %s: %s',
                        self.client_address, str(e))
            else:
                self.send_error(404)
                self.end_headers()
    
    class StreamingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True
    
    # 4 fps = 6 Mbps
    #24 fps = 18 Mbps
    with picamera2.Picamera2() as camera:
        config = camera.create_video_configuration(
            # 4056x3040
            main={"size": (4056, 3040)},  # HD resolution (adjust to supported)
            lores={"size": (640, 480)},  # Optional low-res for faster preview
            encode="lores"  # Stream preview from lores for smoothness
        )

        camera.configure(config)
        camera.framerate = 24

        # camera.rotation = 180
        # output = StreamingOutput()
        try:
            # camera.start_recording(output, format='mjpeg')
            encoder = MJPEGEncoder(quality=85)  # JPG quality 1-100
            camera.start_encoder(encoder, stream)  # Stream to global buffer
            camera.start()
        except Exception as ex:
            print(f"Error capturing camera:\n {ex}")
        try:
            # address = ('', 8000)
            address = ('', 80)
            server = StreamingServer(address, StreamingHandler)
            server.serve_forever()
            print("starting deamon")
            # s = threading.Thread(target=server.serve_forever())
            # s = threading.Thread(target=server.serve_forever)
            # s.daemon = True
            # s.start()
            print("deamon started")
        except Exception as ex:
            print(f"exception starting deamon:\n {ex}")
        finally:
            camera.stop_recording()
    return
            
streaming()
# time.sleep(10000)

