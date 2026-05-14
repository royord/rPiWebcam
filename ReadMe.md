# Webcam

## Hardware Needed
_The following hardware will produce 2 mirrored camera sets, one as a primary and a second full copy as a backup.
Additional cameras may be needed in order to perform correct tests and development platforms._
- 2x - $55.00 - Raspberry Pi Computer - https://www.adafruit.com/product/5812
- 2x - $22.00 - Raspberry Pi POE - https://www.pishop.us/product/poe-hat-g-compatible-with-raspberry-pi-5-cm5-5v-5a-output-802-3af-at/
- 2x - $32.00 - Raspberry Pi HQ Camera - https://www.adafruit.com/product/4561
- 2x - $65.00 - Raspberry Pi HQ Lens (One of the following)
    - http://adafruit.com/product/4563
    - https://www.pishop.us/product/16mm-telephoto-lens-for-raspberry-pi-hq-camera-cs/
    - https://www.pishop.us/product/6mm-wide-angle-lens-for-raspberry-pi-hq-camera-cs/
## HQ Camera Focus

The Raspberry Pi HQ Camera uses a manual-focus lens — twist the lens barrel to adjust focus. If your image is soft or blurry, rotate the lens ring until the image is sharp.

**Spacer rings:** Some HQ Camera kits include metal spacer rings between the lens and sensor. These are sometimes used for night-vision mods (removing the IR cover glass), but they throw the lens out of its designed working distance and make it impossible to focus. If you're not doing a night-vision mod, **do not install spacer rings** between the lens and the camera body.

- https://www.raspberrypi.com/products/raspberry-pi-high-quality-camera/
- https://forums.raspberrypi.com/viewtopic.php?t=346083

- 2x - $22.00 - SD Card - https://a.co/d/71skmPG
- 2x - $22.00 - Waterproof Case - https://a.co/d/15KyTVh
- 1x - $14.00 - Cable Glands - https://a.co/d/e5Tha8L
- 1x - $10.00 - Standoffs - https://a.co/d/dVZ9prH
- ++++++++++++++++++++++++++++++++++++
-     $420.00 Total for 2 cameras

## Installing the OS

- Download and install raspberry pi imager from the most recent release on the website. The following link can be used.
  https://www.raspberrypi.com/software/
- Choose the correct Raspberry Pi Device, choose the correct "Operating System", one of the "LITE" versions to ensure that only the needed software is installed. We will not be needing a graphical user interface, LITE removes this option.
,select the correct storage media to flash the OS. Click "NEXT" to continue setup. ![img.png](readmeImages/piImager.png)
- On the following select "EDIT SETTINGS" to customize the installation. ![readmeImages/OS_Settings_Apply.png](readmeImages/OS_Settings_Apply.png) Before putting the SD card into the raspberry pi computer, add a file "ssh" to the root SD card file system to enable SSH in the OS.
- On the "GENERAL" tab configure the hostname to "webcam", username and password to a value of your choice. _Other settings may be configured as needed_ ![readmeImages/OS_General_Settings.png](readmeImages/OS_General_Setting)
- On the "SERVICES" tab enable SSH using the access method that you prefer, the rest of the documentation will use SSH to install the needed software and services.![readmeImages/OS_Services_Enable_SSH.png](readmeImages/OS_Services_Enable_SSH.png)

Additional help if needed:
  https://www.youtube.com/watch?v=ntaXWS8Lk34
  https://www.raspberrypi.com/documentation/computers/getting-started.html

Install base OS libraries:

```
sudo apt update
sudo apt dist-upgrade -y
sudo apt autoremove -y
sudo apt install screen vim nano git python3-netifaces build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev tk-dev libcap-dev build-essential python3-libcamera libcamera-apps libcamera-dev python3-picamera2 python3-libcamera
```

Allow passwordless sudo for time sync (required for NTP and hardware clock):

```bash
echo '%sudo ALL=(ALL) NOPASSWD: /usr/bin/timedatectl, /usr/bin/hwclock, /usr/bin/systemctl' | sudo tee /etc/sudoers.d/time-sync
sudo chmod 440 /etc/sudoers.d/time-sync
```

create a public key
'''
ssh-keygen -t ed25519 -C "your_email@example.com"
'''

```
cat .ssh/id_ed25519.pub
```
Make sure that the ssh agent is running:
```aiignore
eval "$(ssh-agent -s)"
```
use the following command to get the content of the public key to add to github profile:
```
cat .ssh/id_ed25519.pub
```
set the git settings for my user:
```aiignore
git config --global user.email "user@domain.com"
git config --global user.name "user_name"
```

now clone the repository:
```
git clone git@github.com:royord/rPiWebcam.git
```
change directory to the cloned folder
```aiignore
cd rPiWebcam
```
create a virtual environment (must include --system-site-packages to access system libcamera):
```aiignore
python3 -m venv --system-site-packages venv
```
activate virtual env
```aiignore
source venv/bin/activate
```
install Python packages:
```aiignore
pip install -r requirements.txt
```
start the server:
```aiignore
python flaskServer.py
```
The server will start on port 8000. Access the web interface at `http://<camera-ip>:8000`.
