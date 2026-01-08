"""
FastAPI WebSocket server for progress monitoring.

Runs as a background task, auto-stops when operation completes.
"""

import asyncio
import json
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .tracker import ProgressTracker, ProgressState


class ProgressServer:
    """
    Manages the FastAPI server and WebSocket connections.

    Usage:
        server = ProgressServer(tracker, port=8765)
        await server.start()  # Starts in background, opens browser
        # ... do work, tracker updates broadcast automatically ...
        await server.stop()   # Graceful shutdown
    """

    def __init__(
        self,
        tracker: ProgressTracker,
        port: int = 8765,
        host: str = "127.0.0.1",
        auto_open_browser: bool = True,
        shutdown_delay: float = 5.0,  # Seconds to keep open after complete
    ):
        self.tracker = tracker
        self.port = port
        self.host = host
        self.auto_open_browser = auto_open_browser
        self.shutdown_delay = shutdown_delay

        self._connections: set[WebSocket] = set()
        self._app = self._create_app()
        self._server = None
        self._serve_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._completion_handled = False

    def _create_app(self) -> FastAPI:
        """Create the FastAPI application."""
        app = FastAPI(title="litrev-mcp Progress")

        @app.get("/", response_class=HTMLResponse)
        async def dashboard():
            """Serve the progress dashboard."""
            html_path = Path(__file__).parent / "static" / "dashboard.html"
            return html_path.read_text()

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self._connections.add(websocket)

            try:
                # Send initial state
                await websocket.send_json({
                    "type": "state",
                    "data": self.tracker.state.model_dump(mode="json")
                })

                # Keep connection alive, handle client messages
                while True:
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_text(),
                            timeout=30.0
                        )
                        msg = json.loads(data)
                        if msg.get("type") == "get_state":
                            await websocket.send_json({
                                "type": "state",
                                "data": self.tracker.state.model_dump(mode="json")
                            })
                    except asyncio.TimeoutError:
                        # Send ping to keep alive
                        try:
                            await websocket.send_json({"type": "ping"})
                        except Exception:
                            break

            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                self._connections.discard(websocket)

        return app

    async def _broadcast(self, state: ProgressState):
        """Broadcast state update to all connected clients."""
        if not self._connections:
            return

        message = {
            "type": "update",
            "data": state.model_dump(mode="json")
        }

        disconnected = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)

        self._connections -= disconnected

        # Check if operation complete
        if state.is_complete and not self._completion_handled:
            self._completion_handled = True
            asyncio.create_task(self._handle_completion(state))

    async def _handle_completion(self, state: ProgressState):
        """Handle operation completion - brief delay then signal shutdown."""
        # Send completion message
        message = {
            "type": "complete",
            "data": {
                "operation_id": state.operation_id,
                "summary": state.final_message,
            }
        }
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                pass

        # Wait before allowing shutdown
        await asyncio.sleep(self.shutdown_delay)
        self._shutdown_event.set()

    async def start(self):
        """Start the server and optionally open browser."""
        import uvicorn

        # Register broadcast callback with tracker
        self.tracker.on_update(self._broadcast)

        # Create uvicorn config
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        # Start server in background
        self._serve_task = asyncio.create_task(self._server.serve())

        # Brief delay for server to start
        await asyncio.sleep(0.5)

        # Open browser
        if self.auto_open_browser:
            webbrowser.open(f"http://{self.host}:{self.port}")

    async def stop(self):
        """Stop the server gracefully."""
        if self._server:
            self._server.should_exit = True

        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass

    async def wait_for_completion(self):
        """Wait until operation completes and shutdown delay passes."""
        await self._shutdown_event.wait()


@asynccontextmanager
async def progress_server(
    tracker: ProgressTracker,
    port: int = 8765,
    auto_open_browser: bool = True,
):
    """
    Context manager for running progress server.

    Usage:
        tracker = ProgressTracker(...)
        async with progress_server(tracker) as server:
            # Do work, tracker updates broadcast automatically
            ...
        # Server auto-stops when context exits
    """
    server = ProgressServer(tracker, port=port, auto_open_browser=auto_open_browser)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
