import os
import time
import configparser
from configparser import ConfigParser
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont


class webcam:
    def __init__(self):
        # Conditional import, if error we're in testing
        try:
            from picamera import PiCamera
        except ImportError:
            self.testing = True
            pass

        self.output_dir = os.path.join(os.getcwd(), 'image_dir')
        self.script_dir = os.path.join(os.getcwd())
        self.testing = False
        if not self.testing:

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
                print(key)
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
    
    def capture_image(self, output_dir, cam_ext):
        """
        This method captures the image using the raspberry pi camera module

        :param output_dir - location that the file is going to be stored.
        :param cam_ext - type of image tat is going to be created.

        :return binary - True if everything went accordingt to plan, else False
        """
        if not self.testing:
            try:
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
                camera.capture(f'{self.output_dir}/camera_image.{cam_ext}')
                print("Camera Revision:" + camera.revision)
                camera.close()
                return True
            except Exception as ex:
                print("Error in capture_image")
                print(ex)
                return False
        
    def create_embed_text(self):
        """
        This method is going to create the text that is going to be put onto the
        photo ONLY. When the text is created it will then be embedded into the image.

        Enhance with the path that the file should be saved to so that images aren't in the
        root folder.
        """
        font_dir = '/'.join(self.output_dir.split('/')[:-1])
        if len(self.embed_time) > 2:
            self.camera_name = self.camera_name + ' - ' + self.cam_time

        # sample text and font
        unicode_text = self.camera_name
        font = ImageFont.truetype(font=f'{font_dir}/fonts/AmazeFont.otf', size=18)

        # get the line size
        text_width, text_height = font.getsize(unicode_text)

        # create a blank canvas with extra space between lines
        canvas = Image.new('RGB', (text_width + 10, text_height + 10), self.text_bg)

        # draw the text onto the text canvas, and use black as the text color
        draw = ImageDraw.Draw(canvas)
        draw.text((5,5), self.camera_name, self.font_color, self.font)

        # save the blank canvas to a file
        try:
            os.remove(f"{self.output_dir}/text.{self.output_ext}")
        except Exception as ex:
            pass
        canvas.save(f"{self.output_dir}/text.{self.output_ext}")

        return True


    def layer_text_img(self, output_dir, cam_file, cam_ext, image_file_sizea):
        """
        Creates the output file with the camera name and time embedded (text)

        Should be updated to include the path for the text file so that the function doesn't
        have to derive that on it's own.

        :param output_dir - output location of the created file
        :param cam_file - filename for the output file
        :param cam_ext - Extension used for the output files

        :output image file
        """
        global cam_x, cam_y

        output_file = ''
        try:
            background = Image.open(f'{output_dir}/camera_image.{cam_ext}')
            img = Image.open(f'{output_dir}/text.{cam_ext}')
            # output_file = f'{output_dir}/{cam_file}{file_date_code}.{cam_ext}'
            output_file = f'{output_dir}/{cam_file}{self.file_date_string()}.{cam_ext}'
            offset = (0, 0)
            background.paste(img, offset)
            # print(f"Saving {output_file}...")
            background.save(output_file)
            # print(f"Resizing {output_file}")
            try:
                image_file_size(output_file, cam_x, cam_y, image_file_sizea)
            except Exception as ex:
                print ("Error create_image.image_file_size")
                print(ex)
        except Exception as ex:
            print("Error create_image")
            print(ex)
        return output_file

def main():
    piCam = webcam()
    print(piCam.file_date_string())
    # print(piCam.cam_config()['filename'])
    # print(piCam.ftpserver)
    print(piCam.cam_time())
    return

if __name__ == "__main__":
    main()