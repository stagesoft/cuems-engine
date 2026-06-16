# Timecode-over-WebSocket CPU Evaluation

## Data flow

1. **MTC listener thread** (mido callback): receives MIDI quarter-frame messages.
   - At 24 fps: 8 quarter-frames per frame → `__update_timecode()` runs when frame_type ∈ {3, 7}, plus full decode at 7 → **~24 invocations/sec** (one per video frame).
   - At 25/30 fps: **~25–30 invocations/sec**.

2. **`mtc_callback`** (BaseEngine, same thread): runs ~24–30/sec. Does:
   - `go_offset is not None` check
   - `self.timecode = mtc.milliseconds - self.go_offset` → triggers property setter.

3. **`on_timecode_change`** (ControllerEngine, same thread): runs ~24–30/sec. Does:
   - `time.monotonic()` (cheap)
   - Throttle: `(now - _last_timecode_broadcast) >= 0.05` → **only ~20 times/sec** proceed.
   - When passing: `int(value)`, `_broadcast_status('timecode', tc_int)`.

4. **`broadcast_osc`** (ControllerCommunications, called from MTC thread): ~20/sec. Does:
   - `build_osc_message('/engine/status/timecode', tc_int)` → new OSC message (~50–80 bytes).
   - `asyncio.run_coroutine_threadsafe(_send_all(), event_loop)` → schedules work on comms thread.

5. **Event loop** (comms thread): ~20/sec runs `_send_all()`:
   - `list(self._ws_clients)` (copy of set)
   - For each client: `await ws.send(data)` (one small TCP send per client).

## CPU impact (summary)

| Component              | Rate        | Cost per call              | Estimated CPU |
|------------------------|------------|----------------------------|---------------|
| mtc_callback           | ~24–30/s   | 1 check + 1 property set    | Negligible    |
| on_timecode_change     | ~24–30/s   | monotonic + throttle check | Negligible    |
| Throttle pass          | 20/s       | int + broadcast            | Negligible    |
| build_osc_message      | 20/s       | Small allocation + encode  | Very low      |
| run_coroutine_threadsafe | 20/s     | Schedule onto loop         | Very low      |
| _send_all (1–5 clients)| 20/s       | 20–100 small socket sends  | Very low      |

**Conclusion:** CPU use for timecode-over-WebSocket is **low**. Typical case (1–3 UI clients, 20 broadcasts/sec, ~50–80 bytes each) is well under 1% CPU. The throttle (20 Hz) is the main limiter; without it, ~24–30 builds and sends/sec would still be light.

## Possible optimizations (if ever needed)

- **Logging:** Avoid `Logger.debug` on every MTC tick; log only when actually broadcasting (or at lower rate) to reduce cost when debug is enabled.
- **Throttle:** 10 Hz (0.1 s) is enough for a timecode display; would halve broadcast and build rate.
- **Message reuse:** Reuse a single OSC message buffer and only change the int argument (micro-optimization; current allocation rate is already small).
