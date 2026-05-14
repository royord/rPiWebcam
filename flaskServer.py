#!/usr/bin/python3

# Rewritten with Flask: MJPEG streaming server using Picamera2.
# Dynamically detects max supported video size from camera sensor modes.
# Added: Configuration page (/config.html) to set rotation; saves/loads from 'config.ini' using ConfigParser.
# On startup, loads rotation from file (default 270 if missing).
# Capture photo button on index page; fetches /capture.jpg and displays below stream.
# Routes: / (redirect to /index.html), /index.html (HTML page with capture button), /full.html (fullscreen stream page), /stream.mjpg (multipart stream), /capture.jpg (single JPEG capture), /config.html (config form), /save_config (POST to save rotation).
# Supports rotation via libcamera Transform.
# Fix: Simplified get_max_video_size() to handle SensorMode dict structure; removed format description access to avoid AttributeError (format is str, not dict with 'description').

import html
import io
import logging
import configparser
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from threading import Condition, Thread, Event
from flask import Flask, Response, redirect, request, render_template
from io import BytesIO
from flask import send_file
import sys
import requests
import netifaces as ni
import suncalc
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
    'capture_mode': 'interval',
    'time_before_image': '10',
    'time_before_first_image': '120',
    'timed_schedule': '[]',
    'sunrise_offset': '30',
    'sunset_offset': '-60',
    'lat': '51.5',
    'lon': '-0.1',
    'grid_square': '',
    'output_width': None,
    'output_height': None,
    'output_extension': 'extension',
    'output_quality':'100',
    'output_filetype':'jpg',
    'output_max_filesize_kb':0,
    'output_folder':'image_dir',
    'embed_timestamp': 'embed_timestamp',
    'embed_camera_name': 'embed_camera_name',
    'archive_retention_days': '30',
    'reserved_space_gb': '5',
    '_bg_restart_event': None,
    '_last_cleanup_time': 0,
    '_last_time_sync': 0,
    'file_name': 'file_name',
    'text_size': '18',
    'text_color': 'silver',
    'text_background': 'black',
    'camera_timezone': 'camera_timezone',
    'camera_daylight_savings': 'camera_daylight_savings',
    'camera_port': '8000',
    'camera_url': 'camera_urls',
    'rtc_error_count': '0',
    'rtc_last_error': 'Never'
}

def load_config():
    """Load rotation from config file; default to 270."""
    configs = {}

    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if config.has_section('camera') and config.has_option('camera', 'rotation'):
            for key, value in config.items('camera'):
                # Convert 'true'/'false' strings to actual booleans for checkbox fields
                if key in ('embed_timestamp', 'embed_camera_name', 'camera_daylight_savings'):
                    if value.lower() == 'true':
                        value = True
                    elif value.lower() == 'false':
                        value = False
                configs[key] = value
                # print("Current config: ", key, " = ", value)

    for key, value in default_config.items():
        if key not in globals():
            globals()[key] = value

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
    """Save config values to INI file."""
    config = configparser.ConfigParser()
    config.add_section('camera')
    try:
        for key, value in rotation.items():
            # Convert booleans and non-strings to 'true'/'false' or str for INI storage
            if isinstance(value, bool):
                strval = 'true' if value else 'false'
            else:
                strval = str(value)
            config.set('camera', key, strval)
            globals()[key] = value
        globals().update(rotation)
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)
    except Exception as e:
        print(f"Error saving config: {e}")
        import traceback
        traceback.print_exc()

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

# Lazy camera detection: try to query sensor modes at import time,
# fall back to defaults if the camera is unavailable.
NATIVE_SIZE = None
try:
    _picam2_detect = Picamera2()
    NATIVE_SIZE = get_max_video_size(_picam2_detect)
    _picam2_detect.close()
except Exception as e:
    print(f"Camera detection failed ({e}) — using fallback defaults")
    NATIVE_SIZE = (2592, 1944)  # 5MP common HQ camera fallback

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
    transform = Transform(transpose=1, vflip=1)
elif ROTATION == 270:
    transform = Transform(transpose=1, hflip=1)
else:
    raise ValueError("Unsupported rotation; use 0, 90, 180, or 270")

# Module-level camera instance (initialised in __main__ block)
picam2 = None


def connection_check(interface):
    """Check network interface has internet connectivity. Returns IP or False."""
    try:
        if interface not in ni.interfaces():
            return False
        ip = ni.ifaddresses(interface)[ni.AF_INET][0]['addr']
        if len(ip) <= 7:
            return False
        print(f'{interface} IP address: {ip}')
        requests.head('http://google.com', timeout=5)
        print("Internet connection confirmed")
        return ip
    except Exception as ex:
        print(f"Connection check failed for {interface}: {ex}")
        return False


def get_interface_ip():
    """Auto-detect a network interface with internet connectivity. Returns (interface, ip) or (None, None)."""
    gateways = ni.gateways()
    # First check the default gateway interface
    try:
        default_gw = gateways[999][0][0]  # default route interface
    except (KeyError, IndexError):
        default_gw = None

    # Try the default gateway interface first, then all others
    candidates = []
    if default_gw:
        candidates.append(default_gw)
    for iface in ni.interfaces():
        if iface not in ('lo',) and iface not in candidates:
            candidates.append(iface)

    for iface in candidates:
        ip = connection_check(iface)
        if ip:
            print(f"Using {iface} connection (IP: {ip})")
            return iface, ip
    return None, None


def update_rtc_time():
    """Update the hardware clock from the internet via timedatectl.
    Detects if RTC is >2 hours behind and tracks errors."""
    # Throttle: don't sync more than once per hour
    last = globals().get('_last_time_sync', 0)
    now = time.time()
    if now - last < 3600:
        return
    globals()['_last_time_sync'] = now

    try:
        # Re-enable NTP sync via systemd (most reliable on modern Raspberry Pi OS)
        result = os.system("sudo timedatectl set-ntp 1 2>/dev/null")
        if result == 0:
            print("NTP sync triggered via timedatectl")
        else:
            print("timedatectl set-ntp 1 failed, trying systemd-timesyncd")
            os.system("sudo systemctl restart systemd-timesyncd 2>/dev/null")
        # Wait for systemd to sync, then write to hwclock
        time.sleep(3)

        # Before writing, read the current RTC time and compare with system time
        rtc_drift_detected = False
        try:
            r = subprocess.run(['sudo', 'hwclock', '-r'], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                rtc_line = r.stdout.strip().split('\n')[-1].strip()
                # hwclock -r output: "Wed 14 May 2025 10:30:00 AM UTC" or similar
                # Try multiple formats
                for fmt in ('%a %d %b %Y %I:%M:%S %p %Z', '%a %b %d %H:%M:%S %Z %Y',
                            '%a %b %d %H:%M:%S UTC %Y', '%a %b %d %H:%M:%S %Y'):
                    try:
                        rtc_time = datetime.strptime(rtc_line, fmt)
                        sys_time = datetime.now()
                        drift = abs((sys_time - rtc_time).total_seconds())
                        if drift > 7200:
                            # RTC error tracking
                            err_count = int(globals().get('rtc_error_count', 0)) + 1
                            globals()['rtc_error_count'] = str(err_count)
                            globals()['rtc_last_error'] = sys_time.strftime('%Y-%m-%d %H:%M:%S')
                            print(f"RTC drift detected: {drift:.0f}s ({drift/3600:.1f}h) — error #{err_count}")
                            rtc_drift_detected = True
                        else:
                            print(f"RTC drift: {drift:.0f}s — OK")
                        break
                    except ValueError:
                        continue
        except Exception:
            pass  # No RTC or hwclock error, skip drift check

        result = os.system("sudo hwclock -w 2>/dev/null")
        if result == 0:
            print("Hardware clock updated")
        else:
            print("hwclock -w failed (no RTC hardware?)")

        if rtc_drift_detected:
            print("WARNING: RTC battery may be dead or failing — RTC was >2 hours behind system time")
    except Exception as ex:
        print(f"Time sync error: {ex}")


def periodic_time_sync():
    """Background thread: sync time hourly."""
    while True:
        time.sleep(3600)
        try:
            if requests.head('http://google.com', timeout=5).status_code == 200:
                update_rtc_time()
        except Exception:
            pass  # No internet, skip this cycle


def grid_square_to_latlon(gs):
    """Convert Maidenhead grid square to (lat, lon).
    Supports 2, 4, or 6 char grids (e.g. 'IO91' -> ~51.5, -0.1).
    Returns (lat, lon) or None on invalid input.
    """
    gs = gs.strip().upper()
    if len(gs) < 2 or len(gs) not in (2, 4, 6):
        return None
    if not all(c.isalpha() for c in gs[0:2]) or not all(c.isdigit() for c in gs[2:4]):
        return None

    # Field (2 chars): 20° x 10°
    field_e = ord(gs[0]) - ord('A')  # 0-17
    field_w = ord(gs[1]) - ord('A')  # 0-17
    lon = -180 + field_e * 20
    lat = -90 + field_w * 10

    if len(gs) >= 4:
        # Subfield (2 digits): 2° x 1°
        sub_e = int(gs[2])  # 0-9
        sub_w = int(gs[3])  # 0-9
        lon += sub_e * 2
        lat += sub_w * 1

    if len(gs) >= 6:
        # Extended field (2 chars): 5' x 2.5'
        ext_e = ord(gs[4]) - ord('A')  # 0-23
        ext_w = ord(gs[5]) - ord('A')  # 0-23
        lon += ext_e * (5.0 / 60.0)
        lat += ext_w * (2.5 / 60.0)

    return (lat, lon)


class UnifiedScheduler:
    """Replaces background_capture_task. Supports interval, timed, and sunrise/sunset modes."""

    def __init__(self, restart_event):
        self.restart_event = restart_event
        self._last_captured = set()  # set of "key_date" strings to prevent duplicates

    def _should_capture(self, key, date_str):
        tag = f"{key}_{date_str}"
        if tag in self._last_captured:
            return False
        self._last_captured.add(tag)
        return True

    def _check_timed(self, now, today):
        try:
            times = json.loads(globals().get('timed_schedule', '[]'))
            current_hm = now.strftime('%H:%M')
            for t in times:
                if t == current_hm and self._should_capture(f'timed_{t}', today):
                    print(f"Timed capture at {t}")
                    do_capture_embedded()
        except Exception as e:
            print(f"Timed schedule error: {e}")

    def _check_sunrise_sunset(self, now, today):
        try:
            gs = globals().get('grid_square', '')
            if gs:
                result = grid_square_to_latlon(gs)
                if result is None:
                    print(f"Invalid grid square: {gs}")
                    return
                lat, lon = result
            else:
                try:
                    lat = float(globals().get('lat', '51.5'))
                    lon = float(globals().get('lon', '-0.1'))
                except ValueError:
                    lat, lon = 51.5, -0.1

            tz_name = globals().get('camera_timezone', '')
            sunrise_off = int(globals().get('sunrise_offset', '30'))
            sunset_off = int(globals().get('sunset_offset', '-60'))

            # suncalc returns UTC times
            times = suncalc.get_times(now, lat, lon)
            sunrise_utc = times['sunrise']
            sunset_utc = times['sunset']

            # Convert to local timezone
            if tz_name:
                try:
                    import zoneinfo
                    tz = zoneinfo.ZoneInfo(tz_name)
                    sunrise_dt = sunrise_utc.replace(tzinfo=zoneinfo.utc).astimezone(tz)
                    sunset_dt = sunset_utc.replace(tzinfo=zoneinfo.utc).astimezone(tz)
                except Exception:
                    sunrise_dt = sunrise_utc
                    sunset_dt = sunset_utc
            else:
                sunrise_dt = sunrise_utc
                sunset_dt = sunset_utc

            target_sr = sunrise_dt + timedelta(minutes=sunrise_off)
            target_ss = sunset_dt + timedelta(minutes=sunset_off)

            # Capture if within a 2-minute window of the target time
            now_naive = datetime.now()
            if abs((now_naive - target_sr).total_seconds()) < 120 and self._should_capture('sr', today):
                print(f"Sunrise capture at ~{target_sr.strftime('%H:%M')}")
                do_capture_embedded()
            if abs((now_naive - target_ss).total_seconds()) < 120 and self._should_capture('ss', today):
                print(f"Sunset capture at ~{target_ss.strftime('%H:%M')}")
                do_capture_embedded()
        except Exception as e:
            print(f"Sunrise/sunset schedule error: {e}")

    def tick(self):
        """Called every 30 seconds. Check if capture should fire."""
        mode = globals().get('capture_mode', 'interval')
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')

        if mode == 'interval':
            # Interval mode is handled by the existing background_capture_task
            return
        elif mode == 'timed':
            self._check_timed(now, today)
        elif mode == 'sunrise_sunset':
            self._check_sunrise_sunset(now, today)


def scheduler_loop(scheduler):
    """Main loop for the UnifiedScheduler — checks every 30 seconds."""
    while True:
        time.sleep(30)
        if scheduler.restart_event and scheduler.restart_event.is_set():
            print("Scheduler: config changed, restarting...")
            scheduler.restart_event.clear()
            # Refresh the globals after a restart
            load_config()
        try:
            scheduler.tick()
        except Exception as e:
            print(f"Scheduler tick error: {e}")


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            logging.debug(f"New frame written: {len(buf)} bytes")
            self.condition.notify_all()

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
app = Flask(__name__, template_folder='templates')

# Global output instance
output = StreamingOutput()

@app.template_filter('is_true')
def is_true(value):
    """Jinja2 filter: returns True for truthy values (bool True or string 'true'/'True')."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', '1', 'yes')

def _tmpl_context():
    """Pass all globals as template context variables with hyphenated keys."""
    c = dict(globals())
    # Map hyphenated config keys to underscored versions for template use
    c['ftp_mode'] = c.get('ftp-mode', '')
    c['ftp_server'] = c.get('ftp-server', '')
    c['ftp_port'] = c.get('ftp-port', '')
    c['ftp_username'] = c.get('ftp-username', '')
    c['ftp_password'] = c.get('ftp-password', '')
    c['ftp_destination'] = c.get('ftp-destination', '')
    return c


def _get_storage_info():
    """Compute current disk usage info. Returns dict with pct, free_gb, total_gb."""
    script_dir = os.path.dirname(__file__)
    output_dir = os.path.join(script_dir, globals().get('output_folder', 'image_dir'))
    try:
        usage = shutil.disk_usage(output_dir)
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)
        pct = round(usage.used / usage.total * 100) if usage.total > 0 else 0
    except Exception:
        free_gb = 0
        total_gb = 0
        pct = 0
    return {'pct': pct, 'free_gb': free_gb, 'total_gb': total_gb}


@app.route('/')
def index_redirect():
    return redirect('/index.html', code=301)


@app.route('/index.html')
def index():
    return render_template('index.html', rotation=ROTATION)


@app.route('/full.html')
def full():
    return render_template('full.html', rotation=ROTATION)


@app.route('/config.html')
def config():
    ctx = _tmpl_context()
    ctx['rotation'] = ROTATION
    si = _get_storage_info()
    ctx['pct'] = si['pct']
    ctx['free_gb'] = si['free_gb']
    ctx['total_gb'] = si['total_gb']
    return render_template('config.html', **ctx)


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
    old_first_image_delay = globals().get('time_before_first_image', '0')
    new_first_image_delay = config_key_value.get('time_before_first_image', old_first_image_delay)
    old_image_delay = globals().get('time_before_image', '10')
    new_image_delay = config_key_value.get('time_before_image', old_image_delay)
    old_capture_mode = globals().get('capture_mode', 'interval')
    new_capture_mode = config_key_value.get('capture_mode', old_capture_mode)

    # Only validate transfer fields if the transfer tab is being saved
    active_tab = config_key_value.get('_active_tab', 'camera')
    is_transfer_tab = active_tab == 'transfer'

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
        elif key == "ftp-server":
            if is_transfer_tab and value in ('ftp_server', 'ftp_server2', 'camera_url', ''):
                error_text += f"Invalid ftp-server: {value}. Please enter a valid server hostname or IP address.\n"
        elif key == "archive_retention_days":
            if not value.isnumeric() or int(value) < 1:
                error_text += f"Invalid archive_retention_days: {value}. Must be a positive integer.\n"
        elif key == "reserved_space_gb":
            if not value.replace('.', '', 1).isnumeric() or float(value) < 0.5:
                error_text += f"Invalid reserved_space_gb: {value}. Must be at least 0.5.\n"
        elif key == "capture_mode":
            if value not in ('interval', 'timed', 'sunrise_sunset'):
                error_text += f"Invalid capture_mode: {value}. Must be interval, timed, or sunrise_sunset.\n"
        elif key == "sunrise_offset":
            if not value.isnumeric():
                error_text += f"Invalid sunrise_offset: {value}. Must be an integer.\n"
        elif key == "sunset_offset":
            if not value.isnumeric():
                error_text += f"Invalid sunset_offset: {value}. Must be an integer.\n"
        elif key == "timed_schedule":
            try:
                times = json.loads(value)
                if not isinstance(times, list):
                    error_text += f"Invalid timed_schedule: must be a JSON array.\n"
                else:
                    for t in times:
                        if not isinstance(t, str) or len(t) != 5 or t[2] != ':':
                            error_text += f"Invalid time in timed_schedule: {t}. Format: HH:MM.\n"
            except json.JSONDecodeError:
                error_text += f"Invalid timed_schedule: not valid JSON.\n"
        elif key == "lat":
            if not value.replace('.', '', 1).isnumeric() or not -90 <= float(value) <= 90:
                error_text += f"Invalid lat: must be between -90 and 90.\n"
        elif key == "lon":
            if not value.replace('.', '', 1).isnumeric() or not -180 <= float(value) <= 180:
                error_text += f"Invalid lon: must be between -180 and 180.\n"

    if len(error_text) > 0:
        return error_text, 400
    else:
        try:
            save_config(config_key_value)
        except Exception as e:
            print(f"save_config error: {e}")
            import traceback
            traceback.print_exc()
            return f"Error saving config: {e}", 500
        if old_first_image_delay != new_first_image_delay:
            print(f"time_before_first_image changed from {old_first_image_delay} to {new_first_image_delay} — signaling background capture to restart timer...")
            restart = globals().get('_bg_restart_event')
            if restart is not None:
                restart.set()
        if old_image_delay != new_image_delay:
            print(f"time_before_image changed from {old_image_delay} to {new_image_delay} — signaling background capture...")
            restart = globals().get('_bg_restart_event')
            if restart is not None:
                restart.set()
        if new_capture_mode != old_capture_mode:
            print(f"Capture mode changed from {old_capture_mode} to {new_capture_mode} — signaling scheduler restart...")
            restart = globals().get('_bg_restart_event')
            if restart is not None:
                restart.set()
        if int(new_rotation_str) != old_rotation:
            reconfigure_camera()
        if new_port != old_port:
            print(f"Port changed from {old_port} to {new_port} — restarting server...")
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--restart-port', new_port])
        return '', 200


@app.route('/rtc_status')
def rtc_status():
    """Return RTC error status as JSON."""
    return {
        'error_count': int(globals().get('rtc_error_count', 0)),
        'last_error': globals().get('rtc_last_error', 'Never'),
        'has_warning': int(globals().get('rtc_error_count', 0)) > 0
    }


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
                if key in ('embed_timestamp', 'embed_camera_name', 'camera_daylight_savings'):
                    if value == 'True':
                        value = True
                    elif value == 'False':
                        value = False
                globals()[key] = value
        globals().update({k: v for k, v in _cfg.items('camera')
                         if k not in ('embed_timestamp', 'embed_camera_name', 'camera_daylight_savings')})
        # Restart if port changed
        new_port = _cfg.get('camera', 'camera_port', fallback='8000')
        if new_port and new_port != str(globals().get('camera_port', '8000')):
            globals()['camera_port'] = new_port
            print(f"Port changed from {globals().get('camera_port', '8000')} to {new_port} — restarting server...")
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--restart-port', new_port])
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


def _cleanup_images_throttled():
    """Run cleanup only if more than 300s have passed since last check."""
    last = globals().get('_last_cleanup_time', 0)
    now = time.time()
    if now - last < 300:
        return
    globals()['_last_cleanup_time'] = now
    result = cleanup_images()
    if result['deleted'] > 0:
        print(f"Auto-cleanup: {result['deleted']} image(s) deleted, {result['freed_bytes']/(1024*1024):.1f} MB freed.")


def cleanup_images():
    """
    Clean up image files in the output folder.
    1. Hard limit: always keep at least 10% of the drive free
    2. Respect the user's reserved_space_gb setting
    3. Delete oldest files first
    4. Never delete files newer than archive_retention_days
    """
    script_dir = os.path.dirname(__file__)
    output_dir = os.path.join(script_dir, globals().get('output_folder', 'image_dir'))
    if not os.path.isdir(output_dir):
        return {'deleted': 0, 'freed_bytes': 0, 'reason': 'no output dir'}

    retention_days = max(int(globals().get('archive_retention_days', '30')), 1)
    reserved_gb = max(float(globals().get('reserved_space_gb', '5')), 1)

    usage = shutil.disk_usage(output_dir)
    total = usage.total
    free = usage.free

    # Hard limit: always keep 10% free
    hard_limit_free = total * 0.10
    # User setting: always keep at least reserved_gb free
    effective_free_target = max(hard_limit_free, reserved_gb * (1024 ** 3))

    if free >= effective_free_target:
        return {'deleted': 0, 'freed_bytes': 0, 'reason': 'enough space'}

    # We need to free up space. Calculate how much.
    space_to_free = free - effective_free_target  # negative means we're over budget
    if space_to_free >= 0:
        return {'deleted': 0, 'freed_bytes': 0, 'reason': 'enough space'}

    bytes_to_free = abs(space_to_free)

    # Gather image files with their age and size
    now = time.time()
    retention_seconds = retention_days * 86400
    eligible_files = []

    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png'):
            continue
        try:
            mtime = os.path.getmtime(fpath)
            age = now - mtime
            if age < retention_seconds:
                continue  # Don't delete files within retention period
            fsize = os.path.getsize(fpath)
            eligible_files.append((fpath, fname, mtime, age, fsize))
        except OSError:
            continue

    # Sort by age descending (oldest first)
    eligible_files.sort(key=lambda x: x[3], reverse=True)

    deleted = 0
    freed = 0

    for fpath, fname, mtime, age, fsize in eligible_files:
        if freed >= bytes_to_free:
            break
        try:
            os.remove(fpath)
            deleted += 1
            freed += fsize
            print(f"Archive cleanup: deleted {fname} (age: {age/86400:.1f}d, size: {fsize/(1024*1024):.1f}MB)")
        except OSError as ex:
            print(f"Archive cleanup: failed to delete {fname}: {ex}")

    return {'deleted': deleted, 'freed_bytes': freed, 'reason': 'cleanup triggered'}


@app.route('/cleanup_disk')
def cleanup_disk():
    """Trigger disk cleanup and return results as JSON."""
    result = cleanup_images()
    return '{{"deleted":{d},"freed_bytes":{f},"reason":"{r}"}}'.format(
        d=result['deleted'], f=result['freed_bytes'], r=result['reason']
    ), 200, {'Content-Type': 'application/json'}


@app.route('/disk_usage')
def disk_usage():
    """Return disk usage info for the output folder."""
    script_dir = os.path.dirname(__file__)
    output_dir = os.path.join(script_dir, globals().get('output_folder', 'image_dir'))
    usage = shutil.disk_usage(output_dir)
    used_gb = usage.used / (1024**3)
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    pct = (usage.used / usage.total * 100) if usage.total > 0 else 0

    # Count total images and total archive size
    total_images = 0
    archive_images = 0
    if os.path.isdir(output_dir):
        now = time.time()
        retention_days = max(int(globals().get('archive_retention_days', '30')), 1)
        retention_seconds = retention_days * 86400
        for fname in os.listdir(output_dir):
            if os.path.splitext(fname)[1].lower() in ('.jpg', '.jpeg', '.png'):
                total_images += 1
                mtime = os.path.getmtime(os.path.join(output_dir, fname))
                if now - mtime >= retention_seconds:
                    archive_images += 1

    return '{{"total_gb":{total_gb:.1f},"used_gb":{used_gb:.1f},"free_gb":{free_gb:.1f},"percent":{pct:.0f},"total_images":{total_images},"archive_images":{archive_images}}}'.format(
        total_gb=total_gb, used_gb=used_gb, free_gb=free_gb, pct=pct,
        total_images=total_images, archive_images=archive_images
    ), 200, {'Content-Type': 'application/json'}


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

def do_capture_embedded():
    """Core capture logic: capture photo, embed text, save to disk, FTP transfer.
    Called by both /capture_embedded.jpg route and background scheduler."""
    print("Capturing photo with embedded text...")
    _cleanup_images_throttled()
    script_dir = os.path.dirname(__file__)
    file_prefix = globals().get('file_name', globals()['camera_name'])
    photo_buffer = BytesIO()
    picam2.capture_file(photo_buffer, name="main", format="jpeg")
    photo_buffer.seek(0)

    background = Image.open(photo_buffer)
    img_text = create_embed_text()
    if img_text is not None:
        background.paste(img_text, (0, 0))

    output_buffer = BytesIO()
    background.save(output_buffer, format="jpeg", quality=100)
    output_buffer.seek(0)

    output_dir = os.path.join(script_dir, globals().get('output_folder', 'image_dir'))
    os.makedirs(output_dir, exist_ok=True)
    file_name = os.path.join(output_dir, f"{file_prefix}_{file_date_string()}.jpg")
    background.save(file_name, format="jpeg")

    # FTP transfer to each destination
    ftp_dest = globals().get('ftp-destination', '')
    ftp_mode = globals().get('ftp-mode', 'sftp').lower()
    for dest in ftp_dest.split(','):
        dest = dest.strip()
        if not dest:
            continue
        remote_name = file_prefix + '_' + file_date_string() + '.jpg'
        if dest.endswith('/'):
            remote_path = dest + remote_name
        else:
            remote_path = dest.rstrip('/') + '/' + remote_name
        print(f"Transferring: {file_name} -> {remote_path}")
        try:
            ft.FileTransfer(
                globals()['ftp-server'],
                globals()['ftp-username'],
                globals()['ftp-password'],
                ftp_mode.upper(),
                file_name,
                remote_path,
                globals()['ftp-port'],
            )
        except Exception as ex:
            print(f"FTP transfer failed: {ex}")

    return output_buffer.getvalue()

@app.route('/capture_embedded.jpg')
def capture_embedded_photo():
    """Capture a photo and return it as JPEG response."""
    return Response(do_capture_embedded(), mimetype='image/jpeg')

def background_capture_task(delay):
    restart_event = globals().get('_bg_restart_event')
    first = True
    while True:
        try:
            # If delay > 0, apply the configured delay
            if delay > 0:
                # Check for restart signal (time_before_first_image changed)
                if restart_event is not None and first and restart_event.is_set():
                    restart_event.clear()
                    print(f"Background capture: restarting timer (new time_before_first_image)...")

                # Use time_before_first_image on the first capture, then time_before_image
                if first:
                    wait = int(globals().get('time_before_first_image', '0'))
                    if wait > 0:
                        print(f"Waiting {wait}s before first capture...")
                        total = 0
                        while total < wait:
                            if restart_event is not None and restart_event.is_set():
                                print("Background capture: config changed, restarting wait...")
                                restart_event.clear()
                                total = 0
                                wait = int(globals().get('time_before_first_image', '0'))
                                if wait > 0:
                                    print(f"Restarted: waiting {wait}s before first capture...")
                                continue
                            time.sleep(1)
                            total += 1
                            if total % 10 == 0:
                                print(f"Waiting {wait - total}s before first capture...")
                    first = False
                else:
                    total_delayed = 0
                    while total_delayed < delay:
                        if restart_event is not None and restart_event.is_set():
                            print("Background capture: config changed, restarting...")
                            restart_event.clear()
                            total_delayed = 0
                            first = True
                            delay = int(globals().get('time_before_image', '10'))
                            continue
                        time.sleep(1)
                        total_delayed += 1
                        if total_delayed % 10 == 0:
                            print(f"Background thread sleeping for {total_delayed} seconds...")
            do_capture_embedded()
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
    script_dir = os.path.dirname(__file__)
    camera_name = globals()['camera_name'] if globals().get('embed_camera_name') is True else ''
    if globals().get('embed_timestamp') is True:
        camera_name = camera_name + (' - ' if camera_name else '') + cam_time()
    unicode_text = camera_name
    if not unicode_text:
        return None

    # sample text and font
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
    try:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"size": (WIDTH, HEIGHT)},
            transform=transform
        )
        picam2.configure(config)
        # Start recording to output
        # picam2.start_recording(JpegEncoder(q=85), FileOutput(output))
        picam2.start_recording(JpegEncoder(q=60), FileOutput(output))
        print(f"Camera initialised: {WIDTH}x{HEIGHT} rotated {ROTATION}°")
    except Exception as e:
        print(f"WARNING: Camera failed to initialise ({e})")
        print("Flask server will start but streaming/capture will not work")
        picam2 = None

    # Network detection and initial time sync
    iface, ip = get_interface_ip()
    if ip:
        print(f"Network ready: {iface} ({ip}) — syncing time")
        update_rtc_time()
    else:
        print("No internet connection detected yet — time sync will happen when connected")

    # Start periodic hourly time sync
    time_sync_thread = Thread(target=periodic_time_sync, daemon=True)
    time_sync_thread.start()

    print(f"Server starting on http://0.0.0.0:{globals()['camera_port']} (local: http://localhost:{globals()['camera_port']})")
    print(f"Streaming rotated {ROTATION}° video at {WIDTH}x{HEIGHT}")
    print("New: Fullscreen view at /full.html")
    print("Capture: Button on index page saves/displays latest photo")
    print("Config: Set rotation at /config.html (applies immediately)")

    globals()['_bg_restart_event'] = Event()
    capture_mode = globals().get('capture_mode', 'interval')
    if capture_mode == 'interval':
        thread = Thread(target=background_capture_task, args=(int(globals()['time_before_image']),), daemon=True)
        thread.start()
    else:
        scheduler = UnifiedScheduler(globals()['_bg_restart_event'])
        thread = Thread(target=scheduler_loop, args=(scheduler,), daemon=True)
        thread.start()
    try:
        app.run(host='0.0.0.0', port=int(globals()['camera_port']), threaded=True, use_reloader=False)
    finally:
        picam2.stop_recording()
