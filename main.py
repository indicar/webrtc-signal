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
    # Создаем копию ключей для итерации, чтобы избежать изменения словаря во время итерации
    users_to_check = list(online_users.keys())
    user_list = []

    for nick in users_to_check:
        if nick in online_users:  # Проверяем, что пользователь все еще в словаре
            ws = online_users[nick]
            if ws.open:
                user_list.append(nick)
            else:
                # Удаляем закрытые соединения
                del online_users[nick]
                if nick in last_activity:
                    del last_activity[nick]

    message = json.dumps({"type": "user_list", "users": user_list})
    for nick in user_list:
        if nick in online_users:  # Проверяем, что пользователь все еще в словаре
            await online_users[nick].send(message)

async def send_server_log(recipients, level, message):
    """Отправляет лог-сообщение от сервера указанным получателям."""
    log_msg = {
        "type": "server_log",
        "level": level,
        "message": message,
        "timestamp": time.time()
    }
    for user in recipients:
        if user in online_users:
            try:
                await online_users[user].send(json.dumps(log_msg))
            except:
                pass # Игнорируем ошибки, если сокет уже закрыт

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
                
                # Сначала рассылаем обновленный список пользователей
                await notify_user_list()

                # Затем создаем и рассылаем ВСЕМ сообщение о новом подключении
                # Создаем копию ключей, чтобы избежать проблем при итерации
                all_nicks = list(online_users.keys())
                joined_message = json.dumps({"type": "joined", "nickname": nickname})
                
                for nick in all_nicks:
                    if nick in online_users: # Проверяем, что пользователь все еще онлайн
                        try:
                            await online_users[nick].send(joined_message)
                        except Exception as e:
                            print(f"Could not send joined message to user {nick}: {e}")
            
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
                to_user = data.get("to")
                if to_user and to_user in online_users:
                    try:
                        # 1. Пересылаем сообщение получателю
                        await online_users[to_user].send(message)
                        print(f"Сообщение '{msg_type}' отправлено от {current_user} к {to_user}")

                        # 2. Отправляем лог подтверждения отправителю
                        await send_server_log(
                            [current_user], "info",
                            f"[SERVER] Успешно переслано сообщение '{msg_type}' пользователю {to_user}"
                        )
                        # 3. Отправляем лог уведомления получателю
                        await send_server_log(
                            [to_user], "info",
                            f"[SERVER] Получено сообщение '{msg_type}' от пользователя {current_user}"
                        )

                    except Exception as e:
                        print(f"Ошибка отправки '{msg_type}' от {current_user} к {to_user}: {e}")
                        # Отправляем сообщение об ошибке инициатору
                        await send_server_log(
                            [current_user], "error",
                            f"[SERVER] Ошибка доставки '{msg_type}' пользователю {to_user}: {str(e)}"
                        )
                        # Удаляем "мертвое" соединение
                        if to_user in online_users:
                            del online_users[to_user]
                        if to_user in last_activity:
                            del last_activity[to_user]
                        await notify_user_list()
                else:
                    print(f"Получатель '{to_user}' не найден для сообщения '{msg_type}' от {current_user}")
                    # Отправляем сообщение об ошибке инициатору
                    await send_server_log(
                        [current_user], "error",
                        f"[SERVER] Получатель '{to_user}' не найден для сообщения '{msg_type}'"
                    )

    except websockets.exceptions.ConnectionClosed:
        # Соединение закрыто - удаляем пользователя
        pass
    except Exception as e:
        # Логируем ошибки для отладки
        print(f"Ошибка обработки сообщения: {e}")
    finally:
        if current_user in online_users:
            del online_users[current_user]
        if current_user in last_activity:
            del last_activity[current_user]
        await notify_user_list()

async def cleanup_task():
    """Фоновая задача для очистки неактивных пользователей"""
    while True:
        await asyncio.sleep(30)  # Проверяем каждые 30 секунд
        current_time = time.time()
        timeout = 120  # Таймаут в 2 минуты

        # Собираем пользователей для удаления (создаем копию ключей для итерации)
        to_remove = []
        for nick in list(last_activity.keys()):  # Создаем копию ключей для итерации
            if nick in last_activity:  # Проверяем, что пользователь все еще в словаре
                if current_time - last_activity[nick] > timeout:
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
            # Удаляем из обоих словарей, если они существуют
            if nick in online_users:
                del online_users[nick]
            if nick in last_activity:
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