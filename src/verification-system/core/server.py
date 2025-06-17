import asyncio
import websockets
import uuid
import json
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)

# Global storage
connections: Dict[str, websockets.WebSocketServerProtocol] = {}
task_queue: asyncio.Queue = asyncio.Queue()
result_queue: asyncio.Queue = asyncio.Queue()


async def invoke_sub_contract_update(sub_contract_id: str, event_type: str, event_data: Dict[str, Any], sender_subject_id: str) -> Dict[str, Any]:
    await asyncio.sleep(1)  # simulate async processing
    return {
        "success": True,
        "message": f"Processed event '{event_type}' for sub_contract_id '{sub_contract_id}' from '{sender_subject_id}'",
        "event_data": event_data
    }


async def background_processor():
    while True:
        task_id, payload = await task_queue.get()
        try:
            result = await invoke_sub_contract_update(
                sub_contract_id=payload["sub_contract_id"],
                event_type=payload["event_type"],
                event_data=payload["event_data"],
                sender_subject_id=payload["sender_subject_id"]
            )
            await result_queue.put((task_id, result))
        except Exception as e:
            await result_queue.put((task_id, {"success": False, "message": str(e)}))


# --- Response Dispatcher: Sends response back over socket ---
async def response_dispatcher():
    while True:
        task_id, result = await result_queue.get()
        ws = connections.pop(task_id, None)
        if ws:
            try:
                await ws.send(json.dumps(result))
                await ws.close()
            except Exception as e:
                logging.error(f"Failed to send response for {task_id}: {e}")


# --- WebSocket Connection Handler ---
async def handler(websocket):
    task_id = str(uuid.uuid4())
    connections[task_id] = websocket
    logging.info(f"New WebSocket connection assigned ID: {task_id}")

    try:
        message = await websocket.recv()
        payload = json.loads(message)

        required_fields = ["sub_contract_id", "event_type", "event_data", "sender_subject_id"]
        if not all(field in payload for field in required_fields):
            await websocket.send(json.dumps({"success": False, "message": "Missing required fields"}))
            await websocket.close()
            return

        await task_queue.put((task_id, payload))
        logging.info(f"Queued task {task_id}")

    except Exception as e:
        logging.error(f"Error handling connection {task_id}: {e}")
        await websocket.send(json.dumps({"success": False, "message": str(e)}))
        await websocket.close()
        connections.pop(task_id, None)


async def main():
    server = await websockets.serve(handler, "0.0.0.0", 6789)
    logging.info("WebSocket server running at ws://0.0.0.0:6789")

    await asyncio.gather(
        background_processor(),
        response_dispatcher(),
        server.wait_closed()
    )

def run_ws_server():
    asyncio.run(main())
