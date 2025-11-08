import os
import time
import configparser
from configparser import ConfigParser
from PIL import Image, ImageDraw, ImageFont
import netifaces as ni
import requests
import getrpimodel as grpm
from PIL.BlpImagePlugin import Format

from PIL.ImageFont import FreeTypeFont


class webcam:
    def __init__(self):
        # Get the raspberry pi model if there's an error we need to make sure that
        # some of the code below isn't run
        try:
            self.m = grpm.model()
        except Exception as ex:
            print("Error getting raspberry pi model")
            print(ex)
            print("End error getting raspberry pi model")
            self.m = None

        # Conditional import, if error we're in testing
        try:
            from picamera import PiCamera
        except ImportError:
            print("Error importing picamera")
            self.testing = True
            pass

        self.output_dir = os.path.join(os.getcwd(), 'image_dir')
        self.script_dir = os.path.join(os.getcwd())
        # if not self.testing:
        self.output_file = None
        self._load_config()
        return

    def _load_config(self):
        # Flatten all sections into instance variables (e.g., self.host, self.db_host)
        self.config = configparser.ConfigParser()
        if os.path.exists("/boot/cam_config.cfg"):
            self.config.read("/boot/cam_config.cfg")
        else:
            self.config.read("cam_config.cfg")
        for section in self.config.sections():
            for key in self.config.options(section):
                # Optional: Type conversion logic
                value = self.config[section][key]
                if key.endswith('_port'):
                    value = self.config.getint(section, key)
                elif value.lower() in ('true', 'false'):
                    value = self.config.getboolean(section, key)

                # Assign as instance variable (flattened namespace)
                # print(key)
                setattr(self, key, value)  # Or: self.__dict__[key] = value

        # Alternative: Nested structure (e.g., self.settings = {'host': 'localhost'})
        # self._load_nested_config()

    def _load_nested_config(self):
        """Optional: Load into nested dicts as attributes."""
        self.config = configparser.ConfigParser()
        if os.path.exists("/boot/cam_config.cfg"):
            self.config.read("/boot/cam_config.cfg")
        else:
            self.config.read("cam_config.cfg")
        for section in self.config.sections():
            setattr(self, section, {})
            for key in self.config.options(section):
                value = self.config[section][key]  # Add type logic as above
                self.__dict__[section][key] = value

    def config_load(self):
        config_object = ConfigParser()
        return

    def current_time(self):
        current_time = time.localtime()
        return current_time

    def cam_time(self):
        """
        Time in the following format:
        Sat, 15 Nov 2020 10:43:50

        :return:
        """
        cam_time = time.strftime('%a, %d %b %Y %H:%M:%S', self.current_time())
        return cam_time

    def display_string(self):
        string = time.strftime('%a, %d %b %Y %H:%M:%S', self.current_time())
        return string

    def file_date_string(self):
        string = time.strftime('%Y%m%d_%H%M%S', self.current_time())
        return string

    def config_parse(self):
        config_object = ConfigParser()
        try:
            conf = config_object.read("/boot/cam_config.cfg")
        except Exception as ex:
            print("Error reading config_object")
            print(ex)
        return conf

    def ftp_config(self):
        try:
            ftp_config = self.config_parse()
            ftp_config = ftp_config["FTP_CONFIG"]
        except Exception as ex:
            print(ex)
        return ftp_config

    # def cam_config(self):
    #     ret = {}
    #     parser = ConfigParser()
    #
    #     parser.read("cam_config.cfg")
    #     # print(parser)
    #
    #     self._load_config()
    #
    #     # section = "CAM_CONFIG"
    #     #
    #     # try:
    #     #     # cam_config = cam_config["CAM_CONFIG"]
    #     #     for key in parser[section]:
    #     #         value = parser[section].getboolean(key) if parser[section][key].lower() in ('true','false') else parser[section][key]
    #     #         ret[key] = value
    #     # except Exception as ex:
    #     #     print(ex)
    #     # # print(ret)
    #     # return ret
    
    def capture_image(self):
        """
        This method captures the image using the raspberry pi camera module

        :param output_dir - location that the file is going to be stored.
        :param output_ext - type of image tat is going to be created.

        :return binary - True if everything went accordingt to plan, else False
        """
        if not self.testing:
            try:
                print("Capturing image")
                camera = PiCamera()
                camera.framerate = 30
                try:
                    camera.resolution = (3280, 2464)
                except:
                    print("Review readme for change in memory split to full support Camera v2")
                    print("Resolution kept at 2592x1944")
                    camera.resolution = (2592, 1944)
                camera.resolution = (cam_x, cam_y)
                camera.start_preview()
                time.sleep(2)
                baseExposure = camera.exposure_speed
                print("base exposure found: ", str(baseExposure))
                camera.capture(f'{self.output_dir}/camera_image.{self.output_ext}')
                print("Camera Revision:" + camera.revision)
                camera.close()
                return True
            except Exception as ex:
                print("Error in capture_image")
                print(ex)
                return False
        else:
            print("Testing mode, not capturing image")
        
    def create_embed_text(self):
        """
        This method is going to create the text that is going to be put onto the
        photo ONLY. When the text is created it will then be embedded into the image.

        Enhance with the path that the file should be saved to so that images aren't in the
        root folder.
        """
        font_dir = '/'.join(self.output_dir.split('/')[:-1])
        if len(self.embed_time) > 2:
            self.camera_name = self.camera_name + ' - ' + self.cam_time()

        # sample text and font
        unicode_text = self.camera_name
        # font_path = f'{self.script_dir}/fonts/AmazeFont.otf'
        font_path = f'{self.script_dir}/fonts/AmazeFont.otf'
        if self.testing == True:
            print(font_path)

        font = ImageFont.truetype(font=font_path, size=18)
        left, top, right, bottom = font.getbbox(text=unicode_text, mode='string')
        text_width = right - left
        text_height = bottom - top

        # create a blank canvas with extra space between lines
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), self.text_bg)

        # draw the text onto the text canvas, and use black as the text color
        draw = ImageDraw.Draw(canvas)
        draw.text((5,5), self.camera_name, self.text_color, font)

        # save the blank canvas to a file
        output_dir = f"{self.output_dir}/text.{self.output_ext}"
        try:
            os.remove(output_dir)
        except Exception as ex:
            pass
        canvas.save(output_dir)

        return True


    def layer_text_img(self):
        """
        Creates the output file with the camera name and time embedded (text)

        Should be updated to include the path for the text file so that the function doesn't
        have to derive that on it's own.

        :param output_dir - output location of the created file
        :param filename - filename for the output file
        :param output_ext - Extension used for the output files

        :output image file
        """
        global cam_x, cam_y

        output_file = ''
        try:
            if self.testing:
                fallback_path = os.path.join(self.script_dir,'image_dir','mountain-stream-in-forest.jpg')
                background = Image.open(fallback_path)
            else:
                background = Image.open(f'{self.output_dir}/camera_image.{self.output_ext}')

            try:
                img = Image.open(f'{self.output_dir}/text.{self.output_ext}')
            except Exception as ex:
                print(f"Error creating img: {img}")

            try:
                # output_file = f'{self.output_dir}/{filename}{file_date_code}.{output_ext}'
                print(self.output_ext)
                self.output_file = f'{self.output_dir}/{self.filename}{self.file_date_string()}.{self.output_ext}'
                # self.output_file = f'{self.output_dir}\\{self.filename}{self.file_date_string()}.png'
                print(self.output_file)
                offset = (0, 0)
                background.paste(img, offset)
                # print(f"Saving {output_file}...")
                background.save(self.output_file,format='JPEG')
                # print(f"Resizing {output_file}")
                # try:
                #     self.image_file_size()
                #     # pass
                # except Exception as ex:
                #     print ("Error create_image.image_file_size")
                #     print(ex)
            except Exception as ex:
                print("Error layering text on the background")
                print(ex)
        except Exception as ex:
            print("Error create_image")
            print(ex)
        return output_file

    def image_file_size(self):
        """
        This function is used to ensure consistent file size output if needed by the application.

        This will ensure that the time to transfer an image is theoretically the same on a daily/upload basis.
        :param file_name - name of file to resize
        :param w - desired width
        :param h - desired height
        :param kb - desired file size in kb
        """
        # print(file_name)
        image = Image.open(self.output_file)
        # print(image)
        kb = kb * 1024
        o_w, o_h = image.size
        # image_size = image.shape
        # print(f"image_size: {img_size}")
        # o_w = img_size[0]
        # o_h = img_size[1]
        if o_w > o_h:
            resize_percent = self.width / o_w
        else:
            resize_percent = self.height / o_h
        n_w = w * resize_percent
        n_h = h * resize_percent
        image.resize((n_w, n_h))

        quality_num = 100
        image.save("resized.jpg", optimize=True, quality=quality_num)
        # get file size
        try:
            file_size = os.path.getsize("resized.jpg")
        except Exception as ex:
            print("Couldn't get file size")
            print(ex)
        print(f"testing kb {file_size}")
        # print(type(file_size))
        # print(type(kb))
        while os.path.getsize("resized.jpg") > kb:
            quality_num -= 1
            print(quality_num)
            image.save("resized.jpg", optimize=True, quality=quality_num)
            # file_size = os.path.getsize("resized.jpg")
            if quality_num <= 0:
                print("COULDN'T RESIZE TO DESTINATION")
                exit(0)
        print("End testing kb")
        # Now that the image is resized it needs to be saved to the same file
        # that is going to be uploaded

        os.remove(self.output_file)
        os.rename("resized.jpg", self.output_file)

        return quality_num

    def connection_check(self, interface):
        """
        Update needed
        """
        ni.gateways()
        interfaces = ni.interfaces()

        if interface in interfaces:
            try:
                ip = ni.ifaddresses(interface)[ni.AF_INET][0]['addr']
                # ni.ifaddresses(interface)[ni.]
                print(f'{interface} IP address: {ip}')
                if len(ip) > 7:
                    print(f"Using {interface} connection")

                    requests.head('http://google.com', timeout=5)
                    print("True connection to the internet is established")
                    # true_connection = True
                    return ip
            except Exception as ex:
                print(f"Connect_Exception: {interface}")
                print(ex)

            # Needs to ensure a real connection to the internet or continue
            # to the next adapter.
        return False

    def update_rtc_time(self):
        """
        Update the time from the internet and then set the hardware
        clock. Note that this can't be checked until on a linux system.
        """
        loop_time_set = 10
        is_set = False
        # Get the time off of the internet.
        # os.system("sudo ntpdate time-a-g.nist.gov time-b-g.nist.gov time-c-g.nist.gov time-d-g.nist.gov time-d-g.nist.gov time-e-g.nist.gov time-e-g.nist.gov time-a-wwv.nist.gov time-b-wwv.nist.gov time-c-wwv.nist.gov time-d-wwv.nist.gov time-d-wwv.nist.gov time-e-wwv.nist.gov time-e-wwv.nist.gov time-a-b.nist.gov time-b-b.nist.gov time-c-b.nist.gov time-d-b.nist.gov time-d-b.nist.gov time-e-b.nist.gov time-e-b.nist.gov time.nist.gov utcnist.colorado.edu utcnist2.colorado.edu")
        while loop_time_set > 0 and is_set == False:
            try:
                ## Raspberry Pi 5 method of setting time
                ## Want to update the time every time the script is run
                os.system("sudo timedatectl set-ntp False")
                os.system("sudo timedatectl set-ntp True")
                is_set = True
            except:
                print("couldn't update time from timedatectl command")
            try:
                if not is_set:
                    os.system("sudo systemctl restart systemd-timesyncd")
                    is_set = True
            except:
                print("couldn't update time from systemctl command")

            try:
                if not is_set:
                    os.system("sudo ntpdate -q 0.us.pool.ntp.org")
                    is_set = True
            except Exception as ex:
                print("couldn't find time")
            # Set the hardware clock
            try:
                if not is_set:
                    os.system("sudo hwclock -w")
                    is_set = True
            except Exception as ex:
                print("couldn't hwclock -w")

            try:
                if not is_set:
                    os.system("sudo hwclock -s")
                    is_set = True
            except Exception as ex:
                print("couldn't hwclock -s")
            time.sleep(5)
            loop_time_set -= 1
        return

    def class_test(self):
        self.file_date_string()
        self.capture_image()
        self.create_embed_text()
        self.layer_text_img()
        if not self.m == None:
            self.update_rtc_time()
            self.connection_check("eth0")
        return

def main():
    piCam = webcam()
    print(piCam.file_date_string())
    # print(piCam.cam_config()['filename'])
    # print(piCam.ftpserver)
    # print(piCam.cam_time())
    # piCam.create_embed_text()
    # piCam.layer_text_img()
    piCam.class_test()
    return

if __name__ == "__main__":
    main()