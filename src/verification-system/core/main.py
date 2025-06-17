import threading
import asyncio

from .api import run_api_server
from .server import run_ws_server

# Your async WebSocket server
async def start_ws_server():
    import websockets
    import logging

    logging.basicConfig(level=logging.INFO)

    async def dummy_ws_handler(ws):
        await ws.send("WebSocket server is alive")
        await ws.wait_closed()

    server = await websockets.serve(dummy_ws_handler, "0.0.0.0", 6789)
    print("WebSocket server started on ws://0.0.0.0:6789")
    await server.wait_closed()

# 👇 Unified Main Launcher
def main():
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    print("API server started on http://0.0.0.0:8000")

    run_ws_server()

if __name__ == "__main__":
    main()
