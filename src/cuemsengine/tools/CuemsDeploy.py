from os import pipe
import subprocess
import sys
import os
from cuemsutils.log import Logger
from ..ControllerEngine import CONTROLLER_HOST

class CuemsDeploy():
    def __init__(
            self,
            library_path = '/opt/cuems_library/',
            tmp_path = '/tmp/cuems_library/',
            hostname = CONTROLLER_HOST,
            log_file = '/tmp/cuems_rsync.log'
        ):
        self.library_path = library_path
        self.tmp_path = tmp_path
        self.main_hostname = hostname
        self.log_file = log_file
        self.errors = []
        self.encoding = sys.getfilesystemencoding()
        
        self.main_ip = self._avahi_resolve(self.main_hostname)
        self.address = f'rsync://cuems_library_rsync@{self.main_ip}/cuems'
    
    def sync_files(self, project, tag, file_names=[]):
        """Sync the files from the controller to the node"""
        if tag == 'project' and len(file_names) == 0:
            file_names = self._project_files(project)
        log_file = self._deploy_log_path(project, tag)
        self._create_deploy_log(log_file, file_names)

        synced = self._sync(log_file)
        if synced:
            self._reset_deploy_log(log_file)
        else:
            Logger.error(f'Failed to sync files from {log_file}')
            for error in self.errors:
                Logger.error(error)
        return synced


    def _avahi_resolve(self, hostname):
        try:
            result = subprocess.run(
                ['avahi-resolve-host-name', '-n', hostname],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            result.check_returncode()
            ip = result.stdout.decode(self.encoding).replace(hostname, "").strip()
            return ip
        except subprocess.CalledProcessError as e:
            return False

    def _sync(self, path):
        #rsync -rv --files-from=/opt/cuems_library/files.tmp --log-file=/tmp/cuems_rsync.log rsync://master.local/cuems /opt/cuems_library/
        try:
            result = subprocess.run(
                [
                    'rsync',
                    '-rq',
                    '--stats',
                    f'--files-from={path}',
                    f'--log-file={self.log_file}',
                    self.address,
                    self.library_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(os.environ, RSYNC_PASSWORD="f48t5eL2kLHw2Wfw")
            )
            result.check_returncode()
            self.errors = []
            return True
        except subprocess.CalledProcessError as e:            
            errors_string = e.stderr.decode(self.encoding)
            
            #convert lines to list and remove last line (final error menssage)
            errors_list = errors_string.splitlines()
            errors_list.pop()
            self.errors = errors_list
            return False

    def _deploy_log_path(self, project, tag = 'project'):
        return os.path.join(
            self.tmp_path, f'rsync_request_{project}_{tag}.log'
        )

    def _create_deploy_log(self, log_file, file_names=[]):
        """Create a log file for a deploy request
        
        Args:
            log_file (str): The path to the log file
            file_names (list): The list of files to deploy

        Returns:
            bool: True if the log file was created successfully, False otherwise
        """
        try:
            with open(log_file, 'w') as f:
                f.writelines(file_names)
        except Exception as e:
            Logger.error(f'Exception raised when writing rsync request log file: {e}')
            return False
        return True

    def _reset_deploy_log(self, log_file):
        with open(log_file, 'w') as f:
            None
        Logger.info(f'rsync Deploy log file {log_file} emptied')

    def _project_files(self, project):
        return [
            '/projects/' + project + '/script.xml\n',
            '/projects/' + project + '/mappings.xml\n', 
            '/projects/' + project + '/settings.xml\n'
        ]
