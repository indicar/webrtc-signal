# main.py
import os
import json
import asyncio
import websockets
from collections import defaultdict

# ник → websocket
online_users = {}
# комната (frozenset{user1, user2}) → [ws1, ws2]
rooms = {}

async def notify_user_list():
    """Рассылает всем список онлайн-пользователей"""
    user_list = list(online_users.keys())
    message = json.dumps({"type": "user_list", "users": user_list})
    for ws in online_users.values():
        if ws.open:
            await ws.send(message)

async def handler(websocket, path):
    current_user = None
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "join" and "nickname" in data:
                nickname = data["nickname"]
                if nickname in online_users:
                    await websocket.send(json.dumps({"type": "error", "message": "Ник занят"}))
                    continue
                online_users[nickname] = websocket
                current_user = nickname
                await notify_user_list()
                await websocket.send(json.dumps({"type": "joined", "nickname": nickname}))

            elif msg_type == "call" and "to" in data and current_user:
                callee = data["to"]
                if callee not in online_users:
                    await websocket.send(json.dumps({"type": "error", "message": "Пользователь не в сети"}))
                    continue
                # Создаём уникальную комнату для пары
                room_id = frozenset([current_user, callee])
                if room_id not in rooms:
                    rooms[room_id] = [websocket, online_users[callee]]
                # Пересылаем всё в комнату
                for client in rooms[room_id]:
                    if client.open and client != websocket:
                        await client.send(message)

            elif msg_type in ("offer", "answer", "candidate") and current_user:
                # Пересылаем напрямую получателю (предполагаем, что комната уже создана)
                to_user = data.get("to")
                if to_user and to_user in online_users:
                    await online_users[to_user].send(message)

    except Exception as e:
        pass
    finally:
        if current_user in online_users:
            del online_users[current_user]
            await notify_user_list()
        # Удаляем комнаты с этим пользователем
        to_remove = [room for room in rooms if current_user in room]
        for room in to_remove:
            del rooms[room]

async def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер запущен на порту {port}")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())