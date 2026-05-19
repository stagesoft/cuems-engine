# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import fcntl
import os
import re
import selectors
import subprocess
import sys
import tempfile
import time
from typing import Callable

from cuemsutils.log import Logger
from ..core.BaseEngine import CONTROLLER_HOST


# ──────────────────────────────────────────────────────────────────────────
# ASYNC MIGRATION NOTE (read me when porting deploy to asyncio)
# ──────────────────────────────────────────────────────────────────────────
# This module uses `selectors` today because the engine is mid-migration to
# asyncio (see comms/AsyncCommsThread.py for the existing pattern: asyncio
# lives in its own dedicated thread, the rest is sync-with-threads). Pure
# `selectors` keeps _sync() orthogonal to any event loop running elsewhere.
#
# When deploy is ready to go async-native, the rewrite is contained to this
# file. Look for `[ASYNC-MIGRATE]` markers below. Mapping:
#
#   subprocess.Popen(...)       →  await asyncio.create_subprocess_exec(...)
#   fcntl O_NONBLOCK setup      →  delete (asyncio StreamReader is async)
#   selectors.DefaultSelector() →  delete; spawn TWO reader tasks instead
#       sel.register(stdout)        t_out = asyncio.create_task(
#       sel.register(stderr)                    self._pump(proc.stdout, 'out'))
#                                   t_err = asyncio.create_task(
#                                           self._pump(proc.stderr, 'err'))
#   sel.select(timeout=budget)  →  asyncio.wait({t_out, t_err},
#                                       timeout=budget,
#                                       return_when=FIRST_COMPLETED)
#       NOT  asyncio.wait_for(reader.read(4096), timeout=budget)
#       (single-stream; would miss events on the other pipe — wrong)
#   os.read(fd, 4096)           →  await reader.read(4096) inside each pump
#   proc.poll() is None         →  proc.returncode is None
#   proc.wait(timeout=...)      →  await asyncio.wait_for(proc.wait(),
#                                                          timeout=...)
#   def _sync(...)              →  async def _sync(...)
#   _kill: proc.wait(timeout=2) →  await asyncio.wait_for(proc.wait(), 2.0)
#   _kill: def _kill(...)       →  async def _kill(...)
#
# Concretely the async I/O loop becomes a `while not (t_out.done() and
# t_err.done()):` driven by `asyncio.wait({t_out, t_err}, timeout=budget)`,
# with each pump task pushing parsed/raw lines onto an asyncio.Queue that
# the main task drains in the same loop. The watchdog stays: empty `done`
# set from asyncio.wait means the budget expired → kill + return.
#
# Everything else — _parse_progress, _dispatch_line, _on_progress, error-
# precedence semantics, watchdog constants, the \r/\n split, the "drop
# rsync's trailer line" logic — transfers UNCHANGED.
# ──────────────────────────────────────────────────────────────────────────


# Armed only until the first byte of output arrives. Catches pre-fork /
# getaddrinfo hangs — the original 15s subprocess timeout's actual job.
_STARTUP_DEADLINE_S = 10

# Belt-and-braces inactivity watchdog ~3x rsync's own --timeout=5, so rsync
# trips first and reports its own diagnostic in the normal case. Only fires
# if rsync itself becomes uninterruptible.
_INACTIVITY_S = 15


# rsync 3.2+ --info=progress2 line shape:
#       32,768   0%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)
# or near end:
#  2,147,483,648 100%  118.34MB/s    0:00:17 (xfr#3, to-chk=0/3)
_PROGRESS2_RE = re.compile(
    r'^\s*([\d,]+)\s+(\d+)%\s+([\d.]+\s*[kMGT]?B/s)\s+(\d+:\d\d:\d\d)'
    r'(?:\s+\(xfr#(\d+),\s*to-chk=(\d+)/(\d+)\))?\s*$'
)


class CuemsDeploy():
    def __init__(
            self,
            library_path = '/opt/cuems_library/',
            tmp_path = '/tmp/cuems_library/',
            controller_ip: str | None = None,
            hostname: str | None = None,
            log_file: str = '/run/cuems/rsync.log',
            on_progress: Callable[[dict], None] | None = None,
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
            on_progress: Optional callback fired for each rsync progress
                update (parsed from --info=progress2). Receives a dict
                like {'bytes': int, 'pct': int, 'rate': str, 'eta': str,
                'xfr': int, 'remaining': int, 'total': int}. The UI hook
                point — defaults to a no-op.
        """
        self.library_path = library_path
        self.tmp_path = tmp_path
        self.log_file = log_file
        self.errors = []
        self.encoding = sys.getfilesystemencoding()
        self._on_progress = on_progress or (lambda parsed: None)

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

    def sync_files(self, project, tag, file_names=None):
        """Sync files from the controller to the node.

        Option A (mixed mandatory + optional) for project deploys:
        1) pre-check mandatory source paths with cheap metadata probes,
        2) execute one rsync transfer with --ignore-missing-args for the full list.

        Performance note:
        - Option A: N mandatory probes + 1 transfer process.
        - Two-call approach: 2 transfer processes (mandatory then optional).
        Option A usually wins because rsync setup/handshake cost is paid once
        for the bulk transfer.
        """
        if not self.enabled:
            Logger.error(
                f'CuemsDeploy is disabled (no controller IP) — '
                f'skipping {tag} sync for project {project!r}'
            )
            return False

        file_names = list(file_names or [])
        if tag == 'project' and len(file_names) == 0:
            file_names = self._project_files(project)

        mandatory_paths = self._mandatory_paths(project, tag)
        if mandatory_paths:
            mandatory_ok, missing = self._check_mandatory_sources(mandatory_paths)
            if not mandatory_ok:
                if missing:
                    self.errors = [
                        f'mandatory project files are missing at source '
                        f'{self.address}: {", ".join(missing)}'
                    ]
                Logger.error(
                    f'Failed mandatory precheck for {tag} files '
                    f'for project {project!r}'
                )
                for error in self.errors:
                    Logger.error(error)
                return False

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

    def _mandatory_paths(self, project, tag):
        if tag != 'project':
            return []
        return [f'/projects/{project}/script.xml']

    def _check_mandatory_sources(self, mandatory_paths):
        """Verify mandatory remote paths exist before bulk transfer.

        Uses one rsync --list-only probe with all mandatory paths included,
        then keeps one transfer call for the actual sync path.
        """
        mandatory_paths = [p.strip() for p in mandatory_paths if p.strip()]
        if not mandatory_paths:
            return True, []

        env = dict(os.environ, RSYNC_PASSWORD="f48t5eL2kLHw2Wfw")
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding=self.encoding,
            delete=False,
            prefix='rsync_mandatory_',
            suffix='.lst',
        ) as probe_list:
            for source_path in mandatory_paths:
                probe_list.write(f'{source_path}\n')
            probe_list_path = probe_list.name

        try:
            result = subprocess.run(
                [
                    'rsync',
                    '-r',
                    '--list-only',
                    '--contimeout=2',
                    '--timeout=5',
                    f'--files-from={probe_list_path}',
                    self.address,
                    self.library_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=10,
            )
        finally:
            try:
                os.remove(probe_list_path)
            except OSError:
                pass

        if result.returncode == 0:
            return True, []

        stderr = result.stderr.decode(errors='replace').strip()
        missing = []
        for source_path in mandatory_paths:
            if source_path in stderr and (
                'No such file or directory' in stderr
                or 'link_stat' in stderr
                or 'failed to stat' in stderr
            ):
                missing.append(source_path)

        if missing:
            return False, missing

        self.errors = [
            f'rsync mandatory precheck failed: '
            f'{stderr or f"exit code {result.returncode}"}'
        ]
        return False, []


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

    def _sync(self, path):  # [ASYNC-MIGRATE] → `async def _sync(...)`
        # Ensure the log directory exists. /run/cuems is normally created
        # by systemd RuntimeDirectory=, but the cuems user may write
        # nested files into it on demand.
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        except OSError as e:
            Logger.warning(f'Could not create rsync log directory: {e}')

        # --contimeout=2 caps the TCP connect attempt.
        # --timeout=5 is rsync's own I/O inactivity timeout — bounded per
        #   syscall, not total transfer time. Multi-GB media completes as
        #   long as the stream is flowing.
        # --info=progress2,name0 emits a single-line overall progress feed
        #   (with the ,name0 suffix suppressing per-file noise).
        # --ignore-missing-args tells rsync to skip (not error on) entries
        #   from --files-from that do not exist on the source.
        #
        # Supervision: this method streams stdout/stderr via selectors and
        # supervises two watchdogs (startup deadline + inactivity). No
        # total-wall-clock cap — huge transfers complete naturally.
        # -t (preserve mtime) is critical:
        #   1. Without it, rsync stamps receiver mtime to "now" on every transfer,
        #      so subsequent rsyncs see mtime mismatch and rehash the file to
        #      verify content (delta-transfer). For a 4 GB unchanged file this
        #      costs ~30 s of I/O per load.
        #   2. The videocomposer's .idx cache stores the source mtime in its
        #      header. A receiver-side mtime drift invalidates the cache on every
        #      load, forcing a 3-pass reindex (~5 s for 4 GB).
        # Caught on 2026-05-19 — rsync log showed `>f..T......` (size matches,
        # only mtime being updated).
        cmd = [
            'rsync', '-rt',
            '--info=progress2,name0',
            '--stats',
            '--contimeout=2',
            '--timeout=5',
            '--ignore-missing-args',
            f'--files-from={path}',
            f'--log-file={self.log_file}',
            self.address,
            self.library_path,
        ]
        env = dict(os.environ, RSYNC_PASSWORD="f48t5eL2kLHw2Wfw")

        # [ASYNC-MIGRATE] Popen → asyncio.create_subprocess_exec; bufsize
        #                 disappears (StreamReader handles framing).
        # Bytes mode (no text=); we decode manually so we can split on \r.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )

        # [ASYNC-MIGRATE] DELETE THIS BLOCK — async StreamReader is
        #                 non-blocking by construction.
        # Non-blocking pipes — the selector drives timing; os.read() must
        # never block.
        for fd in (proc.stdout.fileno(), proc.stderr.fileno()):
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # [ASYNC-MIGRATE] DELETE — no selector; concurrent reader tasks
        #                 replace this.
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ, 'out')
        sel.register(proc.stderr, selectors.EVENT_READ, 'err')

        bufs = {'out': '', 'err': ''}
        stderr_lines: list[str] = []
        started = False
        deadline = time.monotonic() + _STARTUP_DEADLINE_S
        rc: int | None = None

        try:
            # [ASYNC-MIGRATE] Replace `sel.get_map()` with "both readers
            #                 done"; replace sel.select(timeout=) with
            #                 asyncio.wait({...}, timeout=budget). Empty
            #                 result → asyncio.TimeoutError equivalent.
            while sel.get_map():
                budget = (
                    (deadline - time.monotonic()) if not started
                    else _INACTIVITY_S
                )
                events = sel.select(timeout=max(budget, 0.1))
                if not events:
                    reason = (
                        'no output within startup deadline' if not started
                        else 'no output within inactivity threshold'
                    )
                    self._kill(proc)
                    self.errors = [
                        f'rsync {reason} (target: {self.address})'
                    ]
                    # MUST return — don't let the stderr-derived branch
                    # below overwrite the watchdog reason.
                    return False

                for key, _ in events:
                    tag = key.data
                    try:
                        # [ASYNC-MIGRATE] → await reader.read(4096)
                        chunk = os.read(key.fd, 4096)
                    except BlockingIOError:
                        # [ASYNC-MIGRATE] DELETE — async read can't raise
                        continue
                    if not chunk:
                        sel.unregister(key.fileobj)
                        if bufs[tag]:
                            self._dispatch_line(tag, bufs[tag], stderr_lines)
                            bufs[tag] = ''
                        continue
                    started = True
                    bufs[tag] += chunk.decode(errors='replace')
                    *parts, bufs[tag] = re.split(r'[\r\n]', bufs[tag])
                    for p in parts:
                        if p:
                            self._dispatch_line(tag, p, stderr_lines)

            # rsync may close its pipes a fraction before exiting. Trust
            # --timeout=5 to have done its job, but never block forever
            # here. If wait() times out, the process is wedged after
            # closing fds — kill it.
            # [ASYNC-MIGRATE] → await asyncio.wait_for(proc.wait(),
            #                                          timeout=_INACTIVITY_S)
            try:
                rc = proc.wait(timeout=_INACTIVITY_S)
            except subprocess.TimeoutExpired:
                self._kill(proc)
                self.errors = [
                    f'rsync closed pipes but did not exit within '
                    f'{_INACTIVITY_S}s (target: {self.address})'
                ]
                return False
        finally:
            # [ASYNC-MIGRATE] proc.poll() → proc.returncode is None
            if proc.poll() is None:
                self._kill(proc)
            sel.close()  # [ASYNC-MIGRATE] DELETE — no selector to close

        if rc == 0:
            self.errors = []
            return True
        # Drop rsync's positional "rsync error: ... at main.c(NNN)" trailer
        # when present; keep the real diagnostic lines.
        self.errors = (
            stderr_lines[:-1]
            if stderr_lines and 'rsync error:' in stderr_lines[-1]
            else stderr_lines
        )
        return False

    def _dispatch_line(self, tag: str, line: str, stderr_lines: list[str]) -> None:
        # Paradigm-portable: no I/O primitives, no concurrency. Stays sync
        # in the async port.
        if tag == 'out':
            Logger.debug(f'rsync: {line}')
            parsed = self._parse_progress(line)
            if parsed:
                self._on_progress(parsed)
        else:
            Logger.warning(f'rsync: {line}')
            stderr_lines.append(line)

    def _kill(self, proc):
        # [ASYNC-MIGRATE] Make this `async def`. Both wait() calls become
        #                 `await asyncio.wait_for(proc.wait(), 2.0)` with
        #                 `except asyncio.TimeoutError` instead of
        #                 `subprocess.TimeoutExpired`.
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _parse_progress(self, line: str) -> dict:
        """Parse a rsync --info=progress2 line.

        Returns {} for any line that isn't a progress2 update (stats
        block, file names, blank, etc.). Returns a structured dict
        otherwise — the only consumer today is self._on_progress, which a
        future UI will subscribe to. Keep keys stable.
        """
        m = _PROGRESS2_RE.match(line)
        if not m:
            return {}
        bytes_str, pct, rate, eta, xfr, done, total = m.groups()
        out = {
            'bytes': int(bytes_str.replace(',', '')),
            'pct': int(pct),
            'rate': rate,
            'eta': eta,
        }
        if xfr is not None:
            out.update({
                'xfr': int(xfr),
                'remaining': int(done),
                'total': int(total),
            })
        return out

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
                # rsync --files-from is one path per line. Callers may or
                # may not include the trailing newline; normalize so the
                # file is never silently a single mashed string.
                for name in file_names:
                    if not name.endswith('\n'):
                        name = name + '\n'
                    f.write(name)
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
