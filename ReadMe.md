# Webcam

## Hardware Needed
_The following hardware will produce 2 mirrored camera sets, one as a primary and a second full copy as a backup.
Additional cameras may be needed in order to perform correct tests and development platforms._
- 2x - $55.00 - Raspberry Pi Computer - https://www.adafruit.com/product/5812
- 2x - $32.00 - Raspberry Pi HQ Camera - https://www.adafruit.com/product/4561
- 2x - $65.00 - Raspberry Pi HQ Lens (One of the following)
    - http://adafruit.com/product/4563
    - https://www.pishop.us/product/16mm-telephoto-lens-for-raspberry-pi-hq-camera-cs/
    - https://www.pishop.us/product/6mm-wide-angle-lens-for-raspberry-pi-hq-camera-cs/
- 2x - $22.00 - SD Card - https://a.co/d/71skmPG
- 2x - $22.00 - Waterproof Case - https://a.co/d/15KyTVh
- 1x - $14.00 - Cable Glands - https://a.co/d/e5Tha8L
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
