# Deployment Configuration

All camera settings are stored in `cam_config.cfg` (INI format under the `[camera]` section). The Flask server loads this on startup and provides a web form at `/config.html` to modify settings at runtime.

## FTP/SFTP Transfer

| Setting | Default | Description |
|---------|---------|-------------|
| `ftp-mode` | `sftp` | Transfer protocol. Use `sftp` or `ftp`. |
| `ftp-server` | `ftp_server` | Hostname or IP of the FTP/SFTP server. |
| `ftp-port` | `22` | Connection port (22 for SFTP, 21 for FTP). |
| `ftp-username` | `username` | Login username. |
| `ftp-password` | `password` | Login password. |
| `ftp-destination` | `ftp_destination_list` | Comma-separated list of destination paths on the remote server. |

## Camera

| Setting | Default | Description |
|---------|---------|-------------|
| `camera_name` | `camera_name` | Identifier for this camera. Used in filenames and embedded text. No spaces — use underscores. |
| `rotation` | `0` | Camera image rotation in degrees. Must be one of: `0`, `90`, `180`, `270`. Requires server restart to apply. |
| `camera_port` | `8000` | HTTP port the Flask server listens on. |
| `camera_timezone` | `camera_timezone` | Timezone string for embedded timestamps (e.g., `America/New_York`). |
| `camera_daylight_savings` | `camera_daylight_savings` | Whether to observe daylight saving time adjustments. |
| `camera_url` | `camera_urls` | URL for the camera (used for remote access references). |

## Image Output

| Setting | Default | Description |
|---------|---------|-------------|
| `output_width` | (auto-detected) | Width in pixels of captured photos. Defaults to the camera sensor's max width. |
| `output_height` | (auto-detected) | Height in pixels of captured photos. Defaults to the camera sensor's max height. |
| `output_extension` | `extension` | Image file extension format. Accepted values: `jpg`, `jpeg`, `png`. |
| `output_quality` | `100` | JPEG quality (0-100). Higher = better quality, larger file. |
| `output_max_filesize_kb` | `0` | Maximum output file size in KB. `0` = no limit. |
| `output_folder` | `image_dir` | Local directory where captured images are saved. |
| `embed_timestamp` | `embed_timestamp` | Enable timestamp overlay on captured photos. Any value with more than 2 characters enables it (e.g., `yes`, `enabled`). |
| `file_name` | `file_name` | Base filename prefix for captured photos. |
| `text_size` | `18` | Font size (in points) for embedded text overlay. |
| `text_color` | `silver` | Color of the embedded text. Accepts PIL color names (`silver`, `white`, `black`, etc.) or hex codes. |
| `text_background` | `black` | Background color behind the text. Accepts PIL color names. |

## Timing

| Setting | Default | Description |
|---------|---------|-------------|
| `time_before_first_image` | `120` | Seconds to wait before the first scheduled capture. Set to 0 to capture immediately on startup. |
| `time_before_image` | `10` | Seconds between subsequent scheduled background captures. The server starts a background thread that captures a photo with embedded text at this interval. |

## Configuration File Example

```ini
[camera]
ftp-mode = sftp
ftp-server = 192.168.1.50
ftp-port = 22
ftp-username = camuser
ftp-password = secret123
ftp-destination = /home/camuser/pictures
camera_name = front_porch
rotation = 270
time_before_first_image = 120
time_before_image = 60
output_width = 4608
output_height = 2592
output_extension = jpg
output_quality = 100
output_max_filesize_kb = 0
output_folder = image_dir
embed_timestamp = yes
file_name = frontporch
text_size = 18
text_color = silver
text_background = black
camera_timezone = America/New_York
camera_daylight_savings = yes
camera_port = 8000
camera_url = http://camuser.dyndns.org:8000
```

## Startup

```bash
python3 flaskServer.py
```

The server listens on `http://0.0.0.0:8000` by default.

- Home page with stream and capture button: `/` or `/index.html`
- Fullscreen stream: `/full.html`
- Configuration form: `/config.html`
- Single JPEG capture: `/capture.jpg`
- Capture with embedded text: `/capture_embedded.jpg`

## Auto-start on Boot

To launch the Flask server automatically on boot, add a cron job:

```bash
crontab -e
```

Then add one of the following lines (adjust the path to match your setup):

**Without virtual environment:**
```
@reboot cd /home/pi/rPiWebcam && nohup python3 flaskServer.py >> /home/pi/rPiWebcam/flask.log 2>&1 &
```

**With virtual environment:**
```
@reboot cd /home/pi/rPiWebcam && source venv/bin/activate && nohup python3 flaskServer.py >> /home/pi/rPiWebcam/flask.log 2>&1 &
```

After reboot, check the log to verify it started:

```bash
tail -f ~/rPiWebcam/flask.log
```
