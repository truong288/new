import json
import os
import asyncio
import threading
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

# === CONFIG ===
BOT_TOKEN = "PASTE_YOUR_TOKEN_HERE"
WEBHOOK_URL = "https://your-render-url.onrender.com"  # Không có dấu "/" ở cuối
PORT = 8080

# === GAME STATE ===
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# === WINNERS FILE ===
WINNER_FILE = "winners.json"


def load_winners():
    if os.path.exists(WINNER_FILE):
        with open(WINNER_FILE, "r") as f:
            return json.load(f)
    return {}


def save_winner(user_id):
    winners = load_winners()
    winners[str(user_id)] = winners.get(str(user_id), 0) + 1
    with open(WINNER_FILE, "w") as f:
        json.dump(winners, f)


def reset_game():
    global players, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task
    players = []
    current_phrase = ""
    used_phrases = {}
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None


# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gõ /play để bắt đầu trò chơi nối cụm từ!")


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True
    keyboard = [
        [InlineKeyboardButton("✅ Tham gia", callback_data='join')],
        [InlineKeyboardButton("▶️ Bắt đầu", callback_data='begin')]
    ]
    await update.message.reply_text("🎮 Trò chơi bắt đầu! Bấm để tham gia hoặc bắt đầu:", reply_markup=InlineKeyboardMarkup(keyboard))


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "join":
        if user.id not in players:
            players.append(user.id)
            await query.message.reply_text(f"✅ {user.first_name} đã tham gia.")
        else:
            await query.message.reply_text("⚠️ Bạn đã tham gia rồi!")

    elif query.data == "begin":
        if len(players) < 2:
            await query.message.reply_text("❗ Cần ít nhất 2 người chơi.")
            return
        await query.message.delete()
        await begin_game(update, context)


async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase
    waiting_for_phrase = True
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✏️ {mention}, hãy nhập cụm từ đầu tiên!", parse_mode="HTML")
    await start_turn_timer(context)


async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase
    if not in_game:
        return
    user = update.effective_user
    text = update.message.text.strip().lower()
    if user.id != players[current_player_index]:
        return
    words = text.split()
    if len(words) != 2:
        await eliminate_player(update, context, "Cụm từ phải gồm đúng 2 từ.")
        return
    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
    else:
        if words[0] != current_phrase.split()[-1]:
            await eliminate_player(update, context, "Từ đầu không khớp.")
            return
        if text in used_phrases:
            await eliminate_player(update, context, "Cụm từ đã được dùng.")
            return
        used_phrases[text] = 1
        current_phrase = text

    current_player_index = (current_player_index + 1) % len(players)
    if len(players) == 1:
        await announce_winner(update, context, players[0])
        return
    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
    await update.message.reply_text(f"✅ '{words[-1]}' đúng! {mention}, tới lượt bạn.", parse_mode="HTML")
    await start_turn_timer(context)


async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(f"❌ {user.first_name} bị loại! Lý do: {reason}")
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0
    if len(players) == 1:
        await announce_winner(update, context, players[0])
    else:
        await start_turn_timer(context)


async def announce_winner(update, context, winner_id):
    chat = await context.bot.get_chat(winner_id)
    mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🏆 {mention} GIÀNH CHIẾN THẮNG!", parse_mode="HTML")
    save_winner(winner_id)
    reset_game()


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    winners = load_winners()
    sorted_winners = sorted(winners.items(), key=lambda x: x[1], reverse=True)
    msg = "🏅 Bảng xếp hạng:\n"
    for uid, score in sorted_winners[:5]:
        chat = await context.bot.get_chat(int(uid))
        name = chat.username or chat.first_name
        msg += f"• {name}: {score} lần thắng\n"
    await update.message.reply_text(msg)


async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()

    async def timeout():
        await asyncio.sleep(30)
        user_id = players[current_player_index]
        chat = await context.bot.get_chat(user_id)
        await context.bot.send_message(chat_id=chat.id, text="⌛ Hết giờ! Bạn bị loại.")
        update = Update(update_id=0, message=None)
        update.effective_user = chat
        await eliminate_player(update, context, "Hết thời gian")

    turn_timeout_task = asyncio.create_task(timeout())


# === FLASK APP ===
flask_app = Flask(__name__)
app = ApplicationBuilder().token(BOT_TOKEN).build()


@flask_app.route('/')
def index():
    return "Bot is alive!"


@flask_app.route('/webhook', methods=["POST"])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return "OK"


async def setup_webhook():
    await app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")


def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)


# === MAIN ===
if __name__ == '__main__':
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", start_game))
    app.add_handler(CommandHandler("top", show_leaderboard))
    app.add_handler(CallbackQueryHandler(menu_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    # Chạy Flask trong thread phụ
    threading.Thread(target=run_flask).start()

    # Chạy Telegram app + webhook
    asyncio.run(setup_webhook())
