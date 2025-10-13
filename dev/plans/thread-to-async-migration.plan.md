# Migrate Cue Execution from Threading to Asyncio

## Strategy

Hybrid approach: Convert internal cue execution to async/await while maintaining Thread-based MtcListener and synchronous public API surface. OSC operations remain unchanged (already non-blocking).

## Core Changes

### 1. CueHandler (`src/cuemsengine/cues/CueHandler.py`)

**Public API (stays synchronous)**:

- `go(cue, mtc)` - Keep signature, but launch async task internally
- Replace Thread creation with `asyncio.create_task()`
- Use `asyncio.run()` or event loop management

**Internal execution (convert to async)**:

- Rename `go_threaded()` → `_go_async()` and make it `async def`
- Convert `wait_for_cue(thread)` → `_wait_for_task(task)` with `await task`
- Replace `sleep(cue.prewait.milliseconds / 1000)` with `await asyncio.sleep()`
- Replace `sleep(cue.postwait.milliseconds / 1000)` with `await asyncio.sleep()`
```python
# Before (lines 135-153)
def go(self, cue: Cue, mtc: MtcListener) -> Thread:
    thread = Thread(target=self.go_threaded, args=[cue, mtc], daemon=True)
    thread.start()
    if isinstance(cue._target_object, Cue):
        if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
            self.arm(cue._target_object)
    return thread

# After
def go(self, cue: Cue, mtc: MtcListener):
    task = asyncio.create_task(self._go_async(cue, mtc))
    if isinstance(cue._target_object, Cue):
        if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
            self.arm(cue._target_object)
    return task
```




```python
# Before (lines 155-191)
def go_threaded(self, cue: Cue, mtc: MtcListener):
    if cue.prewait > 0:
        sleep(cue.prewait.milliseconds / 1000)
    # ...

# After
async def _go_async(self, cue: Cue, mtc: MtcListener):
    if cue.prewait > 0:
        await asyncio.sleep(cue.prewait.milliseconds / 1000)
    # ...
```

### 2. run_cue module (`src/cuemsengine/cues/run_cue.py`)

Convert all dispatch functions to async coroutines:

```python
# Before (lines 10-15)
@singledispatch
def run_cue(cue: Cue, mtc: MtcListener):
    pass

# After
@singledispatch
async def run_cue(cue: Cue, mtc: MtcListener):
    pass
```

Apply to all registered functions:

- `run_cueList()` → `async def` (line 18)
- `run_actionCue()` → `async def` (line 34)
- `run_audioCue()` → `async def` (line 71)
- `run_dmxCue()` → `async def` (line 107)
- `run_videoCue()` → `async def` (line 139)

**Note**: No internal changes needed since these functions don't use sleep/threading.

### 3. loop_cue module (`src/cuemsengine/cues/loop_cue.py`)

Convert all functions to async and replace `sleep()` with `asyncio.sleep()`:

```python
# Before (lines 10-14)
@singledispatch
def loop_cue(cue: Cue, mtc):
    pass

# After
@singledispatch
async def loop_cue(cue: Cue, mtc):
    pass
```

**Critical change** - Replace blocking sleep in loops:

```python
# Before (line 48, 112)
while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
    sleep(0.005)

# After
while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
    await asyncio.sleep(0.005)
```

Apply to all registered functions:

- `loop_cueList()` → `async def` (line 17)
- `loop_actionCue()` → `async def` (line 24)
- `loop_audioCue()` → `async def` + async sleep (lines 31, 48)
- `loop_dmxCue()` → `async def` (line 83)
- `loop_videoCue()` → `async def` + async sleep (lines 90, 112)

### 4. Update await calls in CueHandler._go_async()

```python
# Before (line 161)
run_cue(cue, mtc)

# After
await run_cue(cue, mtc)
```



```python
# Before (line 171)
loop_cue(cue, mtc)

# After
await loop_cue(cue, mtc)
```

### 5. Update wait_for_cue → _wait_for_task

```python
# Before (lines 185-191)
def wait_for_cue(self, thread: Thread) -> None:
    Logger.info(f'Waiting for {thread.name} to finish')
    while thread.is_alive():
        sleep(1)
    thread.join()
    Logger.info(f'{thread.name} finished')

# After
async def _wait_for_task(self, task: asyncio.Task) -> None:
    Logger.info(f'Waiting for {task.get_name()} to finish')
    await task
    Logger.info(f'{task.get_name()} finished')
```

Update calls (lines 180, 183):

```python
# Before
self.wait_for_cue(go_at_end_thread)
self.wait_for_cue(post_go_thread)

# After
await self._wait_for_task(go_at_end_task)
await self._wait_for_task(post_go_task)
```

### 6. Event Loop Management

Add event loop handling to `go()` method:

```python
def go(self, cue: Cue, mtc: MtcListener):
    Logger.info(f'GO command received. Starting cue {cue.id}')
    if not cue.loaded:
        raise Exception(f'{cue.__class__.__name__} {cue.id} not loaded to go')
    
    # Get or create event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    task = loop.create_task(self._go_async(cue, mtc))
    
    # Arm next target if needed
    if isinstance(cue._target_object, Cue):
        if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
            self.arm(cue._target_object)
    
    return task
```

## Import Changes

Add to all modified files:

```python
import asyncio
```

Remove from CueHandler.py:

```python
from threading import Thread  # Keep Lock only
```

## Files to Modify

1. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/CueHandler.py`
2. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/run_cue.py`
3. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/loop_cue.py`

## Files Unchanged

- `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/arm_cue.py` (no threading)
- `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/tools/MtcListener.py` (stays Thread)
- `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/players/PlayerHandler.py` (player management untouched)



## ✅ Migration Complete

**Changes Applied:**

### 1. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/loop_cue.py`
- Added `import asyncio`
- Removed `from time import sleep`
- Converted all dispatch functions to async:
  - `loop_cue()` → `async def`
  - `loop_cueList()` → `async def`
  - `loop_actionCue()` → `async def`
  - `loop_audioCue()` → `async def`
  - `loop_dmxCue()` → `async def`
  - `loop_videoCue()` → `async def`
- Replaced `sleep(0.005)` with `await asyncio.sleep(0.005)` in audio and video loop functions

### 2. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/run_cue.py`
- Added `import asyncio`
- Converted all dispatch functions to async:
  - `run_cue()` → `async def`
  - `run_cueList()` → `async def`
  - `run_actionCue()` → `async def`
  - `run_audioCue()` → `async def`
  - `run_dmxCue()` → `async def`
  - `run_videoCue()` → `async def`

### 3. `/disk/Projects/StageLab/cuems-engine/src/cuemsengine/cues/CueHandler.py`
- Added `import asyncio`
- Updated imports: `from threading import Lock` (removed Thread)
- Converted `go()` method to create async tasks instead of threads:
  - Implements event loop management (get_running_loop or create new)
  - Creates tasks with `loop.create_task()` instead of `Thread()`
  - Returns `asyncio.Task` instead of `Thread`
- Renamed `go_threaded()` → `_go_async()` and made it async:
  - Replaced `sleep()` with `await asyncio.sleep()`
  - Added `await` for `run_cue()` and `loop_cue()` calls
  - Updated to create tasks for post_go operations
- Renamed `wait_for_cue()` → `_wait_for_task()` and made it async:
  - Simplified to `await task` instead of thread polling
  - Uses `task.get_name()` instead of `thread.name`

**Verification:**
- ✅ No linter errors
- ✅ All async/await conversions complete
- ✅ Event loop handling implemented
- ✅ MtcListener remains Thread-based (unchanged)
- ✅ PlayerHandler unchanged
- ✅ Public API (`go()`) remains synchronous
