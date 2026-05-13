# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import subprocess
import sys
import os
from cuemsutils.log import Logger
from ..core.BaseEngine import CONTROLLER_HOST

class CuemsDeploy():
    def __init__(
            self,
            library_path = '/opt/cuems_library/',
            tmp_path = '/tmp/cuems_library/',
            controller_ip: str | None = None,
            hostname: str | None = None,
            log_file: str = '/tmp/cuems_rsync.log',
        ):
        """Construct a deploy manager.

        Args:
            controller_ip: IP of the controller's rsync daemon (preferred).
                Pass BaseEngine.controller_ip, already resolved from
                network_map.xml. If falsy, manager runs disabled —
                sync_files() returns False without invoking rsync.
            hostname: Legacy fallback. Resolved via avahi when
                controller_ip is not provided. Kept for backwards
                compatibility with code/tests that pre-date the
                controller_ip parameter.
            log_file: Where rsync writes its log.
        """
        self.library_path = library_path
        self.tmp_path = tmp_path
        self.log_file = log_file
        self.errors = []
        self.encoding = sys.getfilesystemencoding()

        # TODO: reconstruct CuemsDeploy on network_map reload so an IP
        # change (DHCP renewal, role-flip, manual XML edit) is picked up
        # without restarting cuems-node-engine.
        if controller_ip:
            self.main_ip = controller_ip
        elif hostname:
            self.main_ip = self._avahi_resolve(hostname)
        else:
            self.main_ip = None

        if self.main_ip:
            self.address = f'rsync://cuems_library_rsync@{self.main_ip}/cuems'
            self.enabled = True
        else:
            self.address = None
            self.enabled = False
            Logger.warning(
                f'CuemsDeploy disabled: no valid controller IP '
                f'(controller_ip={controller_ip!r}, hostname={hostname!r}, '
                f'resolved={self.main_ip!r}). Project deploys will be skipped.'
            )

    def sync_files(self, project, tag, file_names=[]):
        """Sync the files from the controller to the node"""
        if not self.enabled:
            Logger.error(
                f'CuemsDeploy is disabled (no controller IP) — '
                f'skipping {tag} sync for project {project!r}'
            )
            return False

        if tag == 'project' and len(file_names) == 0:
            file_names = self._project_files(project)
        log_file = self._deploy_log_path(project, tag)
        self._create_deploy_log(log_file, file_names)

        synced = self._sync(log_file)
        if synced:
            self._reset_deploy_log(log_file)
        else:
            Logger.error(
                f'Failed to sync {tag} files for project {project!r} '
                f'from {self.address} (log: {log_file})'
            )
            for error in self.errors:
                Logger.error(error)
        return synced


    def _avahi_resolve(self, hostname):
        """Resolve a hostname via avahi-resolve-host-name.

        Returns the IP string on success, or None on failure.
        """
        try:
            result = subprocess.run(
                ['avahi-resolve-host-name', '-n', hostname],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            result.check_returncode()
            ip = result.stdout.decode(self.encoding).replace(hostname, "").strip()
            return ip if ip else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def _sync(self, path):
        # --contimeout=2 caps the TCP connect attempt (was the source of the
        #   ~6s getaddrinfo hangs).
        # --timeout=5 is the rsync I/O inactivity timeout — bounded per-syscall,
        #   not total transfer time, so multi-GB media still completes as long
        #   as the stream is flowing.
        # subprocess.run(timeout=15) is a Python-level backstop in case rsync
        #   hangs before processing its own flags (e.g. inside getaddrinfo).
        try:
            result = subprocess.run(
                [
                    'rsync',
                    '-rq',
                    '--stats',
                    '--contimeout=2',
                    '--timeout=5',
                    f'--files-from={path}',
                    f'--log-file={self.log_file}',
                    self.address,
                    self.library_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(os.environ, RSYNC_PASSWORD="f48t5eL2kLHw2Wfw"),
                timeout=15,
            )
            result.check_returncode()
            self.errors = []
            return True
        except subprocess.CalledProcessError as e:
            errors_string = e.stderr.decode(self.encoding)

            #convert lines to list and remove last line (final error menssage)
            errors_list = errors_string.splitlines()
            if errors_list:
                errors_list.pop()
            self.errors = errors_list
            return False
        except subprocess.TimeoutExpired:
            self.errors = [
                f'rsync timed out after 15s (target: {self.address})'
            ]
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
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
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
