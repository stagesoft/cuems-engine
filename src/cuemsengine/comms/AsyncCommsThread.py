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

    def stop(self) -> None:
        """Stop the thread and event loop.

        Thread-safe method that signals the thread to stop and schedules the
        async stop coroutine to run in the event loop. This will cause the
        event loop to stop and the thread to terminate.

        Note:
            This method can be called from any thread. It does not wait for
            the thread to fully terminate.
        """
        self.stop_requested = True
        if self.event_loop and self.is_alive():
            try:
                asyncio.run_coroutine_threadsafe(self.stop_async(), self.event_loop)
            except Exception as e:
                Logger.debug(f"Error stopping {self.name}: {e}")

    async def stop_async(self) -> None:
        """Async stop handler.

        Cancels all running tasks, waits for cleanup, then stops the event
        loop.
        This is called internally by `stop()` and should not be called
        directly.

        Note:
            This coroutine must run in the same event loop that it stops.
        """
        # Get all tasks except the current one
        current_task = asyncio.current_task()
        pending_tasks = [
            task
            for task in asyncio.all_tasks(self.event_loop)
            if task is not current_task and not task.done()
        ]

        # Cancel all pending tasks
        for task in pending_tasks:
            task.cancel()

        # Wait for all tasks to complete cancellation
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            Logger.debug(f"{self.name} cancelled {len(pending_tasks)} pending tasks")

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
