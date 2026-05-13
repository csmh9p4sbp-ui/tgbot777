import os
import json
import logging
import asyncio
from groq import Groq

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
FIGHTERS_FILE = os.path.join(DATA_DIR, "fighters.json")


def ensure_demo_data():
    if not os.path.exists(EVENTS_FILE):
        demo_events = {
            "next_event": {
                "title": "ACA — ближайший турнир",
                "date": "Дата уточняется",
                "location": "Локация уточняется",
                "main_event": "Главный бой уточняется",
                "stream_url": "https://www.aca-mma.com/",
                "card": [
                    "Главный бой уточняется",
                    "Со-главный бой уточняется",
                    "Кард будет обновлён ближе к турниру"
                ]
            }
        }

        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(demo_events, f, ensure_ascii=False, indent=2)

    if not os.path.exists(FIGHTERS_FILE):
        demo_fighters = {
            "fighters": []
        }

        with open(FIGHTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(demo_fighters, f, ensure_ascii=False, indent=2)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def get_next_event():
    data = load_json(EVENTS_FILE, {})
    return data.get("next_event")


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Ближайший турнир", callback_data="next_event")],
        [InlineKeyboardButton("📋 Кард турнира", callback_data="fight_card")],
        [InlineKeyboardButton("🔥 Что смотреть", callback_data="what_watch")],
        [InlineKeyboardButton("📺 Смотреть трансляцию", callback_data="watch")],
        [InlineKeyboardButton("📊 Сравнить бойцов", callback_data="compare_info")],
        [InlineKeyboardButton("👤 Найти бойца", callback_data="fighter_info")],
    ])


async def safe_send_message(bot, chat_id, text, reply_markup=None):
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
    except RetryAfter as e:
        await asyncio.sleep(int(e.retry_after) + 1)
        return await safe_send_message(bot, chat_id, text, reply_markup)
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Telegram network error: {e}")
    except TelegramError as e:
        logger.warning(f"Telegram error: {e}")
    except Exception as e:
        logger.warning(f"Unknown send error: {e}")


async def safe_query_answer(query):
    try:
        await query.answer()
    except Exception:
        pass


def build_event_text(event):
    return (
        f"🥊 {event.get('title', 'ACA')}\n\n"
        f"📅 Дата: {event.get('date', 'Уточняется')}\n"
        f"📍 Место: {event.get('location', 'Уточняется')}\n\n"
        f"🔥 Главный бой:\n{event.get('main_event', 'Уточняется')}"
    )


def build_card_text(event):
    card = event.get("card", [])

    if not card:
        return "📋 Кард турнира пока не опубликован."

    text = "📋 Кард турнира\n\n"

    for i, fight in enumerate(card, start=1):
        text += f"{i}. {fight}\n"

    return text


async def ask_ai(prompt):
    if not groq_client:
        return "📑 ИИ-аналитик пока не подключён. Добавь GROQ_API_KEY."

    def run():
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты MMA-аналитик для фанатов ACA. "
                        "Отвечай кратко, понятно, без ставок и без призывов к азартным играм. "
                        "Фокусируйся на стиле бойцов, интриге боя и спортивном контексте."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.4,
            max_tokens=600,
        )

        return response.choices[0].message.content or "Не получилось получить ответ."

    try:
        return await asyncio.to_thread(run)
    except Exception as e:
        logger.warning(f"AI error: {e}")
        return "📑 ИИ-аналитик временно недоступен. Попробуй позже."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_demo_data()

    text = (
        "🥊 ACA Assistant\n\n"
        "Бот помогает быстро разобраться в турнирах ACA:\n\n"
        "📅 ближайший турнир\n"
        "📋 кард боёв\n"
        "🔥 какие бои стоит смотреть\n"
        "📺 официальная трансляция\n"
        "📊 сравнение бойцов\n"
        "👤 поиск бойца\n\n"
        "Выбери действие ниже."
    )

    await safe_send_message(
        context.bot,
        update.effective_chat.id,
        text,
        reply_markup=main_menu()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)

    chat_id = query.message.chat_id
    data = query.data
    event = get_next_event()

    if not event:
        await safe_send_message(context.bot, chat_id, "Данные турнира пока не загружены.")
        return

    if data == "next_event":
        await safe_send_message(
            context.bot,
            chat_id,
            build_event_text(event),
            reply_markup=main_menu()
        )

    elif data == "fight_card":
        await safe_send_message(
            context.bot,
            chat_id,
            build_card_text(event),
            reply_markup=main_menu()
        )

    elif data == "watch":
        stream_url = event.get("stream_url")

        if stream_url:
            text = (
                "📺 Официальная трансляция\n\n"
                "Открой официальный источник ниже:\n\n"
                f"{stream_url}"
            )
        else:
            text = (
                "📺 Ссылка на официальную трансляцию пока не опубликована.\n\n"
                "Бот покажет её, когда она появится в данных."
            )

        await safe_send_message(context.bot, chat_id, text, reply_markup=main_menu())

    elif data == "what_watch":
        prompt = (
            "На основе этого карда выбери 3 боя, которые стоит смотреть, "
            "и коротко объясни почему. Не делай прогнозов для ставок.\n\n"
            f"Турнир: {event.get('title')}\n"
            f"Главный бой: {event.get('main_event')}\n"
            f"Кард: {event.get('card')}"
        )

        await safe_send_message(context.bot, chat_id, "📑 Анализирую кард...")
        answer = await ask_ai(prompt)
        await safe_send_message(context.bot, chat_id, answer, reply_markup=main_menu())

    elif data == "compare_info":
        context.user_data["mode"] = "compare"

        await safe_send_message(
            context.bot,
            chat_id,
            "📊 Напиши двух бойцов через vs.\n\nНапример:\nБагов vs Вагаев"
        )

    elif data == "fighter_info":
        context.user_data["mode"] = "fighter"

        await safe_send_message(
            context.bot,
            chat_id,
            "👤 Напиши имя бойца, которого нужно найти."
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    mode = context.user_data.get("mode")

    if mode == "compare":
        context.user_data["mode"] = None

        prompt = (
            "Сравни этих двух бойцов как MMA-аналитик. "
            "Не делай прогнозов для ставок. "
            "Дай кратко: стиль, сильные стороны, возможный ключ боя.\n\n"
            f"Бойцы: {text}"
        )

        await update.message.reply_text("📑 Сравниваю бойцов...")
        answer = await ask_ai(prompt)
        await safe_send_message(context.bot, chat_id, answer, reply_markup=main_menu())

    elif mode == "fighter":
        context.user_data["mode"] = None

        prompt = (
            "Кратко расскажи о бойце ACA/MMA. "
            "Опиши стиль, сильные стороны и что о нём важно знать фанату. "
            "Если данных недостаточно, скажи об этом честно.\n\n"
            f"Боец: {text}"
        )

        await update.message.reply_text("📑 Ищу информацию по бойцу...")
        answer = await ask_ai(prompt)
        await safe_send_message(context.bot, chat_id, answer, reply_markup=main_menu())

    else:
        await safe_send_message(
            context.bot,
            chat_id,
            "Выбери действие в меню ниже.",
            reply_markup=main_menu()
        )


async def error_handler(update, context):
    logger.warning(f"Global error: {context.error}")


ensure_demo_data()

app = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .job_queue(None)
    .connect_timeout(60)
    .read_timeout(60)
    .write_timeout(60)
    .pool_timeout(60)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_error_handler(error_handler)

app.run_polling(
    drop_pending_updates=True,
    allowed_updates=Update.ALL_TYPES,
)