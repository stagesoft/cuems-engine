# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""CuemsDeploy: async rsync-based media and project deployer for CUEMS nodes.

Async model: _sync(), _check_mandatory_sources(), _kill(), and _pump() are
coroutines scheduled on the event loop injected via NodeEngine.start()
late-bind. sync_files() remains a synchronous blocking API; it submits
_deploy_all_async() via run_coroutine_threadsafe() and blocks until
completion. Watchdogs inside the coroutine bound all wait times.

Late-bind protocol:
  NodeEngine.__init__() creates CuemsDeploy(loop=None).
  NodeEngine.start() calls CUE_HANDLER.set_nng_comms(...), which starts
  AsyncCommsThread (creates the event_loop), then:
      self.deploy_manager.loop = CUE_HANDLER.communications_thread.event_loop
  Any sync_files() before that bind returns False immediately.

Why _avahi_resolve stays synchronous: it is called from __init__() before
any asyncio loop exists, so subprocess.run() (short timeout) is correct.
"""

import asyncio
import os
import re
import sys
import tempfile
from typing import Callable, ClassVar

from cuemsutils.log import Logger
from ..core.BaseEngine import CONTROLLER_HOST


# Armed at startup; resets on first byte — catches pre-fork/getaddrinfo hangs.
_STARTUP_DEADLINE_S = 10

# 3× rsync's own --timeout=5; rsync trips first in the normal case.
_INACTIVITY_S = 15


# rsync 3.2+ --info=progress2: "  32,768   0%  0.00kB/s  0:00:00 (xfr#1, to-chk=0/1)"
_PROGRESS2_RE = re.compile(
    r'^\s*([\d,]+)\s+(\d+)%\s+([\d.]+\s*[kMGT]?B/s)\s+(\d+:\d\d:\d\d)'
    r'(?:\s+\(xfr#(\d+),\s*to-chk=(\d+)/(\d+)\))?\s*$'
)


class CuemsDeploy():
    _RSYNC_PASSWORD: ClassVar[str] = 'f48t5eL2kLHw2Wfw'

    def __init__(
            self,
            library_path = '/opt/cuems_library/',
            tmp_path = '/tmp/cuems_library/',
            controller_ip: str | None = None,
            hostname: str | None = None,
            log_file: str = '/run/cuems/rsync.log',
            on_progress: Callable[[dict], None] | None = None,
            loop: asyncio.AbstractEventLoop | None = None,
        ):
        """Construct a deploy manager.

        Args:
            controller_ip: IP of the controller's rsync daemon (preferred).
                Pass BaseEngine.controller_ip. If falsy, manager runs disabled.
            hostname: Legacy fallback resolved via avahi when controller_ip is
                not provided. Kept for backwards compatibility.
            log_file: Where rsync writes its log.
            on_progress: Optional callback fired for each rsync progress update
                (parsed from --info=progress2). Receives a dict with keys
                bytes, pct, rate, eta, and optionally xfr, remaining, total.
                Must be non-blocking — invoked from the asyncio loop.
            loop: The asyncio event loop for run_coroutine_threadsafe(). Defaults
                to None; late-bind via NodeEngine.start().
        """
        self.library_path = library_path
        self.tmp_path = tmp_path
        self.log_file = log_file
        self.errors = []
        self.encoding = sys.getfilesystemencoding()
        self._on_progress = on_progress or (lambda parsed: None)
        self.loop = loop

        # TODO: rebuild on network_map reload to pick up IP changes without restarting.
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

    def sync_files(self, project: str, tag: str, file_names: list[str] | None = None) -> bool:
        """Sync files from the controller to the node.

        Submits _deploy_all_async() to self.loop via run_coroutine_threadsafe()
        and blocks until the coroutine completes. Watchdogs inside the coroutine
        handle all time bounds; no external timeout is needed here.

        Args:
            project: Project identifier used to build paths and log file names.
            tag: Transfer type — ``'project'`` or ``'media'``. Controls which
                mandatory-path precheck runs and which default file list is used
                when file_names is empty.
            file_names: Explicit list of rsync-relative paths to transfer. When
                omitted (or empty) and tag is ``'project'``, defaults to the
                standard project file set (script, mappings, settings).

        Returns:
            True on success; False if disabled, loop unbound, precheck failed,
            rsync exited non-zero, or any unexpected exception occurred. On
            failure, self.errors contains one or more diagnostic strings.
        """
        if not self.enabled:
            Logger.error(
                f'CuemsDeploy is disabled (no controller IP) — '
                f'skipping {tag} sync for project {project!r}'
            )
            return False

        if self.loop is None:
            Logger.error(
                f'CuemsDeploy event loop not bound (NodeEngine.start() not '
                f'called yet) — skipping {tag} sync for project {project!r}'
            )
            self.errors = ['event loop not bound']
            return False

        file_names = list(file_names or [])
        if tag == 'project' and len(file_names) == 0:
            file_names = self._project_files(project)
        elif tag == 'media' and len(file_names) > 0:
            file_names = self._media_files(file_names)

        mandatory_paths = self._mandatory_paths(project, tag)
        log_file = self._deploy_log_path(project, tag)

        try:
            coro = self._deploy_all_async(log_file, file_names, mandatory_paths)
            synced = asyncio.run_coroutine_threadsafe(coro, self.loop).result()
        except Exception as e:
            Logger.error(f'Unexpected error during deploy of {project!r}: {e}')
            self.errors = [str(e)]
            return False

        if synced:
            self._reset_deploy_log(log_file)
            self.errors = []
        else:
            Logger.error(
                f'Failed to sync {tag} files for project {project!r} '
                f'from {self.address} (log: {log_file})'
            )
            for error in self.errors:
                Logger.error(error)
        return synced

    def _mandatory_paths(self, project: str, tag: str) -> list[str]:
        if tag != 'project':
            return []
        return [f'/projects/{project}/script.xml']

    async def _check_mandatory_sources(self, mandatory_paths: list[str]) -> tuple[bool, list[str]]:
        """Verify mandatory remote paths exist before bulk transfer.

        Uses one rsync --list-only probe with all mandatory paths. Output is
        consumed via proc.communicate() — the probe is short-lived and has
        bounded output, so streaming is unnecessary (proc.communicate()
        rationale: see research.md §2).
        """
        mandatory_paths = [p.strip() for p in mandatory_paths if p.strip()]
        if not mandatory_paths:
            return True, []

        env = dict(os.environ, RSYNC_PASSWORD=self._RSYNC_PASSWORD)
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
            proc = await asyncio.create_subprocess_exec(
                'rsync',
                '-r',
                '--list-only',
                '--contimeout=2',
                '--timeout=5',
                f'--files-from={probe_list_path}',
                self.address,
                self.library_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr_bytes = await proc.communicate()
        finally:
            try:
                os.remove(probe_list_path)
            except OSError:
                pass

        if proc.returncode == 0:
            return True, []

        stderr = stderr_bytes.decode(errors='replace').strip()
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
            f'{stderr or f"exit code {proc.returncode}"}'
        ]
        return False, []

    def _avahi_resolve(self, hostname: str) -> str | None:
        """Resolve a hostname via avahi-resolve-host-name.

        Stays synchronous: called from __init__() before any asyncio loop
        exists. Returns the IP string on success, or None on failure.
        """
        import subprocess
        try:
            result = subprocess.run(
                ['avahi-resolve-host-name', '-n', hostname],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            result.check_returncode()
            ip = result.stdout.decode(self.encoding).replace(hostname, '').strip()
            return ip if ip else None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    async def _pump(self, stream: asyncio.StreamReader, tag: str, queue: asyncio.Queue) -> None:
        """Read 4096-byte chunks until EOF; push (tag, chunk) then (tag, None).

        (tag, None) is the EOF sentinel consumed by _sync's driver loop.
        """
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                await queue.put((tag, None))
                return
            await queue.put((tag, chunk))

    async def _sync(self, path: str) -> bool:
        """Async rsync transfer with two concurrent reader tasks and watchdogs.

        Watchdog state machine (data-model.md):
          STARTUP → empty asyncio.wait result before first queue item → KILLED
          ACTIVE  → empty asyncio.wait result after receiving data    → KILLED
          DONE    → both pipes closed, proc exits rc=0                → True
          DONE    → both pipes closed, proc exits rc≠0                → False

        Queue pattern: two _pump tasks push to a shared asyncio.Queue; the
        main driver loop drains it after each asyncio.wait() call. The
        watchdog deadline resets on every received chunk.
        """
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        except OSError as e:
            Logger.warning(f'Could not create rsync log directory: {e}')

        # -t: rsync shows >f..T...... without it; also breaks .idx mtime cache (2026-05-19).
        cmd = [
            'rsync', '-rt',
            '--delete',
            '--delete-delay',
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
        env = dict(os.environ, RSYNC_PASSWORD=self._RSYNC_PASSWORD)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        queue: asyncio.Queue = asyncio.Queue()
        t_out = asyncio.create_task(self._pump(proc.stdout, 'out', queue))
        t_err = asyncio.create_task(self._pump(proc.stderr, 'err', queue))

        bufs = {'out': '', 'err': ''}
        stderr_lines: list[str] = []
        started = False
        deadline = asyncio.get_event_loop().time() + _STARTUP_DEADLINE_S
        pipes_done = 0
        rc: int | None = None
        # Only pending tasks: avoids busy-loop once one pump finishes before the other.
        pending = {t_out, t_err}

        try:
            while pipes_done < 2:
                budget = deadline - asyncio.get_event_loop().time()
                done, pending = await asyncio.wait(
                    pending, timeout=max(budget, 0.1)
                )
                # Drain before watchdog: pump can push data without completing its task.
                got_data = False
                while not queue.empty():
                    tag, chunk = queue.get_nowait()
                    if chunk is None:
                        if bufs[tag]:
                            self._dispatch_line(tag, bufs[tag], stderr_lines)
                            bufs[tag] = ''
                        pipes_done += 1
                        continue
                    got_data = True
                    started = True
                    deadline = asyncio.get_event_loop().time() + _INACTIVITY_S
                    bufs[tag] += chunk.decode(errors='replace')
                    *parts, bufs[tag] = re.split(r'[\r\n]', bufs[tag])
                    for p in parts:
                        if p:
                            self._dispatch_line(tag, p, stderr_lines)
                if not done and not got_data:
                    reason = (
                        'no output within startup deadline' if not started
                        else 'no output within inactivity threshold'
                    )
                    t_out.cancel()
                    t_err.cancel()
                    await asyncio.gather(t_out, t_err, return_exceptions=True)
                    await self._kill(proc)
                    self.errors = [f'rsync {reason} (target: {self.address})']
                    return False

            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=_INACTIVITY_S)
            except asyncio.TimeoutError:
                await self._kill(proc)
                self.errors = [
                    f'rsync closed pipes but did not exit within '
                    f'{_INACTIVITY_S}s (target: {self.address})'
                ]
                return False
        finally:
            if proc.returncode is None:
                await self._kill(proc)

        if rc == 0:
            self.errors = []
            return True
        # Drop the positional "rsync error: ... at main.c(NNN)" trailer if present.
        self.errors = (
            stderr_lines[:-1]
            if stderr_lines and 'rsync error:' in stderr_lines[-1]
            else stderr_lines
        )
        return False

    def _dispatch_line(self, tag: str, line: str, stderr_lines: list[str]) -> None:
        if tag == 'out':
            Logger.debug(f'rsync: {line}')
            parsed = self._parse_progress(line)
            if parsed:
                self._on_progress(parsed)
        else:
            Logger.warning(f'rsync: {line}')
            stderr_lines.append(line)

    async def _kill(self, proc: asyncio.subprocess.Process) -> None:
        """Terminate proc gracefully, escalating to SIGKILL after 2 s."""
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _deploy_all_async(self, log_file: str, file_names: list[str], mandatory_paths: list[str]) -> bool:
        """Full deploy flow: precheck → log creation → rsync transfer.

        Early-fails on precheck failure; the log file is only created when
        precheck passes (preserving the pre-refactor invariant).
        """
        if mandatory_paths:
            mandatory_ok, missing = await self._check_mandatory_sources(
                mandatory_paths
            )
            if not mandatory_ok:
                if missing:
                    self.errors = [
                        f'mandatory project files are missing at source '
                        f'{self.address}: {", ".join(missing)}'
                    ]
                Logger.error('Failed mandatory precheck for project files')
                return False
        self._create_deploy_log(log_file, file_names)
        return await self._sync(log_file)

    def _parse_progress(self, line: str) -> dict[str, int | str]:
        """Parse a rsync --info=progress2 line.

        Returns {} for non-progress lines (stats block, file names, blank).
        Returns a structured dict with keys bytes, pct, rate, eta, and
        optionally xfr, remaining, total. Keep keys stable — UI consumers
        depend on them.
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

    def _deploy_log_path(self, project: str, tag: str = 'project') -> str:
        return os.path.join(
            self.tmp_path, f'rsync_request_{project}_{tag}.log'
        )

    def _create_deploy_log(self, log_file: str, file_names: list[str] = []) -> bool:
        """Create the rsync --files-from list file for a deploy request."""
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'w') as f:
                # Normalize to one-path-per-line; callers may omit the trailing newline.
                for name in file_names:
                    if not name.endswith('\n'):
                        name = name + '\n'
                    f.write(name)
        except Exception as e:
            Logger.error(f'Exception raised when writing rsync request log file: {e}')
            return False
        return True

    def _reset_deploy_log(self, log_file: str) -> None:
        with open(log_file, 'w'):
            pass
        Logger.info(f'rsync Deploy log file {log_file} emptied')

    def _project_files(self, project: str) -> list[str]:
        return [
            '/projects/' + project + '/script.xml\n',
            '/projects/' + project + '/mappings.xml\n',
            '/projects/' + project + '/settings.xml\n'
        ]

    def _media_files(self, bare_names: list[str]) -> list[str]:
        """Expand bare media filenames to rsync-relative paths for --files-from.

        Every file gets a media/<name> entry. Video files (.mp4 .mov .avi
        .mkv .mpg) also get a media/indexes/<name>.idx sidecar entry.
        """
        _VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.mpg'}
        result = []
        for name in bare_names:
            result.append(f'media/{name}')
            if os.path.splitext(name)[1].lower() in _VIDEO_EXTS:
                result.append(f'media/indexes/{name}.idx')
        return result
