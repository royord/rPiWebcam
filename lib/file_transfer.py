import os
import time
from paramiko import SSHClient, AutoAddPolicy

class FileTransfer:
    def __init__(self, ftpserver, ftpport, username, password, ftmode, file):
        self.ftpserver = ftpserver

        # Set the default port for SFTP or ftp if not set
        if ftpport == "" and ftmode == "sftp":
            self.ftpport = 22
        elif ftpport == "" and ftmode == "ftp":
            self.ftpport = 21
        else:
            self.ftpport = ftpport
        self.ftpmode = ftmode
        self.ftpport = ftpport
        self.username = username
        self.password = password
        self.ftmode = ftmode
        self.file = file

        self.file_size_bytes = os.path.getsize(file)
        self.starttime = time.mktime(time.localtime())
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
        file_size_bytes = os.path.getsize(file)
        starttime = time.mktime(time.localtime())

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
            ftp = ftplib.FTP(ftp_host, ftp_port)
            ftp.login(ftp_user, ftp_pass)
            # upload(ftp, "README.nluug")
            upload(ftp, file)
            ext = os.path.splitext(file)[1]
            if ext in (".txt", ".htm", ".html"):
                ftp.storlines("STOR " + file, open(file))
            else:
                ftp.storbinary("STOR " + file, open(file, "rb"), 1024)
        except Exception as ex:
            print("FTP Transfer Failure")
            return False
        return

    def scp_file(self, site, port, user, pass_w, file, dest):
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
            f"""site: {site}\n"""
            f"""port: {port}\n"""
            f"""user: {user}\n"""
            f"""pass: {pass_w}\n"""
            f"""dest: {dest}\n"""
        )
        try:
            ssh_ob = SSHClient()
            ssh_ob.load_system_host_keys()
            ssh_ob.set_missing_host_key_policy(AutoAddPolicy())
            ssh_ob.connect(hostname=site, port=port, username=user, password=pass_w)
            # ftp_client = ssh_ob.open_sftp()
            ftp_client = scp.SCPClient(ssh_ob.get_transport())
            # transfer_val = False
        except Exception as ex:
            print("Couldn't connect to SCP site.")
            print(ex)
            return False
        try:
            ftp_client.put(file, dest)
        except Exception as ex:
            print("Transfer unsuccessful.")
            print(ex)
            return False
        ftp_client.close()

        return True