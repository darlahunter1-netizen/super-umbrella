import logging
import random
import sqlite3
import os
import asyncio
from datetime import datetime, timedelta
from threading import Thread

from flask import Flask, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, ChatJoinRequestHandler

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не найден!")

GROUP_CHAT_ID = -1003431090434  # ← свой ID группы
ADMIN_ID = 998091317            # ← свой ID

DB_FILE = "users.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/")
def health():
    return jsonify({"status": "ok"}), 200

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 full_name TEXT,
                 joined_at TIMESTAMP
                 )""")
    conn.commit()
    conn.close()

def add_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
                 (user_id, username, full_name, datetime.now()))
    conn.commit()
    conn.close()

def get_users_count():
    conn = sqlite3.connect(DB_FILE)
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count

def get_all_user_ids():
    conn = sqlite3.connect(DB_FILE)
    ids = [row[0] for row in conn.execute("SELECT user_id FROM users")]
    conn.close()
    return ids

pending = {}

def make_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    return a + b, f"{a} + {b} = ?"

async def join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if not req or req.chat.id != GROUP_CHAT_ID:
        return

    user = req.from_user
    ans, q = make_captcha()
    opts = [ans, ans + random.randint(1, 5), ans - random.randint(1, 5)]
    random.shuffle(opts)

    kb = [[InlineKeyboardButton(str(x), callback_data=f"cap_{x}_{user.id}")] for x in opts]

    pending[user.id] = {"answer": ans, "expires": datetime.now() + timedelta(minutes=5), "chat_id": req.chat.id}

    await context.bot.send_message(
        user.id,
        f"Решите, чтобы вступить:\n\n<b>{q}</b>\n\n5 минут!",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML"
    )

async def cap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    try:
        _, val_str, uid_str = q.data.split("_")
        val = int(val_str)
        uid = int(uid_str)
    except:
        await q.edit_message_text("Ошибка кнопки")
        return

    if uid != q.from_user.id or uid not in pending:
        await q.edit_message_text("Не твоя капча")
        return

    data = pending[uid]

    if datetime.now() > data["expires"]:
        await q.edit_message_text("Время вышло")
        del pending[uid]
        return

    if val == data["answer"]:
        add_user(uid, q.from_user.username, q.from_user.full_name)

        text = (
            "🎉 <b>Пройдено!</b>\n\n"
            "Заявка в обработке. Мы проверим и добавим вас в группу скоро 🚀\n"
            "Спасибо за терпение!"
        )
        photo = "https://i.imgur.com/0Z8Z8Z8.jpeg"  # ← можно поменять

        await context.bot.send_photo(uid, photo, caption=text, parse_mode="HTML")
        await q.edit_message_text("✅ Готово!")
    else:
        await q.edit_message_text("❌ Неверно.")

    del pending[uid]

async def start(update: Update, _):
    u = update.effective_user
    add_user(u.id, u.username, u.full_name)
    await update.message.reply_text("Привет! Подай заявку в группу — пришлю капчу.")

async def stats(update: Update, _):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(f"Пользователей: {get_users_count()}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Напиши: /broadcast текст")
        return

    text = " ".join(context.args)
    users = get_all_user_ids()
    ok = fail = 0

    await update.message.reply_text(f"Рассылаю {len(users)} людям...")

    for uid in users:
        try:
            await context.bot.send_message(uid, text)
            ok += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(f"Готово\nУспех: {ok}\nОшибок: {fail}")

# Приложение
application = Application.builder().token(TOKEN).build()

application.add_handler(ChatJoinRequestHandler(join_handler))
application.add_handler(CallbackQueryHandler(cap_handler, pattern="^cap_"))
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(CommandHandler("broadcast", broadcast))

init_db()

def polling():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_forever()
    except Exception as e:
        logger.error(e)
    finally:
        loop.run_until_complete(application.stop())
        loop.run_until_complete(application.shutdown())
        loop.close()

if __name__ == "__main__":
    Thread(target=polling, daemon=True).start()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)