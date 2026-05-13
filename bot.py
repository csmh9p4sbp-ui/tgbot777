import os
import json
import asyncio
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from groq import Groq

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.error import (
    TimedOut,
    NetworkError,
    RetryAfter,
    TelegramError,
)

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
GROQ_MODEL = os.environ.get(
    "GROQ_MODEL",
    "llama-3.1-8b-instant"
)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

groq_client = (
    Groq(api_key=GROQ_API_KEY)
    if GROQ_API_KEY else None
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

DATA_DIR = "data"

os.makedirs(DATA_DIR, exist_ok=True)

EVENTS_FILE = os.path.join(
    DATA_DIR,
    "events.json"
)

ACA_SOURCE_URL = "https://www.aca-mma.com/en"

AUTO_UPDATE_INTERVAL_SECONDS = 60 * 60 * 6


def load_json(path, default):

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(path, data):

    tmp = path + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(tmp, path)


def get_event():

    data = load_json(
        EVENTS_FILE,
        {"next_event": {}}
    )

    return data.get("next_event", {})


def main_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📅 Ближайший турнир",
                callback_data="next_event"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Кард турнира",
                callback_data="fight_card"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 Что смотреть",
                callback_data="what_watch"
            )
        ],
        [
            InlineKeyboardButton(
                "📺 Смотреть трансляцию",
                callback_data="watch"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Сравнить бойцов",
                callback_data="compare"
            )
        ],
        [
            InlineKeyboardButton(
                "👤 Найти бойца",
                callback_data="fighter"
            )
        ],
    ])


async def safe_send_message(
    bot,
    chat_id,
    text,
    reply_markup=None
):

    try:

        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )

    except RetryAfter as e:

        await asyncio.sleep(
            int(e.retry_after) + 1
        )

        return await safe_send_message(
            bot,
            chat_id,
            text,
            reply_markup
        )

    except (
        TimedOut,
        NetworkError
    ) as e:

        logger.warning(
            f"Telegram network error: {e}"
        )

    except TelegramError as e:

        logger.warning(
            f"Telegram error: {e}"
        )

    except Exception as e:

        logger.warning(
            f"Unknown send error: {e}"
        )


async def safe_query_answer(query):

    try:

        await query.answer()

    except Exception:

        pass


def build_event_text(event):

    return (
        f"🥊 {event.get('title', 'ACA')}\n\n"
        f"📅 Дата: {event.get('date', 'Уточняется')}\n"
        f"🕘 Время: {event.get('time', 'Уточняется')}\n"
        f"📍 Место: {event.get('location', 'Уточняется')}\n"
        f"🏟 Арена: {event.get('venue', 'Уточняется')}\n\n"
        f"🔥 Главный бой:\n"
        f"{event.get('main_event', 'Уточняется')}"
    )


def build_card_text(event):

    card = event.get("card", [])

    if not card:

        return (
            "📋 Кард турнира "
            "пока не опубликован."
        )

    text = "📋 Кард турнира\n\n"

    for i, fight in enumerate(
        card,
        start=1
    ):

        text += f"{i}. {fight}\n"

    return text


async def ask_ai(prompt):

    if not groq_client:

        return (
            "📑 ИИ-аналитик "
            "пока не подключён."
        )

    def run():

        response = (
            groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты MMA-аналитик ACA. "
                            "Отвечай кратко, "
                            "без ставок и азартных игр. "
                            "Фокусируйся на стиле, "
                            "интриге и спортивном контексте."
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
        )

        return (
            response
            .choices[0]
            .message.content
        )

    try:

        return await asyncio.to_thread(run)

    except Exception as e:

        logger.warning(
            f"AI error: {e}"
        )

        return (
            "📑 ИИ-аналитик "
            "временно недоступен."
        )


def fetch_aca_data():

    headers = {
        "User-Agent":
        "Mozilla/5.0 ACA Assistant"
    }

    response = requests.get(
        ACA_SOURCE_URL,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    text = soup.get_text(
        "\n",
        strip=True
    )

    lines = [
        x.strip()
        for x in text.split("\n")
        if x.strip()
    ]

    aca_lines = [
        x for x in lines
        if "ACA" in x
    ]

    title = (
        aca_lines[0]
        if aca_lines else
        "ACA Tournament"
    )

    return {
        "next_event": {
            "title": title,
            "stream_url": ACA_SOURCE_URL,
            "last_updated":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }
    }


def update_cache():

    try:

        current = load_json(
            EVENTS_FILE,
            {"next_event": {}}
        )

        fresh = fetch_aca_data()

        merged = current.copy()

        merged["next_event"].update(
            fresh["next_event"]
        )

        save_json(
            EVENTS_FILE,
            merged
        )

        logger.warning(
            "ACA cache updated"
        )

    except Exception as e:

        logger.warning(
            f"Cache update failed: {e}"
        )


async def auto_update_loop():

    await asyncio.sleep(5)

    while True:

        await asyncio.to_thread(
            update_cache
        )

        await asyncio.sleep(
            AUTO_UPDATE_INTERVAL_SECONDS
        )


async def post_init(app):

    app.create_task(
        auto_update_loop()
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "🥊 ACA Assistant\n\n"
        "Быстрый доступ к турнирам ACA:\n\n"
        "📅 ближайший турнир\n"
        "📋 кард турнира\n"
        "🔥 какие бои стоит смотреть\n"
        "📺 официальная трансляция\n"
        "📊 сравнение бойцов\n"
        "👤 информация о бойцах\n\n"
        "Выбери действие ниже."
    )

    await safe_send_message(
        context.bot,
        update.effective_chat.id,
        text,
        reply_markup=main_menu()
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await safe_query_answer(query)

    chat_id = query.message.chat_id

    data = query.data

    event = get_event()

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

        stream = event.get(
            "stream_url",
            ACA_SOURCE_URL
        )

        text = (
            "📺 Официальная трансляция\n\n"
            f"{stream}"
        )

        await safe_send_message(
            context.bot,
            chat_id,
            text,
            reply_markup=main_menu()
        )

    elif data == "what_watch":

        await safe_send_message(
            context.bot,
            chat_id,
            "📑 Анализирую кард..."
        )

        prompt = (
            "Выбери 3 самых интересных "
            "боя карда ACA и объясни "
            "почему их стоит смотреть.\n\n"
            f"Кард: {event.get('card')}"
        )

        answer = await ask_ai(prompt)

        await safe_send_message(
            context.bot,
            chat_id,
            answer,
            reply_markup=main_menu()
        )

    elif data == "compare":

        context.user_data[
            "mode"
        ] = "compare"

        await safe_send_message(
            context.bot,
            chat_id,
            (
                "📊 Напиши двух бойцов "
                "через vs.\n\n"
                "Например:\n"
                "Шлеменко vs Эмеев"
            )
        )

    elif data == "fighter":

        context.user_data[
            "mode"
        ] = "fighter"

        await safe_send_message(
            context.bot,
            chat_id,
            (
                "👤 Напиши имя бойца."
            )
        )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mode = context.user_data.get(
        "mode"
    )

    text = update.message.text.strip()

    chat_id = update.effective_chat.id

    if mode == "compare":

        context.user_data["mode"] = None

        await safe_send_message(
            context.bot,
            chat_id,
            "📑 Сравниваю бойцов..."
        )

        prompt = (
            "Сравни бойцов ACA/MMA. "
            "Кратко опиши стиль, "
            "сильные стороны и "
            "главную интригу боя.\n\n"
            f"{text}"
        )

        answer = await ask_ai(
            prompt
        )

        await safe_send_message(
            context.bot,
            chat_id,
            answer,
            reply_markup=main_menu()
        )

    elif mode == "fighter":

        context.user_data["mode"] = None

        await safe_send_message(
            context.bot,
            chat_id,
            "📑 Анализирую бойца..."
        )

        prompt = (
            "Кратко расскажи "
            "о бойце ACA/MMA: "
            "стиль, сильные стороны, "
            "что важно знать.\n\n"
            f"{text}"
        )

        answer = await ask_ai(
            prompt
        )

        await safe_send_message(
            context.bot,
            chat_id,
            answer,
            reply_markup=main_menu()
        )

    else:

        await safe_send_message(
            context.bot,
            chat_id,
            (
                "Выбери действие "
                "в меню ниже."
            ),
            reply_markup=main_menu()
        )


async def error_handler(
    update,
    context
):

    logger.warning(
        f"Global error: {context.error}"
    )


app = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .job_queue(None)
    .post_init(post_init)
    .connect_timeout(60)
    .read_timeout(60)
    .write_timeout(60)
    .pool_timeout(60)
    .build()
)

app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

app.add_handler(
    CallbackQueryHandler(
        button_handler
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler
    )
)

app.add_error_handler(
    error_handler
)

app.run_polling(
    drop_pending_updates=True,
    allowed_updates=Update.ALL_TYPES,
)