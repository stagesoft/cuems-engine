from os import pipe
import subprocess
import sys
import os

class CuemsDeploy():

    def __init__(self, library_path=None, master_hostname=None, log_file=None):
        
        if not master_hostname:
            self.master_hostname = "master.local"
        else:
            self.master_hostname

        self.master_ip = self.__avahi_resolve(self.master_hostname)

        self.address = f'rsync://cuems_library_rsync@{self.master_ip}/cuems'

        
        if not library_path:
            self.library_path = '/opt/cuems_library/'
        else:
            self.library_path = library_path

        if not log_file:
            self.log_file = '/tmp/cuems_rsync.log'
        else:
            self.log_file = log_file

        self.errors = None

    def __avahi_resolve(self, hostname):
        try:
            result = subprocess.run(['avahi-resolve-host-name', '-n', hostname], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result.check_returncode()
            ip = result.stdout.decode(sys.getfilesystemencoding()).replace(hostname, "").strip()
            return ip
        except subprocess.CalledProcessError as e:
            return False
        

        


    def sync(self, path):
        #rsync -rv --files-from=/opt/cuems_library/files.tmp --log-file=/tmp/cuems_rsync.log rsync://master.local/cuems /opt/cuems_library/
        try:
            result = subprocess.run(['rsync', '-rq', '--stats', f'--files-from={path}', f'--log-file={self.log_file}', self.address, self.library_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, RSYNC_PASSWORD="f48t5eL2kLHw2Wfw"))
            result.check_returncode()
            self.errors = None
            return True
        except subprocess.CalledProcessError as e:
            #print('exit code: {}'.format(e.returncode))
            #print('stdout: {}'.format(e.output.decode(sys.getfilesystemencoding())))
            #print('stderr: {}'.format(e.stderr.decode(sys.getfilesystemencoding())))
            
            errors_string = e.stderr.decode(sys.getfilesystemencoding())
            
            #convert lines to list and remove last line (final error menssage)
            errors_list = errors_string.splitlines()
            errors_list.pop()
            self.errors = errors_list
            return False

