# main.py
import os
import json
import asyncio
import websockets
from collections import defaultdict

import time

# ник → websocket
online_users = {}
# ник → время последней активности
last_activity = {}

async def notify_user_list():
    """Рассылает всем список онлайн-пользователей"""
    user_list = list(online_users.keys())
    message = json.dumps({"type": "user_list", "users": user_list})
    # Фильтруем только открытые соединения
    open_connections = []
    for nick, ws in online_users.items():
        if ws.open:
            open_connections.append((nick, ws))
        else:
            # Удаляем закрытые соединения
            if nick in online_users:
                del online_users[nick]
                if nick in last_activity:
                    del last_activity[nick]

    for _, ws in open_connections:
        await ws.send(message)

async def handler(websocket, path):
    current_user = None
    try:
        async for message in websocket:
            # Обновляем время активности при любом сообщении
            if current_user:
                last_activity[current_user] = time.time()

            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "join" and "nickname" in data:
                nickname = data["nickname"]
                # Закрываем старое соединение, если пользователь уже онлайн
                if nickname in online_users:
                    old_ws = online_users[nickname]
                    try:
                        await old_ws.close(code=1000, reason="Другая сессия активна")
                    except:
                        pass  # Старое соединение уже закрыто
                    await notify_user_list()

                online_users[nickname] = websocket
                current_user = nickname
                last_activity[nickname] = time.time()  # Обновляем время активности
                await notify_user_list()
                await websocket.send(json.dumps({"type": "joined", "nickname": nickname}))

            elif msg_type == "call" and "to" in data and current_user:
                callee = data["to"]
                if callee not in online_users:
                    await websocket.send(json.dumps({"type": "error", "message": "Пользователь не в сети"}))
                    print(f"Пользователь {callee} не в сети, невозможно отправить звонок от {current_user}")
                    continue
                # Просто пересылаем сообщение звонка получателю
                try:
                    await online_users[callee].send(message)
                    print(f"Сообщение 'call' отправлено от {current_user} к {callee}")
                except Exception as e:
                    print(f"Ошибка отправки 'call' от {current_user} к {callee}: {e}")
                    # Удаляем неактивное соединение
                    if callee in online_users:
                        del online_users[callee]
                        if callee in last_activity:
                            del last_activity[callee]
                        await notify_user_list()

            elif msg_type == "call_accepted" and "to" in data and current_user:
                callee = data["to"]
                if callee in online_users:
                    try:
                        await online_users[callee].send(message)
                        print(f"Сообщение 'call_accepted' отправлено от {current_user} к {callee}")
                    except Exception as e:
                        print(f"Ошибка отправки 'call_accepted' от {current_user} к {callee}: {e}")
                        if callee in online_users:
                            del online_users[callee]
                            if callee in last_activity:
                                del last_activity[callee]
                            await notify_user_list()

            elif msg_type == "call_rejected" and "to" in data and current_user:
                callee = data["to"]
                if callee in online_users:
                    try:
                        await online_users[callee].send(message)
                        print(f"Сообщение 'call_rejected' отправлено от {current_user} к {callee}")
                    except Exception as e:
                        print(f"Ошибка отправки 'call_rejected' от {current_user} к {callee}: {e}")
                        if callee in online_users:
                            del online_users[callee]
                            if callee in last_activity:
                                del last_activity[callee]
                            await notify_user_list()

            elif msg_type in ("offer", "answer", "candidate") and current_user:
                # Пересылаем напрямую получателю (предполагаем, что комната уже создана)
                to_user = data.get("to")
                if to_user and to_user in online_users:
                    try:
                        await online_users[to_user].send(message)
                        print(f"Сообщение '{msg_type}' отправлено от {current_user} к {to_user}")
                    except Exception as e:
                        print(f"Ошибка отправки '{msg_type}' от {current_user} к {to_user}: {e}")
                        if to_user in online_users:
                            del online_users[to_user]
                            if to_user in last_activity:
                                del last_activity[to_user]
                            await notify_user_list()
                else:
                    print(f"Получатель '{to_user}' не найден для сообщения '{msg_type}' от {current_user}")

    except websockets.exceptions.ConnectionClosed:
        # Соединение закрыто - удаляем пользователя
        pass
    except Exception as e:
        # Логируем ошибки для отладки
        print(f"Ошибка обработки сообщения: {e}")
    finally:
        if current_user in online_users:
            del online_users[current_user]
            await notify_user_list()

async def cleanup_task():
    """Фоновая задача для очистки неактивных пользователей"""
    while True:
        await asyncio.sleep(30)  # Проверяем каждые 30 секунд
        current_time = time.time()
        timeout = 120  # Таймаут в 2 минуты

        # Собираем пользователей для удаления
        to_remove = []
        for nick, last_time in last_activity.items():
            if current_time - last_time > timeout:
                if nick in online_users:
                    to_remove.append(nick)

        # Удаляем неактивных пользователей
        for nick in to_remove:
            if nick in online_users:
                ws = online_users[nick]
                try:
                    await ws.close(code=1001, reason="Таймаут активности")
                except:
                    pass
                del online_users[nick]
                del last_activity[nick]
                print(f"Удален неактивный пользователь: {nick}")

        if to_remove:
            await notify_user_list()

async def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер запущен на порту {port}")

    # Запускаем задачу очистки в фоне
    asyncio.create_task(cleanup_task())

    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())