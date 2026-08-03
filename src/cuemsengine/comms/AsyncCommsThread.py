# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import asyncio
from threading import Thread
from typing import Any, Callable, List, Optional

from cuemsutils.log import Logger

TIMEOUT = 15  # seconds


class AsyncCommsThread(Thread):
    """Base class for asynchronous communication threads.

    This class extends Thread to run an asyncio event loop in a separate daemon
    thread. Subclasses must implement `create_all_tasks()` to define the async
    tasks that will be executed concurrently.

    The event loop runs in the background thread and can be safely accessed
    from
    other threads using `run_coroutine()`.

    Attributes:
        thread_name (str): Base name for the thread.
        name (str): Full thread name with 'AsyncComms-' prefix.
        timeout (float): Default timeout in seconds for coroutine execution.
        stop_requested (bool): Flag indicating whether thread should stop.
        send_contexts (List): List of send contexts (subclass-specific).
        event_loop (asyncio.AbstractEventLoop): The asyncio event loop running
            in this thread. None until `run()` is called.

    Example:
        Subclass implementation:

        ```python
        class MyAsyncComms(AsyncCommsThread):
            async def my_task(self):
                # Do async work
                pass

            def create_all_tasks(self):
                return [asyncio.create_task(self.my_task())]
        ```
    """

    def __init__(self, **kwargs):
        """Initialize the AsyncCommsThread.

        Creates a daemon thread that will run an asyncio event loop. The thread
        is configured with a name and optional timeout for coroutine execution.

        Args:
            **kwargs: Keyword arguments.
                - thread_name (str, optional): Base name for the thread.
                    Defaults to the name of the subclass.
                - timeout (float, optional): Timeout in seconds for coroutine
                    execution. Defaults to TIMEOUT (15 seconds).

        Note:
            The thread is created as a daemon thread, so it will automatically
            terminate when the main program exits.
        """
        self.thread_name = kwargs.get("thread_name", type(self).__name__)
        Logger.info(f"Initializing AsyncCommsThread: {self.thread_name}")
        super().__init__(name=self.thread_name, daemon=True)
        self.name = f"AsyncComms-{self.thread_name}"
        self.timeout = kwargs.get("timeout", TIMEOUT)
        self.stop_requested = False
        self.send_contexts: List[Any] = []
        self.event_loop: asyncio.AbstractEventLoop | None = None

    def run(self) -> None:
        """Thread entry point.

        Creates a new asyncio event loop, schedules the async communications
        task, and runs the event loop forever. This method is called
        automatically when the thread is started.

        The event loop will continue running until `stop()` is called, which
        will cause the loop to stop and the thread to terminate.
        """
        Logger.info(f"Running {self.name}")
        self.event_loop = asyncio.new_event_loop()
        self.event_loop.create_task(self.run_asyncio_comms())
        self.event_loop.run_forever()

    def stop(self, timeout: Optional[float] = None) -> None:
        """Stop the thread and event loop, and wait for it to terminate.

        Thread-safe method that cancels all pending tasks, stops the event
        loop and joins the thread.

        This MUST block until the thread is gone. The event loop drives NNG
        (pynng) sockets, and pynng registers an atexit hook that calls
        nng_fini(), which destroys NNG's global state. CPython does not join
        daemon threads before running atexit hooks, so if this thread is still
        alive at interpreter shutdown, its next NNG call lands in freed
        internals and aborts the process with
        "panic: pthread_mutex_lock: Invalid argument" (ClickUp 869ed00ya).

        Args:
            timeout: Seconds to wait for task cancellation and for the thread
                to join. Defaults to `self.timeout`.

        Note:
            This method can be called from any thread except this one.
        """
        self.stop_requested = True
        if timeout is None:
            timeout = self.timeout

        loop = self.event_loop
        if loop is not None and self.is_alive():
            try:
                # Cancel the tasks first and WAIT for them: cancelling the NNG
                # receiver while NNG is still alive lets pynng cancel and free
                # its aio cleanly.
                future = asyncio.run_coroutine_threadsafe(self._cancel_tasks(), loop)
                future.result(timeout=timeout)
            except Exception as e:
                Logger.warning(f"Error cancelling tasks in {self.name}: {e}")
            finally:
                # Stop the loop only after cancellation has settled, otherwise
                # the future above can never resolve.
                loop.call_soon_threadsafe(loop.stop)

        if self.ident is None:
            # Never started — nothing to join, and join() would raise.
            return

        self.join(timeout=timeout)
        if self.is_alive():
            Logger.error(
                f"{self.name} still alive after {timeout}s — NNG teardown may abort"
            )
        else:
            Logger.info(f"{self.name} stopped and joined")

    async def _cancel_tasks(self) -> None:
        """Cancel every task in this loop except the caller.

        Runs inside the event loop. Deliberately does NOT stop the loop — see
        `stop()`, which stops it once this has settled.
        """
        current_task = asyncio.current_task()
        pending_tasks = [
            task
            for task in asyncio.all_tasks(self.event_loop)
            if task is not current_task and not task.done()
        ]

        for task in pending_tasks:
            task.cancel()

        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            Logger.debug(f"{self.name} cancelled {len(pending_tasks)} pending tasks")

    async def stop_async(self) -> None:
        """Async stop handler.

        Cancels all running tasks, waits for cleanup, then stops the event
        loop.

        Note:
            This coroutine must run in the same event loop that it stops.
            Prefer `stop()`, which also joins the thread — a caller that
            awaits this alone cannot observe the loop actually stopping,
            because stopping the loop prevents this coroutine's result from
            ever being delivered.
        """
        await self._cancel_tasks()

        # Now stop the event loop
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        Logger.info(f"{self.name} event loop stopped")

    async def run_asyncio_comms(self) -> None:
        """Run all async communication tasks.

        Creates all tasks from `create_all_tasks()` and waits for them to
        complete. Tasks run concurrently and exceptions are captured rather
        than immediately raised (via `return_exceptions=True`).

        This method runs until all tasks complete or until `stop_async()` is
        called.

        Note:
            Subclasses should implement `create_all_tasks()` to return a list
            of asyncio tasks that need to run concurrently.
        """
        Logger.info(f"Starting asyncio communications in {self.name}")
        tasks = self.create_all_tasks()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                Logger.error(
                    f"{self.name} task {i} failed with"
                    f"{type(result).__name__}: {result}"
                )
        Logger.info(f"{self.name} asyncio communications finished")

    def create_all_tasks(self) -> List[asyncio.Task]:
        """Create all async tasks to run concurrently.

        Subclasses must implement this method to return a list of asyncio
        tasks that should run concurrently in the event loop. These tasks
        typically handle various communication channels or services.

        Returns:
            List[asyncio.Task]: List of asyncio tasks to run concurrently.

        Raises:
            NotImplementedError: If not implemented by subclass.

        Example:
            ```python
            def create_all_tasks(self):
                return [
                    asyncio.create_task(self.listener_task()),
                    asyncio.create_task(self.sender_task()),
                ]
            ```
        """
        raise NotImplementedError("create_all_tasks is not implemented")

    def run_coroutine(
        self,
        coroutine: Callable,
        message: dict,
        timeout: Optional[float] = None,
    ) -> Any:
        """Run a coroutine in the event loop from another thread.

        Thread-safe method to execute a coroutine function in this thread's
        event loop. The coroutine is called with the provided message and
        the result is returned synchronously, with a timeout.

        This is the primary way to interact with the async event loop from
        other threads (e.g., the main thread).

        Args:
            coroutine: A coroutine function to execute. Must be a coroutine
                function (not a regular function).
            message: Dictionary to pass as argument to the coroutine.
            timeout: Optional timeout in seconds (defaults to self.timeout). -1
            means no timeout.

        Returns:
            Any: The return value from the coroutine.

        Raises:
            AttributeError: If the event loop has not been initialized (thread
                not started).
            TypeError: If `coroutine` is not a coroutine function.
            TimeoutError: If the coroutine does not complete within `timeout`
                seconds.
            Exception: If the coroutine raises an exception, it is re-raised
                here.

        Example:
            ```python
            async def send_message(msg: dict) -> dict:
                # Async operation
                return {'status': 'ok'}

            # From another thread:
            result = comms_thread.run_coroutine(send_message, {'data': 'test'})
            ```
        """
        if not self.event_loop:
            raise AttributeError(f"{self.name} event loop is not initialized")

        if not asyncio.iscoroutinefunction(coroutine):
            raise TypeError(
                f"{self.name} parameter coroutine is not a coroutine function"
            )

        function_name = coroutine.__name__
        Logger.debug(f"{self.name} running coroutine: {function_name}")

        if timeout is None:
            timeout = self.timeout

        if timeout == -1:
            timeout = None

        send_task = asyncio.run_coroutine_threadsafe(
            coroutine(message), self.event_loop
        )
        try:
            result = send_task.result(timeout=timeout)
            Logger.debug(f"{self.name} {function_name} returned: {result!r}")
            return result
        except TimeoutError:
            Logger.error(f"{self.name} {function_name} timed out after {timeout}s")
            send_task.cancel()
            raise
        except Exception as exc:
            Logger.error(f"{self.name} {function_name} raised an exception: {exc!r}")
            send_task.cancel()
            raise
