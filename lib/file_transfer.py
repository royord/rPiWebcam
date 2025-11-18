import os
import time

import paramiko
from paramiko import SSHClient, AutoAddPolicy, file
import scp
import ftplib
import sys

class FileTransfer:
    def __init__(self, ftpserver, username, password, ftmode, file, destination, ftpport=None):
        print(file)
        self.ftpserver = ftpserver

        # Set the default port for SFTP or ftp if not set
        self.ftpmode = ftmode.lower()
        self.ftpport = ftpport
        self.username = username
        self.password = password
        self.ftmode = ftmode.lower()
        self.file = file
        self.destination = destination
        if self.destination.endswith("/"):
            self.destination = self.destination[:-1]
        if self.destination.startswith("./"):
            self.destination = self.destination[2:]

        print(f"self.destination: {self.destination}")

        self.file_size_bytes = os.path.getsize(file)
        self.starttime = time.mktime(time.localtime())
        if ftpport == None and self.ftmode == "sftp":
            self.ftpport = 22
        elif ftpport == None and self.ftmode == "ftp":
            self.ftpport = 21
        else:
            self.ftpport = ftpport

        if self.ftmode == "sftp":
            print("SFTP")
            self.scp_file()
        else:
            print("FTP")
            self.ftp_file()
        pass
    
    def transfer(self, ftp, file):
        """
        Transfers to the ftp the file

        :param ftp passes the information for how the files are going to be connected and moved, passes as a dictionary.
        :param file name that is going to be moved onto the FTP
        :return int 0 if successful and 1 if unsuccessful during the transfer

        Please note that the items below talk give us information about the
        """
        
        # The following allows upload of the file to multiple directories based on config
        # NOTE: It doesn't seem possible to copy the file on the remote server a second
        # upload is going to be necessary at this time.
        print("Starting File Transfer...")

        # If we're using SFTP we need to make sure that we capture the sFTP ssh-key
        # and do so silently. The following command does so at the system level.
        # if self.ftpmode == 'sftp':
        #    os.system(f"ssh-keyscan -H {self.ftpserver} >> ~/.ssh/known_hosts")
        self.file_size_bytes = os.path.getsize(file)
        self.starttime = time.mktime(time.localtime())

        for x in ftp:
            if x.startswith("ftppath"):
                print(x)
                try:
                    print(f"{ftp[x]}")
                    print(f"ftp_file: {ftp[x.replace('ftppath', 'ftpfile')]}")

                    conf_file_path = ftp[x]
                    conf_file = ftp[x.replace('ftppath', 'ftpfile')]
                except Exception as ex:
                    print("could not find matching file name")
                    continue
                if ftp[x.replace('ftppath', 'ftpfile')] != "":
                    print("if")
                    file_name = ftp[x.replace('ftppath', 'ftpfile')]
                else:
                    print("else")
                    file_name = file
                print(f"Uploading {file_name}")
                file_name = conf_file_path + conf_file
                print(f"...{file_name}")
                time.sleep(5)
                # SFTP file
                print("self.ftpmode: ", self.ftpmode)
                if self.ftpmode == 'sftp':
                    print(f"Using SFTP to transfer file... {file}")
                    # scp_success = scp_file(self.ftpserver, 22, self.username, self.password, file, "royord.com/new_test_image.jpg")
                    scp_success = self.scp_file(self.ftpserver, 22, self.username, self.password, file, file_name)
                    # return scp_success
                # FTP file
                # elif ftp_mode == 'ftp':

                # endtime = time.mktime(time.localtime())
                # bytespersec = file_size_bytes / (endtime - starttime).totalseconds()
                # return True
        print("FTP COMPLETED")
        return True

    def ftp_file(self):
        try:
            print("ftp")
            ftp = ftplib.FTP(self.ftpserver, self.ftpport)
            ftp.login(self.ftpuser, self.password)
            # upload(ftp, "README.nluug")
            # upload(ftp, self.file)
            ftp.storbinary()
            ext = os.path.splitext(self.file)[1]
            if ext in (".txt", ".htm", ".html"):
                ftp.storlines("STOR " + self.file, open(self.file))
            else:
                ftp.storbinary("STOR " + self.file, open(self.file, "rb"), 1024)
        except Exception as ex:
            print("FTP Transfer Failure")
            return False
        return

    def scp_file(self):
        """
        Parameters:
            site    : Destination (ftp) site
            port    : connection port, assumes 22 since we're using SCP
            user    : User for the connection
            pass_w  : Password for the connection
            file    : File to be copied
            dest    : Destination on the ftp (site) this can be done as "<dir>/<filename>"

        Return:
            bool connection and transfer True/False

        Example Connection:
            ssh.connect("<host>",port=22,username='<user>',password='<password>',look_for_keys=False, allow_agent=False,timeout=4)
        """
        print("Starting SCP session...")
        print(
            f"""site: {self.ftpserver}\n"""
            f"""port: {self.ftpport}\n"""
            f"""user: {self.username}\n"""
            f"""pass: {self.password}\n"""
            f"""dest: {self.destination}\n"""
        )
        try:
            ssh_ob = SSHClient()
            # ssh_ob.load_system_host_keys()
            ssh_ob.set_missing_host_key_policy(AutoAddPolicy())
            # ssh_ob.set_missing_host_key_policy(WarningPolicy())
            ssh_ob.connect(hostname=self.ftpserver, port=self.ftpport, username=self.username, password=self.password)
            # ftp_client = ssh_ob.open_sftp()
            # ftp_client = scp.SCPClient(ssh_ob.get_transport())
            # ftp_client = ssh
            ftp_client = paramiko.SFTPClient.from_transport(ssh_ob.get_transport())
            # transfer_val = False
        except Exception as ex:
            print("Couldn't connect to SCP site.")
            print(ex)
            return False
        print("Unsplit self.destination: ", self.destination)
        try:
            if self.destination != ".":
                try:
                    dest_list = self.destination.split("/")
                    for d in dest_list[:-1]:
                        print(f"d: {d}")
                        if d == "" or d == "/":
                            d = '/'
                        try:
                            ftp_client.chdir(d)
                            print("Directory change: ", d)
                        except IOError:
                            print("Creating directory: " + d)
                            ftp_client.mkdir(d)
                            ftp_client.chdir(d)
                except Exception as ex:
                    dest_list = self.destination
                    print(dest_list[:-1])

                destination = (f'{self.destination}/{self.file.split("/")[-1]}')
            else:
                destination = self.file.split("/")[-1]

            # Move the file now that the folder exists
            try:
                ftp_client.put(self.file, destination)
            except Exception as ex:
                print("Transfer unsuccessful.")
                print("self.file: ", self.file)
                print("destination: ", destination)
                print(ex)
                return False
        except Exception as ex:
            return False
        # try:
        #     ftp_client.put(self.file, self.destination)
        # except Exception as ex:
        #     print("Transfer unsuccessful.")
        #     print(ex)
        #     return False
        ftp_client.close()

        return True