# main.py
import os
import json
import asyncio
import websockets
import time

online_users = {}
last_activity = {}

async def broadcast_log(level, message):
    """Отправляет лог-сообщение всем онлайн-пользователям и печатает в консоль."""
    print(message)
    log_msg = json.dumps({
        "type": "server_log",
        "level": level,
        "message": f"[SERVER] {message}",
        "timestamp": time.time()
    })
    all_nicks = list(online_users.keys())
    for nick in all_nicks:
        if nick in online_users:
            try:
                await online_users[nick].send(log_msg)
            except:
                pass

async def notify_user_list():
    """Рассылает всем список онлайн-пользователей"""
    await broadcast_log("info", "[notify_user_list] Начинаем рассылку списка пользователей.")
    users_to_check = list(online_users.keys())
    user_list = [nick for nick, ws in online_users.items() if ws.open]
    
    if len(user_list) != len(users_to_check):
        await broadcast_log("warning", f"[notify_user_list] Обнаружены закрытые соединения. Список онлайн: {user_list}")
        # Обновляем online_users, оставляя только активные соединения
        for nick in users_to_check:
            if nick not in user_list:
                del online_users[nick]
                if nick in last_activity:
                    del last_activity[nick]

    await broadcast_log("info", f"[notify_user_list] Финальный список для рассылки: {user_list}")
    message = json.dumps({"type": "user_list", "users": user_list})
    for nick in user_list:
        if nick in online_users:
            await broadcast_log("info", f"[notify_user_list] Отправляем список пользователю {nick}")
            await online_users[nick].send(message)

async def handler(websocket, path):
    current_user = None
    await broadcast_log("info", f"[handler] Новое подключение от {websocket.remote_address}")
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if current_user:
                last_activity[current_user] = time.time()
                await broadcast_log("info", f"[handler] Получено сообщение типа '{msg_type}' от {current_user}")
            else:
                await broadcast_log("info", f"[handler] Получено сообщение типа '{msg_type}' от неизвестного пользователя")

            if msg_type == "join" and "nickname" in data:
                nickname = data["nickname"]
                current_user = nickname
                await broadcast_log("info", f"[handler/join] Пользователь '{nickname}' пытается подключиться.")
                await broadcast_log("info", f"[handler/join] Список онлайн ДО: {list(online_users.keys())}")

                if nickname in online_users:
                    await broadcast_log("warning", f"[handler/join] Пользователь '{nickname}' уже был онлайн. Закрываем старое соединение.")
                    old_ws = online_users[nickname]
                    try:
                        await old_ws.close(code=1000, reason="Другая сессия активна")
                    except Exception as e:
                        await broadcast_log("error", f"[handler/join] Не удалось закрыть старое соединение для '{nickname}': {e}")
                
                online_users[nickname] = websocket
                last_activity[nickname] = time.time()
                await broadcast_log("info", f"[handler/join] Пользователь '{nickname}' успешно добавлен/обновлен.")
                await broadcast_log("info", f"[handler/join] Список онлайн ПОСЛЕ: {list(online_users.keys())}")

                await notify_user_list()

                await broadcast_log("info", f"[handler/join] Начинаем трансляцию 'joined' для '{nickname}'...")
                all_nicks = list(online_users.keys())
                joined_message = json.dumps({"type": "joined", "nickname": nickname})
                
                for nick in all_nicks:
                    if nick in online_users:
                        await broadcast_log("info", f"[handler/join] Отправляем 'joined' ({nickname}) пользователю {nick}")
                        try:
                            await online_users[nick].send(joined_message)
                        except Exception as e:
                            await broadcast_log("error", f"[handler/join] ОШИБКА отправки 'joined' пользователю {nick}: {e}")
            
            elif msg_type in ("call", "call_accepted", "call_rejected", "offer", "answer", "candidate") and current_user:
                to_user = data.get("to")
                await broadcast_log("info", f"[handler/forward] Пересылка '{msg_type}' от {current_user} к {to_user}")
                if to_user and to_user in online_users:
                    try:
                        await online_users[to_user].send(message)
                        await broadcast_log("info", f"[handler/forward] Успешно переслано '{msg_type}' к {to_user}")
                    except Exception as e:
                        await broadcast_log("error", f"[handler/forward] ОШИБКА пересылки '{msg_type}' к {to_user}: {e}")
                else:
                    await broadcast_log("error", f"[handler/forward] ПОЛУЧАТЕЛЬ '{to_user}' НЕ НАЙДЕН для сообщения '{msg_type}' от {current_user}")

    except websockets.exceptions.ConnectionClosed as e:
        await broadcast_log("warning", f"[handler] Соединение закрыто для {current_user or 'unknown'}. Код: {e.code}, причина: {e.reason}")
    except Exception as e:
        await broadcast_log("error", f"[handler] КРИТИЧЕСКАЯ ОШИБКА в обработчике для {current_user or 'unknown'}: {e}")
    finally:
        await broadcast_log("info", f"[handler/finally] Сработал блок finally для {current_user or 'unknown'}")
        if current_user and current_user in online_users and online_users[current_user] == websocket:
            await broadcast_log("info", f"[handler/finally] Удаляем пользователя '{current_user}' из списка онлайн.")
            del online_users[current_user]
            if current_user in last_activity:
                del last_activity[current_user]
            await notify_user_list()
        else:
            await broadcast_log("info", f"[handler/finally] Пользователь '{current_user}' не был удален (либо уже удален, либо это старый сокет).")

async def cleanup_task():
    while True:
        await asyncio.sleep(30)
        current_time = time.time()
        timeout = 120
        to_remove = [nick for nick, last_seen in list(last_activity.items()) if current_time - last_seen > timeout]

        if to_remove:
            await broadcast_log("warning", f"[cleanup] Найдены неактивные пользователи для удаления: {to_remove}")
            for nick in to_remove:
                if nick in online_users:
                    ws = online_users[nick]
                    try:
                        await ws.close(code=1001, reason="Таймаут активности")
                    except: pass
                    del online_users[nick]
                if nick in last_activity:
                    del last_activity[nick]
            await notify_user_list()

async def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"Сервер запущен на порту {port}")
    asyncio.create_task(cleanup_task())
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())