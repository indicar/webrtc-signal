import os
import json
import asyncio
import websockets
from collections import defaultdict

rooms = defaultdict(list)

async def handler(websocket, path):
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                room = data.get("room")
                if not room:
                    continue

                if websocket not in rooms[room]:
                    rooms[room].append(websocket)

                for client in rooms[room]:
                    if client != websocket and client.open:
                        await client.send(message)
            except json.JSONDecodeError:
                pass
    except websockets.ConnectionClosed:
        pass
    finally:
        for room_clients in rooms.values():
            if websocket in room_clients:
                room_clients.remove(websocket)

async def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер запущен на порту {port}")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())