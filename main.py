# main.py
import os
import json
import asyncio
import websockets
from collections import defaultdict

# ник → websocket
online_users = {}

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
                # Просто пересылаем сообщение звонка получателю
                await online_users[callee].send(message)

            elif msg_type == "call_accepted" and "to" in data and current_user:
                callee = data["to"]
                if callee in online_users:
                    await online_users[callee].send(message)

            elif msg_type == "call_rejected" and "to" in data and current_user:
                callee = data["to"]
                if callee in online_users:
                    await online_users[callee].send(message)

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

async def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер запущен на порту {port}")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())