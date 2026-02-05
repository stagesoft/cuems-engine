"""WebSocket OSC Handler for receiving OSC messages via WebSocket.

This module provides an async WebSocket listener that receives and parses
OSC messages sent over WebSocket connections (as used by OSCQuery protocol).
It bypasses pyossia's unreliable WebSocket handling while keeping pyossia
for OSCQuery discovery and metadata.

Usage:
    In an AsyncCommsThread subclass:
    
    async def websocket_osc_task(self):
        await websocket_osc_listener(
            host="0.0.0.0",
            port=9190,
            message_handler=self.handle_osc_message,
            stop_check=lambda: self.stop_requested
        )
    
    def create_all_tasks(self):
        return [
            asyncio.create_task(self.websocket_osc_task()),
            # ... other tasks
        ]
"""

import asyncio
from typing import Callable, Optional, Any

from cuemsutils.log import Logger

try:
    import websockets
    from websockets.server import serve as websocket_serve
    from websockets.exceptions import ConnectionClosed
except ImportError:
    websockets = None
    websocket_serve = None
    ConnectionClosed = Exception

try:
    from pythonosc.osc_message import OscMessage
    from pythonosc.parsing import osc_types
except ImportError:
    OscMessage = None
    osc_types = None


def parse_osc_message(data: bytes) -> tuple[str, list[Any]] | None:
    """Parse a binary OSC message.
    
    Args:
        data: Raw binary OSC message data
        
    Returns:
        Tuple of (address, arguments) if successful, None if parsing fails
    """
    if not osc_types:
        Logger.error("python-osc library not available")
        return None
        
    try:
        # OSC message format: address (null-padded to 4 bytes), type tag string, arguments
        # Use pythonosc's parsing utilities
        address, index = osc_types.get_string(data, 0)
        
        if index >= len(data):
            # No type tag string - address-only message (like an impulse)
            return (address, [])
        
        # Get type tag string
        type_tags, index = osc_types.get_string(data, index)
        
        if not type_tags.startswith(','):
            Logger.warning(f"Invalid OSC type tag string: {type_tags}")
            return (address, [])
        
        # Parse arguments based on type tags
        args = []
        for tag in type_tags[1:]:  # Skip the leading ','
            if tag == 'i':
                value, index = osc_types.get_int(data, index)
                args.append(value)
            elif tag == 'f':
                value, index = osc_types.get_float(data, index)
                args.append(value)
            elif tag == 's':
                value, index = osc_types.get_string(data, index)
                args.append(value)
            elif tag == 'b':
                value, index = osc_types.get_blob(data, index)
                args.append(value)
            elif tag == 'T':
                args.append(True)
            elif tag == 'F':
                args.append(False)
            elif tag == 'N':
                args.append(None)
            elif tag == 'I':
                # Impulse/Infinitum - no value
                args.append(None)
            elif tag == 't':
                # OSC timetag (8 bytes)
                value, index = osc_types.get_timetag(data, index)
                args.append(value)
            elif tag == 'd':
                # Double precision float
                value, index = osc_types.get_double(data, index)
                args.append(value)
            else:
                Logger.warning(f"Unknown OSC type tag: {tag}")
        
        return (address, args)
        
    except Exception as e:
        Logger.debug(f"Error parsing OSC message: {e}")
        return None


async def handle_websocket_connection(
    websocket,
    message_handler: Callable[[str, list[Any]], None],
    stop_check: Callable[[], bool]
) -> None:
    """Handle a single WebSocket connection.
    
    Args:
        websocket: The WebSocket connection
        message_handler: Callback function to handle parsed OSC messages.
                        Called with (address: str, args: list)
        stop_check: Function that returns True when the listener should stop
    """
    client_info = f"{websocket.remote_address}" if hasattr(websocket, 'remote_address') else "unknown"
    Logger.info(f"WebSocket OSC client connected: {client_info}")
    
    try:
        async for message in websocket:
            if stop_check():
                break
                
            # OSCQuery sends OSC messages as binary WebSocket frames
            if isinstance(message, bytes):
                parsed = parse_osc_message(message)
                if parsed:
                    address, args = parsed
                    Logger.debug(f"WebSocket OSC received: {address} = {args}")
                    try:
                        message_handler(address, args)
                    except Exception as e:
                        Logger.error(f"Error in OSC message handler for {address}: {e}")
            else:
                # Text message - might be JSON for OSCQuery protocol
                Logger.debug(f"WebSocket text message received (ignored): {message[:100] if len(message) > 100 else message}")
                
    except ConnectionClosed:
        Logger.debug(f"WebSocket OSC client disconnected: {client_info}")
    except Exception as e:
        Logger.error(f"WebSocket OSC connection error: {e}")
    finally:
        Logger.debug(f"WebSocket OSC connection closed: {client_info}")


async def websocket_osc_listener(
    host: str,
    port: int,
    message_handler: Callable[[str, list[Any]], None],
    stop_check: Callable[[], bool],
    existing_server_check: Optional[Callable[[], bool]] = None
) -> None:
    """Async WebSocket OSC listener.
    
    Listens for WebSocket connections and parses incoming binary OSC messages.
    Routes parsed messages to the provided handler callback.
    
    Args:
        host: Host address to bind to (e.g., "0.0.0.0" or "127.0.0.1")
        port: Port to listen on (typically the OSCQuery WebSocket port)
        message_handler: Callback function to handle parsed OSC messages.
                        Called with (address: str, args: list)
        stop_check: Function that returns True when the listener should stop
        existing_server_check: Optional function that returns True if an existing
                              server is already listening on the port. If True,
                              the listener will not start its own server.
    
    Note:
        The OSCQuery protocol uses the same WebSocket port for both discovery
        (JSON messages) and OSC value updates (binary messages). This listener
        only processes binary OSC messages and ignores JSON messages.
        
        If pyossia's OSCQuery server is already using the port, you may need
        to either:
        1. Disable pyossia's WebSocket handler and use this one exclusively
        2. Run this on a different port and update the UI configuration
        3. Intercept messages at a different layer
    """
    if not websockets:
        Logger.error("websockets library not available - cannot start WebSocket OSC listener")
        return
    
    if existing_server_check and existing_server_check():
        Logger.info(f"Existing server detected on {host}:{port}, WebSocket OSC listener not starting own server")
        return
    
    Logger.info(f"Starting WebSocket OSC listener on ws://{host}:{port}")
    
    try:
        async with websocket_serve(
            lambda ws: handle_websocket_connection(ws, message_handler, stop_check),
            host,
            port,
            # Allow concurrent connections
            max_size=2**20,  # 1 MB max message size
            # Ping/pong for keepalive
            ping_interval=20,
            ping_timeout=20,
        ):
            Logger.info(f"WebSocket OSC listener started on ws://{host}:{port}")
            # Keep running until stop is requested
            while not stop_check():
                await asyncio.sleep(0.1)
                
    except OSError as e:
        if "already in use" in str(e).lower() or e.errno == 98:
            Logger.warning(f"WebSocket port {port} already in use (likely by pyossia OSCQuery server)")
            Logger.info("WebSocket OSC listener will not start - pyossia is handling WebSocket connections")
            Logger.info("Commands will be received via HTTP polling fallback")
        else:
            Logger.error(f"WebSocket OSC listener error: {e}")
    except Exception as e:
        Logger.error(f"WebSocket OSC listener error: {e}")
    finally:
        Logger.info("WebSocket OSC listener stopped")


class WebSocketOscRouter:
    """Routes OSC messages to registered handlers based on address patterns.
    
    This class provides a simple routing mechanism for OSC messages, allowing
    handlers to be registered for specific OSC addresses or address patterns.
    
    Usage:
        router = WebSocketOscRouter()
        router.register('/engine/command/go', handle_go_command)
        router.register('/engine/command/*', handle_any_command)  # Wildcard
        
        # In the message handler:
        def handle_osc_message(address, args):
            router.route(address, args)
    """
    
    def __init__(self):
        self._handlers: dict[str, Callable[[str, list[Any]], None]] = {}
        self._wildcard_handlers: list[tuple[str, Callable[[str, list[Any]], None]]] = []
    
    def register(self, pattern: str, handler: Callable[[str, list[Any]], None]) -> None:
        """Register a handler for an OSC address pattern.
        
        Args:
            pattern: OSC address or pattern. Use '*' at the end for wildcard matching.
                    e.g., '/engine/command/go' for exact match
                    e.g., '/engine/command/*' for prefix match
            handler: Callback function to handle messages matching the pattern.
                    Called with (address: str, args: list)
        """
        if pattern.endswith('/*'):
            prefix = pattern[:-1]  # Remove trailing '*', keep '/'
            self._wildcard_handlers.append((prefix, handler))
            Logger.debug(f"Registered wildcard OSC handler: {pattern}")
        else:
            self._handlers[pattern] = handler
            Logger.debug(f"Registered OSC handler: {pattern}")
    
    def route(self, address: str, args: list[Any]) -> bool:
        """Route an OSC message to the appropriate handler.
        
        Args:
            address: OSC address (e.g., '/engine/command/go')
            args: List of OSC arguments
            
        Returns:
            True if a handler was found and called, False otherwise
        """
        # Check exact match first
        if address in self._handlers:
            try:
                self._handlers[address](address, args)
                return True
            except Exception as e:
                Logger.error(f"Error in OSC handler for {address}: {e}")
                return False
        
        # Check wildcard handlers
        for prefix, handler in self._wildcard_handlers:
            if address.startswith(prefix):
                try:
                    handler(address, args)
                    return True
                except Exception as e:
                    Logger.error(f"Error in wildcard OSC handler for {address}: {e}")
                    return False
        
        Logger.debug(f"No handler registered for OSC address: {address}")
        return False
    
    def clear(self) -> None:
        """Remove all registered handlers."""
        self._handlers.clear()
        self._wildcard_handlers.clear()
