# main.py
import os
import json
import asyncio
import websockets

# Словарь для хранения зарегистрированных пользователей и их контактов
# Структура: {"nickname": {"contacts": {"contact1", "contact2"}}}
users = {} 
# Словарь для хранения активных WebSocket-соединений
online_users = {}

async def notify_user_list_change():
    """Рассылает всем онлайн-пользователям обновленный список онлайн-пользователей."""
    print("[notify_user_list_change] Рассылка обновленного списка онлайн-пользователей.")
    online_nicks = list(online_users.keys())
    message = json.dumps({"type": "user_list", "users": online_nicks})
    
    # Создаем копию словаря для безопасной итерации
    all_online = list(online_users.values())
    for ws in all_online:
        if ws.open:
            try:
                await ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                # Соединение уже закрыто, будет обработано в `finally`
                pass

async def send_to_user(nickname, message):
    """Отправляет сообщение конкретному пользователю, если он онлайн."""
    if nickname in online_users:
        try:
            await online_users[nickname].send(json.dumps(message))
            print(f"[send_to_user] Сообщение '{message['type']}' успешно отправлено {nickname}")
            return True
        except websockets.exceptions.ConnectionClosed:
            print(f"[send_to_user] Ошибка: соединение с {nickname} уже закрыто.")
            return False
    else:
        print(f"[send_to_user] Ошибка: пользователь {nickname} не найден в сети.")
        return False

async def handler(websocket, path):
    current_user = None
    print(f"[handler] Новое подключение от {websocket.remote_address}")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")
            except json.JSONDecodeError:
                print(f"[handler] Ошибка: получено не-JSON сообщение от {current_user or 'unknown'}")
                continue

            print(f"[handler] Получено сообщение типа '{msg_type}' от {current_user or 'unknown'}")

            # --- Обработка регистрации и входа ---
            if msg_type == "register":
                nickname = data.get("nickname")
                if not nickname or not isinstance(nickname, str) or len(nickname) < 3:
                    await websocket.send(json.dumps({"type": "register_response", "success": False, "error": "Неверный никнейм."}))
                    continue
                
                if nickname in users:
                    await websocket.send(json.dumps({"type": "register_response", "success": False, "error": "Этот никнейм уже занят."}))
                else:
                    users[nickname] = {"contacts": set()}
                    current_user = nickname
                    online_users[current_user] = websocket
                    await websocket.send(json.dumps({"type": "register_response", "success": True}))
                    print(f"[handler/register] Пользователь '{nickname}' успешно зарегистрирован и вошел в систему.")
                    await notify_user_list_change()

            elif msg_type == "login":
                nickname = data.get("nickname")
                if nickname in users:
                    # Если пользователь уже онлайн, закрываем старое соединение
                    if nickname in online_users:
                        print(f"[handler/login] Пользователь '{nickname}' уже онлайн. Закрываем старое соединение.")
                        await online_users[nickname].close(1000, "Новая сессия активна")
                    
                    current_user = nickname
                    online_users[current_user] = websocket
                    
                    # Отправляем список контактов
                    contact_list = list(users.get(nickname, {}).get("contacts", []))
                    await websocket.send(json.dumps({"type": "login_response", "success": True, "contacts": contact_list}))
                    print(f"[handler/login] Пользователь '{nickname}' успешно вошел.")
                    
                    await notify_user_list_change()
                else:
                    await websocket.send(json.dumps({"type": "login_response", "success": False, "error": "Пользователь не найден."}))

            # --- Функции, требующие авторизации ---
            elif not current_user:
                print(f"[handler] Ошибка: '{msg_type}' требует авторизации. Пользователь не идентифицирован.")
                continue

            # --- Обработка контактов ---
            elif msg_type == "search_user":
                query = data.get("query", "").lower()
                if not query: continue
                # Исключаем себя из результатов поиска
                results = [nick for nick in users if query in nick.lower() and nick != current_user]
                await websocket.send(json.dumps({"type": "search_result", "users": results}))
                print(f"[handler/search] Поиск по запросу '{query}', найдено: {results}")

            elif msg_type == "add_contact_request":
                to_user = data.get("to")
                if to_user and to_user in users:
                    # Проверяем, не в контактах ли уже
                    if to_user in users[current_user]["contacts"]:
                        print(f"[handler/add_contact] '{to_user}' уже в контактах у '{current_user}'.")
                        continue
                    
                    # Пересылаем запрос получателю
                    await send_to_user(
                        to_user, 
                        {"type": "incoming_contact_request", "from": current_user}
                    )
                else:
                    print(f"[handler/add_contact] Получатель '{to_user}' не найден.")

            elif msg_type == "add_contact_response":
                from_user = data.get("from")
                accepted = data.get("accepted", False)
                
                if from_user and from_user in users:
                    if accepted:
                        # Добавляем контакты в обе стороны
                        users[current_user]["contacts"].add(from_user)
                        users[from_user]["contacts"].add(current_user)
                        print(f"[handler/add_contact_response] '{current_user}' и '{from_user}' теперь контакты.")
                        
                        # Уведомляем обоих пользователей
                        await send_to_user(from_user, {"type": "contact_added", "nickname": current_user})
                        await send_to_user(current_user, {"type": "contact_added", "nickname": from_user})
                    else:
                        # Уведомляем об отклонении
                        await send_to_user(from_user, {"type": "contact_rejected", "nickname": current_user})
                        print(f"[handler/add_contact_response] '{current_user}' отклонил запрос от '{from_user}'.")

            # --- WebRTC Сигналинг и Текстовые сообщения ---
            elif msg_type in ("call", "call_accepted", "call_rejected", "offer", "answer", "candidate", "text_message"):
                to_user = data.get("to")
                if to_user and to_user in online_users:
                    # Просто пересылаем сообщение, добавляя отправителя
                    data["from"] = current_user
                    await online_users[to_user].send(json.dumps(data))
                else:
                    print(f"[handler/forward] Получатель '{to_user}' для '{msg_type}' не найден или не в сети.")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[handler] Соединение закрыто для {current_user or 'unknown'}. Код: {e.code}, причина: {e.reason}")
    except Exception as e:
        print(f"[handler] КРИТИЧЕСКАЯ ОШИБКА в обработчике для {current_user or 'unknown'}: {e}")
    finally:
        if current_user and current_user in online_users:
            del online_users[current_user]
            print(f"[handler/finally] Пользователь '{current_user}' удален из онлайн-списка.")
            await notify_user_list_change()

async def main():
    port = int(os.environ.get("PORT", 8080))
    print(f"Сервер запущен на порту {port}")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())