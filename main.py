from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request
import os

# Tạo ứng dụng Flask
app = Flask(__name__)

# Token bot Telegram
TOKEN = "7243590811:AAGY-Py_DP_561bc2DsPjFKkZTuvp7mSl0o"  # Thay bằng token thật
bot = ApplicationBuilder().token(TOKEN).build()

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Reset game
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

# Đặt webhook
def set_webhook():
    webhook_url = os.getenv("WEBHOOK_URL")  # URL webhook từ Render
    bot.set_webhook(url=webhook_url + "/webhook")

# Các hàm xử lý lệnh
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()  # Reset lại các trạng thái của trò chơi
    global in_game
    in_game = True  # Đánh dấu trò chơi đã bắt đầu

    # Gửi thông báo cho người chơi khi trò chơi bắt đầu
    await update.message.reply_text("🎮 Trò chơi bắt đầu!\nGõ /join để tham gia trò chơi.\nGõ /begin để bắt đầu lượt đầu tiên.")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(f"✅ {user.first_name} đã tham gia... (Tổng {len(players)} )")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_player_index, waiting_for_phrase
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu.")
        return

    waiting_for_phrase = True
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"

    await update.message.reply_text(
        f"✏️ {mention}, hãy nhập cụm từ đầu tiên để bắt đầu trò chơi!",
        parse_mode="HTML")
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return

    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)

        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"

        await update.message.reply_text(
            f"✅ Từ bắt đầu là: '{text}'. {mention}, hãy nối với từ '{text.split()[-1]}'",
            parse_mode="HTML")
        await start_turn_timer(context)
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, reason="Không đúng từ nối")
        return

    if used_phrases.get(text, 0) >= 2:
        await eliminate_player(update, context, reason="Cụm từ bị lặp quá giới hạn")
        return

    used_phrases[text] = used_phrases.get(text, 0) + 1
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} GIÀNH CHIẾN THẮNG!",
                                        parse_mode="HTML")
        reset_game()
        return

    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"

    await update.message.reply_text(
        f"✅ Hợp lệ! '{text.split()[-1]}' là từ cần nối tiếp. {next_mention}, tới lượt bạn!",
        parse_mode="HTML")
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(f"❌ {user.first_name} bị loại! Lý do: {reason}")
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0

    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} GIÀNH CHIẾN THẮNG!", parse_mode="HTML")
        reset_game()
    else:
        await update.message.reply_text(f"Hiện còn lại {len(players)} người chơi.")
        await start_turn_timer(context)

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index
    try:
        await asyncio.sleep(59)
        user_id = players[current_player_index]
        chat = await context.bot.get_chat(user_id)
        mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"

        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"⏰ {mention} hết thời gian và bị loại!",
            parse_mode="HTML")
        players.remove(user_id)

        if len(players) == 1:
            winner_id = players[0]
            winner_chat = await context.bot.get_chat(winner_id)
            mention = f"<a href='tg://user?id={winner_id}'>@{winner_id}</a>"
            await context.bot.send_message(
                chat_id=context._chat_id,
                text=f"🏆 {mention} GIÀNH CHIẾN THẮNG!",
                parse_mode="HTML")
            reset_game()
            return

        if current_player_index >= len(players):
            current_player_index = 0

        await start_turn_timer(context)

    except asyncio.CancelledError:
        pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/startgame - bắt đầu trò chơi\n/join - tham gia\n/begin - người đầu tiên nhập cụm từ\n/help - hướng dẫn")

# Định nghĩa route cho Flask để nhận webhook từ Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = Update.de_json(json_str, bot)
    bot.process_update(update)
    return "OK"

# Định nghĩa route chính để kiểm tra trạng thái
@app.route('/')
def index():
    return "Bot is running!"

# Đặt webhook khi bắt đầu ứng dụng
if __name__ == '__main__':
    set_webhook()  # Đặt webhook khi bot bắt đầu
    app.run(host="0.0.0.0", port=5000)  # Render sẽ cung cấp cổng 5000
