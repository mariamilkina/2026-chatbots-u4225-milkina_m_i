import asyncio
import json
import logging
import os
import random
import re
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

import httpx

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import (
    delete_word,
    get_lesson_stats,
    get_saved_words,
    get_user,
    init_db,
    save_lesson_result,
    save_test_result,
    save_word,
    update_goal,
)


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MERRIAM_WEBSTER_API_KEY = os.getenv("MERRIAM_WEBSTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


QUESTIONS = [
    {
        "question": "Choose the correct option:\n\nI ___ a student.",
        "options": ["am", "is", "are", "be"],
        "correct": 0,
    },
    {
        "question": "Choose the correct option:\n\nShe ___ coffee every morning.",
        "options": ["drink", "drinks", "drinking", "is drink"],
        "correct": 1,
    },
    {
        "question": "Choose the correct option:\n\nWe ___ to the cinema yesterday.",
        "options": ["go", "gone", "went", "going"],
        "correct": 2,
    },
    {
        "question": "Choose the correct option:\n\nThere isn't ___ milk in the fridge.",
        "options": ["some", "many", "any", "few"],
        "correct": 2,
    },
    {
        "question": "Choose the correct option:\n\nI ___ here for three years.",
        "options": ["live", "lived", "have lived", "am living yesterday"],
        "correct": 2,
    },
    {
        "question": "Choose the correct option:\n\nIf it rains tomorrow, we ___ at home.",
        "options": ["stay", "stayed", "will stay", "would stay"],
        "correct": 2,
    },
    {
        "question": "Choose the correct option:\n\nWhen I arrived, they ___ dinner.",
        "options": ["had", "were having", "have", "are having"],
        "correct": 1,
    },
    {
        "question": "Choose the correct option:\n\nThis book ___ by millions of people every year.",
        "options": ["reads", "is read", "was reading", "has read"],
        "correct": 1,
    },
    {
        "question": "Choose the correct option:\n\nShe asked me where I ___.",
        "options": ["live", "lived", "will live", "am living"],
        "correct": 1,
    },
    {
        "question": "Choose the best option:\n\nI wish I ___ more free time.",
        "options": ["have", "had", "will have", "am having"],
        "correct": 1,
    },
    {
        "question": "Choose the correct option:\n\nBy the time we got there, the train ___.",
        "options": ["left", "has left", "had left", "was leaving now"],
        "correct": 2,
    },
    {
        "question": "Choose the best option:\n\nHardly ___ the meeting started when the fire alarm went off.",
        "options": ["did", "had", "has", "was"],
        "correct": 1,
    },
]


# Три задания зависят прежде всего от уровня.
LEVEL_TASKS: Dict[str, List[dict]] = {
    "A1": [
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nMy brother ___ 20 years old.",
            "options": ["am", "is", "are", "be"],
            "correct": 1,
            "explanation": "With he/she/it we use 'is'.",
        },
        {
            "type": "text",
            "question": "Translate into English:\n\n«У меня есть собака.»",
            "answers": ["i have a dog", "i've got a dog", "i have got a dog"],
            "answer_display": "I have a dog.",
            "explanation": "'I have a dog' is a natural basic way to express possession.",
        },
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nThey ___ football on Sundays.",
            "options": ["plays", "play", "playing", "is play"],
            "correct": 1,
            "explanation": "With 'they' in Present Simple we use the base verb: play.",
        },
    ],
    "A2": [
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nI ___ this film last week.",
            "options": ["see", "saw", "have see", "seeing"],
            "correct": 1,
            "explanation": "A finished time ('last week') requires Past Simple: saw.",
        },
        {
            "type": "text",
            "question": "Translate into English:\n\n«Я собираюсь купить новый телефон.»",
            "answers": [
                "i am going to buy a new phone",
                "i'm going to buy a new phone",
            ],
            "answer_display": "I'm going to buy a new phone.",
            "explanation": "'Be going to' is used for plans and intentions.",
        },
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nThere are ___ people in the room.",
            "options": ["much", "many", "any much", "a little"],
            "correct": 1,
            "explanation": "'People' is countable plural, so we use 'many'.",
        },
    ],
    "B1": [
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nIf I had more time, I ___ Spanish too.",
            "options": ["learn", "will learn", "would learn", "learned yesterday"],
            "correct": 2,
            "explanation": "Second Conditional: if + Past Simple, would + verb.",
        },
        {
            "type": "text",
            "question": "Translate into English:\n\n«Я живу здесь уже три года.»",
            "answers": [
                "i have lived here for three years",
                "i've lived here for three years",
                "i have been living here for three years",
                "i've been living here for three years",
            ],
            "answer_display": "I've lived here for three years.",
            "explanation": "Use Present Perfect with 'for' for a situation continuing until now.",
        },
        {
            "type": "mcq",
            "question": "Choose the correct option:\n\nShe told me that she ___ the report already.",
            "options": ["finishes", "had finished", "will finish", "finish"],
            "correct": 1,
            "explanation": "Past Perfect shows the report was finished before the past reporting moment.",
        },
    ],
    "B2": [
        {
            "type": "mcq",
            "question": "Choose the best option:\n\nHad I known about the delay, I ___ earlier.",
            "options": ["would leave", "would have left", "left", "had leave"],
            "correct": 1,
            "explanation": "This is an inverted third conditional: Had I known..., I would have left...",
        },
        {
            "type": "text",
            "question": "Translate naturally into English:\n\n«Несмотря на нехватку времени, мы закончили проект в срок.»",
            "answers": [
                "despite the lack of time we finished the project on time",
                "despite having little time we finished the project on time",
                "in spite of the lack of time we finished the project on time",
                "despite the time pressure we finished the project on time",
            ],
            "answer_display": "Despite the lack of time, we finished the project on time.",
            "explanation": "After 'despite' use a noun/gerund phrase, not 'despite of'.",
        },
        {
            "type": "mcq",
            "question": "Choose the best option:\n\nThe proposal, ___ was submitted yesterday, still needs approval.",
            "options": ["that", "which", "what", "where"],
            "correct": 1,
            "explanation": "A non-defining relative clause after a comma uses 'which'.",
        },
    ],
}


# Два задания зависят и от цели, и от уровня.
GOAL_TASKS: Dict[str, Dict[str, List[dict]]] = {
    "General English": {
        "A1": [
            {
                "type": "mcq",
                "question": "Choose the correct option:\n\nI usually ___ breakfast at 8.",
                "options": ["have", "has", "having", "am have"],
                "correct": 0,
                "explanation": "With 'I' in Present Simple use the base form: have.",
            },
            {
                "type": "text",
                "question": "Write in English:\n\n«Сегодня хорошая погода.»",
                "answers": ["the weather is good today", "it's nice weather today", "the weather is nice today"],
                "answer_display": "The weather is nice today.",
                "explanation": "A natural phrase is 'The weather is nice today.'",
            },
        ],
        "A2": [
            {
                "type": "mcq",
                "question": "Choose the correct option:\n\nI've known Anna ___ 2022.",
                "options": ["for", "since", "from", "during"],
                "correct": 1,
                "explanation": "Use 'since' with a starting point in time.",
            },
            {
                "type": "text",
                "question": "Write in English:\n\n«Я ещё не закончил эту книгу.»",
                "answers": ["i haven't finished this book yet", "i have not finished this book yet"],
                "answer_display": "I haven't finished this book yet.",
                "explanation": "Present Perfect + 'yet' is natural for something not completed up to now.",
            },
        ],
        "B1": [
            {
                "type": "mcq",
                "question": "Choose the best option:\n\nI wasn't used to ___ so early.",
                "options": ["wake up", "waking up", "woke up", "be wake"],
                "correct": 1,
                "explanation": "'Be used to' is followed by a noun or gerund.",
            },
            {
                "type": "text",
                "question": "Write a natural English sentence:\n\n«Если погода улучшится, мы пойдём гулять.»",
                "answers": [
                    "if the weather improves we will go for a walk",
                    "if the weather gets better we will go for a walk",
                    "if the weather improves we'll go for a walk",
                    "if the weather gets better we'll go for a walk",
                ],
                "answer_display": "If the weather improves, we'll go for a walk.",
                "explanation": "First Conditional: if + Present Simple, will + verb.",
            },
        ],
        "B2": [
            {
                "type": "mcq",
                "question": "Choose the best option:\n\nI'd rather you ___ me before making a decision.",
                "options": ["ask", "asked", "will ask", "have ask"],
                "correct": 1,
                "explanation": "After 'I'd rather you...' we use a past form for a present/future preference.",
            },
            {
                "type": "text",
                "question": "Write naturally in English:\n\n«Я бы предпочла обсудить это лично.»",
                "answers": [
                    "i would prefer to discuss this in person",
                    "i'd prefer to discuss this in person",
                    "i would rather discuss this in person",
                    "i'd rather discuss this in person",
                ],
                "answer_display": "I'd prefer to discuss this in person.",
                "explanation": "'Prefer to discuss' and 'would rather discuss' are both natural here.",
            },
        ],
    },
    "Speaking": {
        "A1": [
            {
                "type": "mcq",
                "question": "You meet someone for the first time. Choose the most natural reply:\n\nNice to meet you!",
                "options": ["Nice to meet you too!", "I am meet.", "Good night.", "No, I don't."],
                "correct": 0,
                "explanation": "'Nice to meet you too!' is the standard polite response.",
            },
            {
                "type": "text",
                "question": "Write a short answer in English:\n\nWhere are you from?",
                "answers": ["i am from russia", "i'm from russia", "i am from saint petersburg", "i'm from saint petersburg"],
                "answer_display": "I'm from Russia.",
                "explanation": "Use 'I'm from...' to say where you come from.",
            },
        ],
        "A2": [
            {
                "type": "mcq",
                "question": "Choose the most natural phrase when you didn't hear someone:",
                "options": ["Can you say that again, please?", "Say again you.", "Repeat me.", "What you say?"],
                "correct": 0,
                "explanation": "'Can you say that again, please?' is polite and natural.",
            },
            {
                "type": "text",
                "question": "Write a short reply:\n\nWhat do you usually do at weekends?",
                "answers": [
                    "i usually meet my friends",
                    "i usually relax at home",
                    "i usually play tennis",
                    "i usually spend time with my friends",
                ],
                "answer_display": "I usually meet my friends.",
                "explanation": "Use Present Simple to describe routines.",
            },
        ],
        "B1": [
            {
                "type": "mcq",
                "question": "Choose the most natural way to disagree politely:",
                "options": ["You're wrong.", "I see your point, but I don't completely agree.", "No.", "This is bad."],
                "correct": 1,
                "explanation": "This phrase acknowledges the other person before expressing disagreement.",
            },
            {
                "type": "text",
                "question": "Complete naturally:\n\nIn my opinion, learning English is important because ...",
                "answers": [
                    "it helps me communicate with people",
                    "it helps people communicate",
                    "it gives me more opportunities",
                    "it is useful for work and travel",
                ],
                "answer_display": "In my opinion, learning English is important because it gives me more opportunities.",
                "explanation": "A complete reason after 'because' makes the opinion sound natural.",
            },
        ],
        "B2": [
            {
                "type": "mcq",
                "question": "Choose the most diplomatic phrase in a discussion:",
                "options": [
                    "That's nonsense.",
                    "I understand your perspective, although I'd approach it differently.",
                    "You're definitely wrong.",
                    "I refuse this opinion.",
                ],
                "correct": 1,
                "explanation": "It signals disagreement while keeping the tone constructive.",
            },
            {
                "type": "text",
                "question": "Reply naturally in one sentence:\n\nWhat would you say if you needed a few seconds to think during a conversation?",
                "answers": [
                    "that's a good question let me think for a moment",
                    "let me think about that for a moment",
                    "give me a second to think about that",
                    "let me think for a second",
                ],
                "answer_display": "That's a good question — let me think for a moment.",
                "explanation": "This buys thinking time without breaking the flow of conversation.",
            },
        ],
    },
    "Travel": {
        "A1": [
            {
                "type": "mcq",
                "question": "At a café, choose the correct phrase:",
                "options": ["I'd like a coffee, please.", "I coffee want.", "Give coffee.", "I am coffee."],
                "correct": 0,
                "explanation": "'I'd like..., please' is a polite basic ordering phrase.",
            },
            {
                "type": "text",
                "question": "Translate into English:\n\n«Где туалет?»",
                "answers": ["where is the toilet", "where's the toilet", "where is the restroom", "where's the restroom", "where is the bathroom"],
                "answer_display": "Where is the restroom?",
                "explanation": "Use 'Where is...?' to ask for a location.",
            },
        ],
        "A2": [
            {
                "type": "mcq",
                "question": "At a hotel, choose the most natural question:",
                "options": ["What time is check-out?", "When check-out be?", "Check-out what?", "What hour checkout is doing?"],
                "correct": 0,
                "explanation": "'What time is check-out?' is a natural hotel question.",
            },
            {
                "type": "text",
                "question": "Translate into English:\n\n«Я забронировала номер на две ночи.»",
                "answers": [
                    "i booked a room for two nights",
                    "i have booked a room for two nights",
                    "i've booked a room for two nights",
                ],
                "answer_display": "I booked a room for two nights.",
                "explanation": "'Book a room for two nights' is the standard phrase.",
            },
        ],
        "B1": [
            {
                "type": "mcq",
                "question": "Your flight is cancelled. Choose the most useful question:",
                "options": [
                    "Why plane no go?",
                    "Could you tell me what my rebooking options are?",
                    "Give another flight.",
                    "Where is flying?",
                ],
                "correct": 1,
                "explanation": "'Rebooking options' is useful language in disruption situations.",
            },
            {
                "type": "text",
                "question": "Translate naturally:\n\n«Можно ли оставить багаж после выселения из номера?»",
                "answers": [
                    "can i leave my luggage after check out",
                    "can i leave my luggage after checkout",
                    "could i leave my luggage after check out",
                    "could i leave my luggage after checkout",
                ],
                "answer_display": "Could I leave my luggage after check-out?",
                "explanation": "'Could I...?' sounds polite in a hotel context.",
            },
        ],
        "B2": [
            {
                "type": "mcq",
                "question": "Choose the most natural phrase at a hotel reception:",
                "options": [
                    "I was wondering whether a late check-out might be possible.",
                    "I wonder late checkout can.",
                    "Make checkout later.",
                    "Is late exit hotel?",
                ],
                "correct": 0,
                "explanation": "'I was wondering whether...' is a polite advanced request.",
            },
            {
                "type": "text",
                "question": "Translate naturally:\n\n«Не могли бы вы порекомендовать место, которое не слишком туристическое?»",
                "answers": [
                    "could you recommend somewhere that isn't too touristy",
                    "could you recommend a place that isn't too touristy",
                    "could you recommend somewhere that's not too touristy",
                    "could you recommend a place that's not too touristy",
                ],
                "answer_display": "Could you recommend somewhere that isn't too touristy?",
                "explanation": "'Touristy' is a common informal adjective for places heavily oriented toward tourists.",
            },
        ],
    },
    "Work": {
        "A1": [
            {
                "type": "mcq",
                "question": "Choose the correct phrase:",
                "options": ["I work in a bank.", "I am work in bank.", "I working bank.", "I do bank work in."],
                "correct": 0,
                "explanation": "Use Present Simple to say where you work.",
            },
            {
                "type": "text",
                "question": "Translate into English:\n\n«У меня встреча в десять.»",
                "answers": ["i have a meeting at ten", "i've got a meeting at ten", "i have got a meeting at ten"],
                "answer_display": "I have a meeting at ten.",
                "explanation": "We say 'have a meeting' and use 'at' with clock times.",
            },
        ],
        "A2": [
            {
                "type": "mcq",
                "question": "Choose the best email phrase:",
                "options": ["Please find the file attached.", "File attach there.", "I attacheding file.", "Look file."],
                "correct": 0,
                "explanation": "'Please find the file attached' is a standard email phrase.",
            },
            {
                "type": "text",
                "question": "Translate into English:\n\n«Я отправлю отчёт сегодня вечером.»",
                "answers": ["i will send the report this evening", "i'll send the report this evening", "i will send the report tonight", "i'll send the report tonight"],
                "answer_display": "I'll send the report this evening.",
                "explanation": "Use 'will' for a straightforward future commitment.",
            },
        ],
        "B1": [
            {
                "type": "mcq",
                "question": "Choose the most professional phrase:",
                "options": [
                    "I need answer now.",
                    "Could you get back to me by Friday?",
                    "Answer Friday.",
                    "You must reply.",
                ],
                "correct": 1,
                "explanation": "'Could you get back to me by Friday?' is polite and professional.",
            },
            {
                "type": "text",
                "question": "Translate naturally:\n\n«Давайте перенесём встречу на завтра.»",
                "answers": [
                    "let's move the meeting to tomorrow",
                    "let us move the meeting to tomorrow",
                    "let's reschedule the meeting for tomorrow",
                    "let us reschedule the meeting for tomorrow",
                ],
                "answer_display": "Let's reschedule the meeting for tomorrow.",
                "explanation": "'Reschedule the meeting' is standard business English.",
            },
        ],
        "B2": [
            {
                "type": "mcq",
                "question": "Choose the most professional sentence:",
                "options": [
                    "We need to align on the next steps before Friday.",
                    "We need same thoughts next steps before Friday.",
                    "We should make alignment Friday.",
                    "We must discuss all because yes.",
                ],
                "correct": 0,
                "explanation": "'Align on the next steps' is common professional English.",
            },
            {
                "type": "text",
                "question": "Translate naturally into business English:\n\n«Я уточню детали и вернусь к вам до конца дня.»",
                "answers": [
                    "i'll clarify the details and get back to you by the end of the day",
                    "i will clarify the details and get back to you by the end of the day",
                    "i'll check the details and get back to you by the end of the day",
                    "i will check the details and get back to you by the end of the day",
                    "i'll confirm the details and get back to you by the end of the day",
                    "i will confirm the details and get back to you by the end of the day",
                ],
                "answer_display": "I'll clarify the details and get back to you by the end of the day.",
                "explanation": "'Get back to you' is a natural professional phrase meaning 'reply/follow up'.",
            },
        ],
    },
}


def normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("’", "'").replace("`", "'")
    value = re.sub(r"[.,!?;:]+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def get_level(score: int) -> str:
    if score <= 3:
        return "A1"
    if score <= 6:
        return "A2"
    if score <= 9:
        return "B1"
    return "B2"


def answer_keyboard(question_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=option,
                callback_data=f"answer:{question_index}:{option_index}",
            )
        ]
        for option_index, option in enumerate(QUESTIONS[question_index]["options"])
    ]
    return InlineKeyboardMarkup(buttons)


def goal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("General English", callback_data="goal:General English"),
                InlineKeyboardButton("Speaking", callback_data="goal:Speaking"),
            ],
            [
                InlineKeyboardButton("Travel", callback_data="goal:Travel"),
                InlineKeyboardButton("Work", callback_data="goal:Work"),
            ],
        ]
    )


def lesson_keyboard(session_id: str, task_index: int, task: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=option,
                    callback_data=f"lesson:{session_id}:{task_index}:{option_index}",
                )
            ]
            for option_index, option in enumerate(task["options"])
        ]
    )


def build_lesson(level: str, goal: str) -> List[dict]:
    level_tasks = LEVEL_TASKS.get(level, LEVEL_TASKS["B1"])
    goal_tasks = GOAL_TASKS.get(goal, GOAL_TASKS["General English"]).get(
        level,
        GOAL_TASKS["General English"]["B1"],
    )
    return [dict(task) for task in level_tasks + goal_tasks]


async def retry_telegram_call(callable_obj, *args, retries: int = 2, **kwargs):
    for attempt in range(retries + 1):
        try:
            return await callable_obj(*args, **kwargs)
        except (TimedOut, NetworkError) as exc:
            if attempt >= retries:
                logger.warning(
                    "Telegram network request failed after %s attempts: %s",
                    retries + 1,
                    exc,
                )
                raise
            wait_seconds = 0.5 * (attempt + 1)
            logger.warning(
                "Temporary Telegram network error: %s. Retry in %.1fs.",
                exc,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)


async def safe_reply(message, text: str, reply_markup=None) -> None:
    try:
        await retry_telegram_call(
            message.reply_text,
            text,
            reply_markup=reply_markup,
            retries=2,
        )
    except (TimedOut, NetworkError):
        logger.warning("Не удалось отправить сообщение после повторных попыток.")


async def acknowledge_callback(query) -> None:
    try:
        await retry_telegram_call(query.answer, retries=1)
    except (TimedOut, NetworkError):
        logger.warning("Не удалось быстро подтвердить callback.")


async def edit_callback_message(
    query,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    try:
        await retry_telegram_call(
            query.edit_message_text,
            text=text,
            reply_markup=reply_markup,
            retries=2,
        )
        return True
    except (TimedOut, NetworkError):
        logger.warning("Could not edit callback message because of network timeout.")
        return False
    except TelegramError as exc:
        logger.error("Telegram API error while editing message: %s", exc)
        return False


def clear_lesson_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "lesson_session_id",
        "lesson_tasks",
        "lesson_index",
        "lesson_score",
        "lesson_answered",
        "lesson_level",
        "lesson_goal",
    ):
        context.user_data.pop(key, None)


def clear_review_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "review_session_id",
        "review_pool",
        "review_items",
        "review_index",
        "review_score",
        "review_current",
        "review_mistakes",
    ):
        context.user_data.pop(key, None)


def current_lesson_task(context: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
    tasks = context.user_data.get("lesson_tasks")
    index = context.user_data.get("lesson_index")
    if not tasks or index is None or index >= len(tasks):
        return None
    return tasks[index]


def format_lesson_task(index: int, total: int, task: dict) -> str:
    input_hint = (
        "\n\nНапиши ответ одним сообщением."
        if task["type"] == "text"
        else "\n\nВыбери один вариант:"
    )
    return (
        f"Урок EnglishMate — задание {index + 1}/{total}\n\n"
        f"{task['question']}"
        f"{input_hint}"
    )


BTN_FIND_WORD = "🔎 Найти слово"
BTN_MY_WORDS = "📚 Мои слова"
BTN_LESSON = "🎯 Урок"
BTN_PROGRESS = "📈 Прогресс"
BTN_TEST = "🧪 Тест уровня"
BTN_HELP = "❓ Помощь"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_FIND_WORD, BTN_MY_WORDS],
            [BTN_LESSON, BTN_PROGRESS],
            [BTN_TEST, BTN_HELP],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def placement_test_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Определить мой уровень", callback_data="start_test")]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_dictionary_word", None)
    clear_review_state(context)

    text = (
        "Привет! Я EnglishMate — помощник для изучения английского языка.\n\n"
        "Основные действия теперь доступны кнопками внизу — slash-команды запоминать не нужно. "
        "Если ты здесь впервые, сначала пройди placement test."
    )
    await safe_reply(
        update.message,
        text,
        reply_markup=main_menu_keyboard(),
    )

    await safe_reply(
        update.message,
        "Нажми кнопку ниже, чтобы определить уровень английского.",
        reply_markup=placement_test_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_review_state(context)
    text = (
        "Что умеет EnglishMate:\n\n"
        f"{BTN_FIND_WORD} — перевести слово с английского или русского\n"
        f"{BTN_MY_WORDS} — открыть сохранённые слова\n"
        f"{BTN_LESSON} — начать персональный урок\n"
        f"{BTN_PROGRESS} — посмотреть прогресс\n"
        f"{BTN_TEST} — пройти placement test заново\n\n"
        "Можно пользоваться кнопками внизу. Slash-команды тоже работают: "
        "/lesson, /word, /mywords, /progress, /help."
    )
    await safe_reply(
        update.message,
        text,
        reply_markup=main_menu_keyboard(),
    )


MERRIAM_WEBSTER_API_BASE = (
    "https://www.dictionaryapi.com/api/v3/references/learners/json"
)
WIKTIONARY_API_BASE = "https://en.wiktionary.org/w/api.php"
RU_WIKTIONARY_API_BASE = "https://ru.wiktionary.org/w/api.php"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


def _extract_json_object(raw: str) -> dict:
    """Parse a JSON object even if a model wrapped it in a code fence."""
    value = (raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)

    try:
        data = json.loads(value)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(value[start:end + 1])
        if isinstance(data, dict):
            return data

    raise ValueError("Groq did not return a JSON object")


async def groq_json(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_prompt: str,
    max_completion_tokens: int = 500,
    *,
    temperature: float = 0.1,
    schema_name: str = "englishmate_response",
    schema: Optional[dict] = None,
) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing")

    models = [GROQ_MODEL]
    if GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL not in models:
        models.append(GROQ_FALLBACK_MODEL)

    last_error: Optional[Exception] = None

    for model in models:
        # One quick retry handles transient 429/5xx/network failures. If the
        # primary model still fails, the request is retried on the fallback
        # model so one unlucky API response does not break the dictionary.
        for attempt in range(2):
            request_json = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_completion_tokens": max_completion_tokens,
                "stream": False,
                "reasoning_effort": "low",
            }

            if schema:
                request_json["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                }
            else:
                request_json["response_format"] = {"type": "json_object"}

            try:
                response = await client.post(
                    GROQ_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=request_json,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning(
                    "Groq network error model=%s attempt=%s: %s",
                    model, attempt + 1, exc,
                )
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                break

            status = response.status_code

            if status in {401, 403}:
                response.raise_for_status()

            if status == 429:
                last_error = httpx.HTTPStatusError(
                    "Groq rate limit", request=response.request, response=response
                )
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 1.5
                except ValueError:
                    delay = 1.5
                delay = max(0.5, min(delay, 4.0))
                logger.warning(
                    "Groq rate limit model=%s attempt=%s; retry in %.1fs",
                    model, attempt + 1, delay,
                )
                if attempt == 0:
                    await asyncio.sleep(delay)
                    continue
                break

            if status >= 500:
                last_error = httpx.HTTPStatusError(
                    f"Groq server error {status}",
                    request=response.request,
                    response=response,
                )
                logger.warning(
                    "Groq server error model=%s status=%s attempt=%s",
                    model, status, attempt + 1,
                )
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                break

            if status >= 400:
                logger.warning(
                    "Groq request rejected model=%s status=%s body=%s",
                    model, status, response.text[:500],
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                break

            try:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Groq returned an empty response")
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    data = _extract_json_object(content)
                if not isinstance(data, dict):
                    raise ValueError("Groq did not return a JSON object")
                return data
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                logger.warning(
                    "Groq response parse error model=%s attempt=%s: %s",
                    model, attempt + 1, exc,
                )
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                break

    if last_error:
        raise last_error
    raise RuntimeError("Groq request failed")


def _clean_english_candidate(value: object) -> str:
    candidate = str(value or "").strip()
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,;:.•-")
    if not candidate or len(candidate) > 70:
        return ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z' -]*", candidate):
        return ""
    return candidate


def _clean_russian_translation(value: object) -> str:
    translation = str(value or "").strip()
    translation = re.sub(r"\s+", " ", translation).strip(" ,;:.•-")
    if not translation or len(translation) > 80:
        return ""
    if not re.search(r"[а-яА-ЯёЁ]", translation):
        return ""
    return translation


async def merriam_webster_candidate_exists(
    client: httpx.AsyncClient,
    candidate: str,
) -> bool:
    """Validate simple one-word Groq suggestions against Merriam-Webster."""
    if not MERRIAM_WEBSTER_API_KEY:
        return True

    # Multi-word phrases are not always indexed as headwords. They are kept if
    # Groq proposes them, while normal one-word candidates are dictionary-checked.
    if " " in candidate:
        return True

    url = f"{MERRIAM_WEBSTER_API_BASE}/{quote(candidate.lower(), safe='')}"
    try:
        response = await client.get(url, params={"key": MERRIAM_WEBSTER_API_KEY})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return True  # Do not break translation if validation service is flaky.

    if not isinstance(payload, list):
        return False

    target = candidate.lower()
    for item in payload:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") or {}
        meta_id = str(meta.get("id", "")).split(":", 1)[0].lower()
        stems = [str(stem).lower() for stem in (meta.get("stems") or [])]
        headword = str((item.get("hwi") or {}).get("hw", "")).replace("*", "").lower()
        if target in {meta_id, headword} or target in stems:
            return True
    return False


def _lesson_question_key(question: str) -> str:
    value = normalize_text(question or "")
    value = re.sub(r"\s+", " ", value)
    return value[:240]


def _lesson_text_question_is_self_contained(question: str) -> bool:
    """Reject generated text tasks that contain only an instruction and no material to answer."""
    q = " ".join((question or "").split())
    if not q:
        return False

    lower = q.lower()
    incomplete_stems = (
        "rewrite the following phrase",
        "rewrite the following sentence",
        "translate the following phrase",
        "translate the following sentence",
        "translate naturally into english",
        "complete the following sentence",
        "respond to the following message",
        "reply to the following message",
        "make the following phrase more formal",
        "paraphrase the following sentence",
    )

    if lower.endswith(":") and any(stem in lower for stem in incomplete_stems):
        return False

    if any(stem in lower for stem in incomplete_stems):
        has_quote = any(ch in q for ch in ('"', '«', '»', "'"))
        has_blank = "___" in q or "____" in q
        colon_tail = q.split(":", 1)[1].strip() if ":" in q else ""
        if not (has_quote or has_blank or len(colon_tail.split()) >= 2):
            return False

    return True


def build_modern_fallback_lesson(level: str, goal: str) -> List[dict]:
    """Short fallback lesson used only when Groq is temporarily unavailable."""
    by_level = {
        "A1": [
            {"type":"mcq","question":"Выбери правильный вариант: I ___ coffee every morning.","options":["drink","drinks","am drink","drinking"],"correct":0,"answer_display":"drink","explanation":"После I в Present Simple используем обычную форму глагола."},
            {"type":"mcq","question":"Что лучше подходит? This is ___ sister.","options":["my","me","I","mine is"],"correct":0,"answer_display":"my","explanation":"Перед существительным нужна притяжательная форма my."},
            {"type":"mcq","question":"Выбери естественный ответ на “How are you?”","options":["I'm good, thanks.","I have good.","I am a good.","Good I am."],"correct":0,"answer_display":"I'm good, thanks.","explanation":"Это простой естественный ответ на How are you?"},
            {"type":"mcq","question":"Что значит “See you later”?","options":["Увидимся позже","Доброе утро","Мне жаль","Заходи внутрь"],"correct":0,"answer_display":"Увидимся позже","explanation":"See you later — обычное неформальное прощание."},
            {"type":"text","question":"Переведи естественно: «Я дома.»","answers":["i am home","i'm home","i am at home","i'm at home"],"answer_display":"I'm home.","explanation":"I'm home — короткий и естественный вариант."},
        ],
        "A2": [
            {"type":"mcq","question":"Выбери правильный вариант: I ___ this film yesterday.","options":["saw","see","have seen","am seeing"],"correct":0,"answer_display":"saw","explanation":"Yesterday указывает на Past Simple."},
            {"type":"mcq","question":"Что звучит естественно? I’m ___ to buy a new phone.","options":["going","go","went","gone"],"correct":0,"answer_display":"going","explanation":"Be going to используем для планов."},
            {"type":"mcq","question":"Выбери подходящее слово: There aren’t ___ chairs here.","options":["enough","much","a little","any much"],"correct":0,"answer_display":"enough","explanation":"Enough означает «достаточно»."},
            {"type":"mcq","question":"Что лучше сказать, если хочешь перенести встречу?","options":["Can we move it to Friday?","Can we push it yesterday?","We move Friday?","Make it Fridaying?"],"correct":0,"answer_display":"Can we move it to Friday?","explanation":"Move it to Friday — естественный способ предложить другую дату."},
            {"type":"text","question":"Переведи естественно: «Я ещё не готов.»","answers":["i'm not ready yet","i am not ready yet"],"answer_display":"I'm not ready yet.","explanation":"Yet естественно ставится в конце отрицательного предложения."},
        ],
        "B1": [
            {"type":"mcq","question":"Выбери естественный вариант: I’ll ___ you know when I arrive.","options":["let","make","say","tell to"],"correct":0,"answer_display":"let","explanation":"Let you know — устойчивое выражение «дать знать»."},
            {"type":"mcq","question":"Выбери правильный вариант: If I had more time, I ___ more often.","options":["would travel","will travel","travelled","have travelled"],"correct":0,"answer_display":"would travel","explanation":"Во втором условном используем would + глагол."},
            {"type":"mcq","question":"Что значит “I’m looking forward to it”?","options":["Я этого жду с нетерпением","Я смотрю вперёд","Я отказываюсь","Я уже закончил"],"correct":0,"answer_display":"Я этого жду с нетерпением","explanation":"Look forward to означает ждать чего-то с приятным ожиданием."},
            {"type":"mcq","question":"Как естественно попросить уточнить мысль?","options":["Could you clarify that?","Clarify me this.","Say it more correct.","Can you explain me it?"],"correct":0,"answer_display":"Could you clarify that?","explanation":"Could you clarify that? звучит естественно и вежливо."},
            {"type":"text","question":"Переведи естественно: «Я сообщу тебе завтра.»","answers":["i'll let you know tomorrow","i will let you know tomorrow"],"answer_display":"I'll let you know tomorrow.","explanation":"Let you know — естественный вариант «сообщить/дать знать»."},
        ],
        "B2": [
            {"type":"mcq","question":"Что точнее по смыслу? Her explanation was plausible, but not entirely ___.","options":["convincing","convenient","considerate","conventional"],"correct":0,"answer_display":"convincing","explanation":"Convincing — «убедительный»; остальные слова близки по форме, но не по смыслу."},
            {"type":"mcq","question":"Выбери вариант: If it hadn’t been for your help, we ___ the deadline.","options":["would have missed","would miss","had missed","might miss"],"correct":0,"answer_display":"would have missed","explanation":"Это условие о прошлом: would have + V3."},
            {"type":"mcq","question":"Какое слово лучше? The new evidence ___ doubt on his original account.","options":["casts","throws","puts","makes"],"correct":0,"answer_display":"casts","explanation":"Cast doubt on — устойчивая B2-коллокация «ставить под сомнение»."},
            {"type":"mcq","question":"На встрече цифры не совпадают с прогнозом. Что естественнее?","options":["The figures don’t quite align with the forecast.","The figures don’t quite obey the forecast.","The figures don’t quite follow to the forecast.","The figures don’t quite fit into the forecast."],"correct":0,"answer_display":"The figures don’t quite align with the forecast.","explanation":"Align with естественно описывает соответствие данных прогнозу."},
            {"type":"text","question":"Переведи естественно: «Вряд ли мы успеем закончить это сегодня.»","answers":["we're unlikely to finish this today","we are unlikely to finish this today","i doubt we'll manage to finish this today","i doubt we will manage to finish this today"],"answer_display":"We’re unlikely to finish this today.","explanation":"Be unlikely to — естественный B2-способ выразить «вряд ли»."},
        ],
    }
    tasks = [dict(task) for task in by_level.get(level, by_level["B1"])]
    mcq_tasks = tasks[:4]
    random.shuffle(mcq_tasks)
    return mcq_tasks + [tasks[4]]


async def generate_lesson_with_groq(
    level: str,
    goal: str,
    recent_questions: Optional[List[str]] = None,
    saved_words: Optional[List[dict]] = None,
) -> Optional[List[dict]]:
    """Generate a fresh, short and varied lesson tailored to level and goal.

    The lesson is intentionally closer to a micro-session than a school test:
    four quick choice tasks + one very short RU→EN task. Most of the lesson is
    useful General English; the selected goal influences only one task.
    """
    if not GROQ_API_KEY:
        return None

    schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["mcq", "text"]},
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "correct": {"type": "integer"},
                        "answers": {"type": "array", "items": {"type": "string"}},
                        "answer_display": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": [
                        "type",
                        "question",
                        "options",
                        "correct",
                        "answers",
                        "answer_display",
                        "explanation",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tasks"],
        "additionalProperties": False,
    }

    static_template = build_lesson(level, goal)
    blocked = [task.get("question", "") for task in static_template]
    blocked.extend(recent_questions or [])
    blocked = [q for q in blocked if q][-30:]

    if level == "A1":
        level_rules = (
            "A1: true beginner. Use only very common everyday vocabulary and very short sentences. "
            "Grammar: be/have/can, present simple, basic present continuous, simple imperatives, there is/are, "
            "basic questions, this/that, some/any, simple prepositions, numbers/time/daily routines. "
            "Avoid conditionals, passive voice, reported speech, present perfect, complex phrasal verbs and abstract vocabulary."
        )
        lesson_blueprint = (
            "1) MCQ: very common everyday vocabulary in a short context.\n"
            "2) MCQ: one basic grammar point (be/have/can/present simple/present continuous/there is-are).\n"
            "3) MCQ: a common everyday phrase or preposition.\n"
            "4) MCQ: one very short goal-related situation with simple language.\n"
            "5) TEXT: translate one very short Russian sentence, usually 3-7 English words."
        )
    elif level == "A2":
        level_rules = (
            "A2: elementary/pre-intermediate. Use high-frequency vocabulary and normal everyday situations. "
            "Grammar: present/past/future basics, comparatives/superlatives, common modals, present perfect in simple uses, "
            "first conditional, countable/uncountable nouns, common prepositions and very common phrasal verbs. "
            "Avoid second/third/mixed conditionals, inversion, participle clauses, advanced modal perfects and abstract B2 vocabulary."
        )
        lesson_blueprint = (
            "1) MCQ: common vocabulary/collocation or a very common phrasal verb in context.\n"
            "2) MCQ: A2 grammar in one natural sentence.\n"
            "3) MCQ: choose the most natural everyday phrase among plausible options.\n"
            "4) MCQ: one short goal-related practical situation.\n"
            "5) TEXT: translate one short Russian sentence, usually under 9 English words."
        )
    elif level == "B1":
        level_rules = (
            "B1: solid intermediate. Use useful everyday and work/travel vocabulary, common phrasal verbs and collocations. "
            "Grammar may include present perfect vs past simple, first/second conditional, basic passive, relative clauses, "
            "reported speech, gerund/infinitive patterns and modal verbs. "
            "Avoid third/mixed conditionals, inversion, C1-style discourse structures and obscure vocabulary."
        )
        lesson_blueprint = (
            "1) MCQ: intermediate vocabulary, phrasal verb or collocation in context.\n"
            "2) MCQ: B1 grammar in one natural sentence.\n"
            "3) MCQ: meaning/collocation choice with four plausible options.\n"
            "4) MCQ: one short goal-related situation focused on natural language.\n"
            "5) TEXT: translate one short Russian sentence, usually under 12 English words."
        )
    else:
        level_rules = (
            "B2: upper-intermediate. Make tasks genuinely challenging but short. "
            "Use nuanced vocabulary, collocations, phrasal verbs, register, tense/aspect, modals, passive/reported speech, "
            "second/third conditionals and natural discourse markers. "
            "All distractors must be plausible. Avoid C1/C2-style inversion, archaic structures, specialist vocabulary, "
            "and trivial A1/A2 grammar drills."
        )
        lesson_blueprint = (
            "1) MCQ: vocabulary nuance, strong collocation, idiomatic phrase or phrasal verb.\n"
            "2) MCQ: genuinely B2 grammar in one natural sentence.\n"
            "3) MCQ: subtle meaning/collocation/register choice with four plausible options.\n"
            "4) MCQ: one short goal-related micro-situation without long writing.\n"
            "5) TEXT: translate one short Russian sentence requiring natural B2 wording, usually under 15 English words."
        )


    system_prompt = (
        "You design a high-quality 5-minute English micro-lesson for a Russian-speaking learner. "
        "The learner dislikes long, school-like and corporate-test tasks. Difficulty must come from language depth, "
        "not from task length. Create exactly 5 NEW tasks. Follow this level-specific blueprint:\n"
        + lesson_blueprint +
        "\n\nFor task 4, if goal is Work, keep it practical and language-focused (clarifying, updating, scheduling, "
        "simple negotiation) — NO email-writing, formal-letter templates, reports, deadline-reminder templates, or office jargon.\n"
        "CONTENT BALANCE: about 80% useful General English and only 20% goal-specific English. "
        "Do not make the whole lesson about the goal. "
        + level_rules +
        "\n\n"
        "VERY IMPORTANT FOR MCQ QUALITY: never create options where only one is grammatical and the other three are nonsense. "
        "Never make punctuation, capitalization, a missing infinitive marker, or an obviously malformed phrase the main clue. "
        "Do not create four versions of almost the same sentence with one trivial typo. "
        "Prefer close competitors that test actual knowledge.\n\n"
        "STYLE: instructions should be short and preferably in Russian. The English being tested stays in English. "
        "Never mention CEFR labels (A1/A2/B1/B2/C1/C2), 'level', or phrases such as 'B2-level structure' inside a visible task. "
        "The task itself should simply test English naturally. "
        "For each MCQ use exactly 4 concise plausible options and one unambiguous best answer. "
        "For MCQ, answers must be []. For the text task, options must be [], correct must be 0, and provide "
        "2-5 natural acceptable answers. Explanations must be in Russian, friendly, and ONE short sentence. "
        "Do not penalize capitalization or punctuation.\n\n"
        "Do NOT turn saved vocabulary into easy fill-in-the-blank questions. Vocabulary review is handled elsewhere in the bot. "
        "FRESHNESS: do not repeat or lightly paraphrase any blocked_recent_questions. "
        "Every visible question must be complete and self-contained. Keep each question under 180 characters, "
        "each option under 80 characters, answer_display under 120 characters, and explanation under 180 characters."
    )
    payload = {
        "level": level,
        "goal": goal,
        "blocked_recent_questions": blocked,
    }

    async def _request(extra_instruction: Optional[str] = None) -> Optional[List[dict]]:
        request_payload = dict(payload)
        if extra_instruction:
            request_payload["important_retry_instruction"] = extra_instruction
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                data = await groq_json(
                    client,
                    system_prompt,
                    json.dumps(request_payload, ensure_ascii=False),
                    1800,
                    temperature=0.82,
                    schema_name="english_micro_lesson",
                    schema=schema,
                )
        except Exception as exc:
            logger.warning("Could not generate a fresh micro-lesson with Groq: %s", exc)
            return None
        tasks = data.get("tasks")
        return tasks if isinstance(tasks, list) else None

    raw_tasks = await _request()
    if not raw_tasks or len(raw_tasks) != 5:
        logger.warning("Groq lesson had invalid task count: %r", raw_tasks)
        return None

    blocked_keys = {_lesson_question_key(q) for q in blocked}

    def _validate_and_normalize(items: List[dict]) -> Optional[List[dict]]:
        tasks: List[dict] = []
        new_keys = set()
        mcq_count = 0
        text_count = 0

        for position, raw in enumerate(items):
            if not isinstance(raw, dict):
                return None
            task_type = raw.get("type")
            question = " ".join(str(raw.get("question") or "").split()).strip()
            explanation = " ".join(str(raw.get("explanation") or "").split()).strip()
            answer_display = " ".join(str(raw.get("answer_display") or "").split()).strip()
            qkey = _lesson_question_key(question)

            if len(question) > 180 or len(explanation) > 180 or len(answer_display) > 120:
                return None
            if not question or not explanation or not qkey or qkey in blocked_keys or qkey in new_keys:
                return None
            new_keys.add(qkey)

            forbidden = (
                "write an email", "write a paragraph", "write an essay", "write a report",
                "write a cover letter", "compose an email", "draft an email", "write a dialogue",
                "reply to an email", "deadline reminder email", "formal email",
                "напиши письмо", "напишите письмо", "напиши эссе", "напишите эссе",
                "напиши абзац", "напишите абзац", "напиши отчет", "напишите отчет",
            )
            if any(phrase in question.lower() for phrase in forbidden):
                return None

            # Never show meta wording about CEFR levels in the actual exercise.
            visible_meta = (question + " " + explanation + " " + answer_display).lower()
            if re.search(r"\b(?:a1|a2|b1|b2|c1|c2)[ -]?level\b|\bcefr\b", visible_meta):
                return None

            # Hard guardrails for every CEFR level.
            option_text = " ".join(str(v) for v in (raw.get("options") or [])).lower()
            level_text = (visible_meta + " " + option_text).lower()

            a1_forbidden = (
                "present perfect", "have been", "has been", "would ", "could have", "might have",
                "passive voice", "reported speech", "relative clause", "first conditional",
                "second conditional", "third conditional", "mixed conditional", "inversion",
                "subjunctive", "participle clause", "phrasal verb",
            )
            a2_forbidden = (
                "would have", "could have", "might have", "had i ", "had he ", "had she ",
                "were it not", "should you ", "no sooner", "hardly had", "scarcely had",
                "second conditional", "third conditional", "mixed conditional", "inversion",
                "subjunctive", "participle clause", "modal perfect",
            )
            b1_forbidden = (
                "would have", "could have", "might have", "had i ", "had he ", "had she ",
                "were it not", "no sooner", "hardly had", "scarcely had",
                "third conditional", "mixed conditional", "inversion", "subjunctive",
                "participle clause",
            )
            b2_too_advanced = (
                "no sooner", "hardly had", "scarcely had", "little did", "under no circumstances",
                "were it not for", "had it not been", "should you require", "negative inversion",
                "cleft sentence", "subjunctive mood",
            )
            b2_too_basic_option_sets = (
                {"am", "is", "are", "be"},
                {"do", "does", "did", "done"},
                {"a", "an", "the", "no article"},
                {"was", "were", "is", "are"},
                {"have", "has", "had", "having"},
            )

            if level == "A1" and any(p in level_text for p in a1_forbidden):
                return None
            if level == "A2" and any(p in level_text for p in a2_forbidden):
                return None
            if level == "B1" and any(p in level_text for p in b1_forbidden):
                return None
            if level == "B2":
                if any(p in level_text for p in b2_too_advanced):
                    return None
                raw_options = {str(v).strip().lower() for v in (raw.get("options") or [])}
                if raw_options in b2_too_basic_option_sets:
                    return None
                trivial_stems = (
                    "choose is or are", "choose do or does", "choose a or an",
                    "past tense of", "plural of", "opposite of big", "days of the week",
                )
                if any(p in question.lower() for p in trivial_stems):
                    return None

            # New lesson format is fixed: first 4 are MCQ, last one is a short RU→EN task.
            if position < 4 and task_type != "mcq":
                return None
            if position == 4 and task_type != "text":
                return None

            if task_type == "mcq":
                options = [" ".join(str(v).split()).strip() for v in (raw.get("options") or [])]
                options = [v for v in options if v]
                correct = raw.get("correct")
                if len(options) != 4 or not isinstance(correct, int) or not 0 <= correct < 4:
                    return None
                if len(set(v.lower() for v in options)) != 4 or any(len(v) > 60 for v in options):
                    return None
                if not answer_display:
                    answer_display = options[correct]
                tasks.append({
                    "type": "mcq",
                    "question": question,
                    "options": options,
                    "correct": correct,
                    "explanation": explanation,
                    "answer_display": answer_display,
                })
                mcq_count += 1
            elif task_type == "text":
                # The only writing task is a very short RU→EN translation.
                if not re.search(r"[А-Яа-яЁё]", question):
                    return None
                answers = [" ".join(str(v).split()).strip() for v in (raw.get("answers") or [])]
                answers = [v for v in answers if v]
                if not answers or not answer_display:
                    return None
                if len(answer_display.split()) > 20:
                    return None
                tasks.append({
                    "type": "text",
                    "question": question,
                    "answers": answers[:5],
                    "answer_display": answer_display,
                    "explanation": explanation,
                })
                text_count += 1
            else:
                return None

        if mcq_count != 4 or text_count != 1:
            return None
        return tasks

    normalized = _validate_and_normalize(raw_tasks)
    if normalized:
        return normalized

    logger.warning("Groq produced a lesson outside the new compact lesson format; retrying once")
    raw_tasks = await _request(
        "Regenerate from scratch. Exactly tasks 1-4 must be MCQ and task 5 must be ONE short Russian-to-English "
        "translation. Keep tasks short but NOT easy. For B2, all four MCQ options must be grammatically plausible and "
        "the distinction must depend on B2 vocabulary, collocation, nuance, register, phrasal verbs or advanced grammar. "
        "Reject elementary missing-word tricks and visibly broken distractors. Four tasks are General English; only task 4 "
        "may be directly goal-specific. No emails, long writing, corporate templates, or school-like meta questions."
    )
    if not raw_tasks or len(raw_tasks) != 5:
        return None
    return _validate_and_normalize(raw_tasks)


async def groq_russian_to_english(
    client: httpx.AsyncClient,
    russian_query: str,
) -> List[dict]:
    system_prompt = (
        "You are a careful bilingual Russian-English learner's dictionary. "
        "Translate a Russian word or short phrase into natural, common English. "
        "Return ONLY valid JSON in exactly this shape: "
        '{"items":[{"english":"...","note":"short clarification in Russian"}]}. '
        "Give 1 to 3 best equivalents. If the Russian input is ambiguous, choose "
        "different common meanings and clarify each briefly in Russian. Prefer direct, "
        "everyday dictionary equivalents. Do not invent words, do not output transliteration, "
        "archaic/technical variants unless they are the main meaning, and do not output "
        "quantity derivatives such as glassful/cupful when the Russian word names the object. "
        "For adjectives and phrases, use natural English usage rather than a literal calque. "
        "Example: цирковой -> circus (attributive adjective, e.g. circus performer) or circus-related; "
        "do not fail just because English often uses a noun attributively where Russian uses an adjective."
    )
    translation_schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "english": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["english", "note"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    data = await groq_json(
        client,
        system_prompt,
        russian_query,
        420,
        schema_name="russian_to_english",
        schema=translation_schema,
    )
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Groq translation items missing")

    result: List[dict] = []
    seen = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        english = _clean_english_candidate(raw.get("english"))
        if not english or english.lower() in seen:
            continue
        note = str(raw.get("note") or "").strip()
        note = re.sub(r"\s+", " ", note)[:120]
        result.append({"english": english, "note": note})
        seen.add(english.lower())
        if len(result) >= 3:
            break

    if not result:
        raise LookupError("No usable Groq translations")

    # Dictionary-check normal one-word candidates. If validation removes all of
    # them, keep the model output rather than returning an empty result.
    validated: List[dict] = []
    for item in result:
        if await merriam_webster_candidate_exists(client, item["english"]):
            validated.append(item)
    return validated or result


async def groq_translate_mw_senses(
    client: httpx.AsyncClient,
    word: str,
    senses: List[dict],
) -> None:
    if not senses:
        return

    compact = []
    for index, sense in enumerate(senses[:2]):
        compact.append({
            "index": index,
            "part_of_speech": sense.get("part_of_speech") or "",
            "definition": sense.get("definition") or "",
            "example": sense.get("example") or "",
        })

    system_prompt = (
        "You are a precise English-Russian learner's dictionary. "
        "Translate EACH exact dictionary sense into natural Russian, using the supplied "
        "part of speech and definition. Do not mix meanings of the headword. Return ONLY "
        "valid JSON in exactly this shape: "
        '{"senses":[{"index":0,"translations":["...","..."]}]}. '
        "For each sense give 1 to 3 short, common Russian equivalents. Preserve the part "
        "of speech. Avoid rare, overly literal, technical, or contextually wrong meanings."
    )
    senses_schema = {
        "type": "object",
        "properties": {
            "senses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "translations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["index", "translations"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["senses"],
        "additionalProperties": False,
    }
    data = await groq_json(
        client,
        system_prompt,
        json.dumps({"word": word, "senses": compact}, ensure_ascii=False),
        520,
        schema_name="english_sense_translations",
        schema=senses_schema,
    )

    raw_senses = data.get("senses")
    if not isinstance(raw_senses, list):
        raise ValueError("Groq sense translations missing")

    for raw in raw_senses:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(senses):
            continue
        translations = raw.get("translations")
        if not isinstance(translations, list):
            continue

        cleaned: List[str] = []
        seen = set()
        for value in translations:
            item = _clean_russian_translation(value)
            if not item or item.lower() in seen:
                continue
            cleaned.append(item)
            seen.add(item.lower())
            if len(cleaned) >= 3:
                break
        if cleaned:
            senses[index]["translations"] = cleaned


def format_groq_reverse_translation(query: str, items: List[dict]) -> str:
    lines = [f"Слово: {query}", "", "Варианты на английском:"]
    for item in items[:3]:
        line = f"• {item['english']}"
        if item.get("note"):
            line += f" — {item['note']}"
        lines.append(line)
    lines.extend([
        "",
        "Чтобы посмотреть определение, пример и точный перевод конкретного значения, "
        "нажми «🔎 Найти слово» и введи английский вариант.",
    ])
    return "\n".join(lines)

POS_NAMES = {
    "noun": "noun",
    "verb": "verb",
    "adjective": "adjective",
    "adverb": "adverb",
    "pronoun": "pronoun",
    "preposition": "preposition",
    "conjunction": "conjunction",
    "interjection": "interjection",
}


def clean_mw_text(value: object) -> str:
    """Convert Merriam-Webster inline markup into plain readable text."""
    text = str(value or "")
    if not text:
        return ""

    text = text.replace("{bc}", "")

    # Cross-reference-like tags keep the human-readable word in the first argument.
    text = re.sub(
        r"\{(?:a_link|d_link|i_link|et_link|mat|sx|dxt)\|([^|{}]+)(?:\|[^{}]*)?\}",
        r"\1",
        text,
    )

    # Formatting tags such as {it}...{/it}, {b}...{/b}, etc.
    text = re.sub(r"\{/?(?:it|b|sc|inf|sup|phrase|qword)\}", "", text)

    # Remove any remaining Merriam-Webster control tags.
    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ;,:-")
    return text


def _iter_nested(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_nested(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nested(child)


def extract_first_example(entry: dict) -> Optional[str]:
    for node in _iter_nested(entry.get("def", [])):
        if (
            isinstance(node, list)
            and len(node) >= 2
            and node[0] == "vis"
            and isinstance(node[1], list)
        ):
            for item in node[1]:
                if isinstance(item, dict) and item.get("t"):
                    example = clean_mw_text(item["t"])
                    if example:
                        return example
    return None


def _append_unique(words: List[str], value: object, requested_word: str) -> None:
    word = clean_mw_text(value)
    if not word:
        return
    if word.lower() == requested_word.lower():
        return
    if word.lower() in {item.lower() for item in words}:
        return
    words.append(word)


def extract_mw_synonyms(entry: dict, requested_word: str) -> List[str]:
    """Read explicit synonym lists if the Learner's response contains them."""
    synonyms: List[str] = []

    meta_syns = entry.get("meta", {}).get("syns", [])
    for node in _iter_nested(meta_syns):
        if isinstance(node, str):
            _append_unique(synonyms, node, requested_word)
        if len(synonyms) >= 3:
            return synonyms[:3]

    for node in _iter_nested(entry):
        if isinstance(node, dict) and "syn_list" in node:
            for syn_node in _iter_nested(node.get("syn_list")):
                if isinstance(syn_node, dict) and syn_node.get("wd"):
                    _append_unique(synonyms, syn_node["wd"], requested_word)
                elif isinstance(syn_node, str):
                    _append_unique(synonyms, syn_node, requested_word)
                if len(synonyms) >= 3:
                    return synonyms[:3]

    return synonyms[:3]


def parse_merriam_webster(payload: object, requested_word: str) -> List[dict]:
    if not isinstance(payload, list):
        raise ValueError("Unexpected Merriam-Webster response")

    # A list of strings means spelling suggestions, not dictionary entries.
    dictionary_entries = [item for item in payload if isinstance(item, dict)]
    if not dictionary_entries:
        raise LookupError("Word not found")

    requested_lower = requested_word.lower()
    matched_entries = []

    for item in dictionary_entries:
        meta = item.get("meta") or {}
        meta_id = str(meta.get("id", "")).split(":", 1)[0].lower()
        stems = [str(stem).lower() for stem in (meta.get("stems") or [])]
        headword = str((item.get("hwi") or {}).get("hw", "")).replace("*", "").lower()

        if requested_lower in {meta_id, headword} or requested_lower in stems:
            matched_entries.append(item)

    if not matched_entries:
        matched_entries = dictionary_entries

    senses: List[dict] = []
    used_pos = set()

    for item in matched_entries:
        part_of_speech = str(item.get("fl") or "").strip().lower() or "—"

        # Prefer at most one clear block for each part of speech.
        pos_key = part_of_speech.lower()
        if pos_key in used_pos:
            continue

        shortdefs = item.get("shortdef") or []
        definition = ""
        if isinstance(shortdefs, list):
            for raw_definition in shortdefs:
                definition = clean_mw_text(raw_definition)
                if definition:
                    break

        if not definition:
            app_shortdef = (item.get("meta") or {}).get("app-shortdef") or {}
            app_defs = app_shortdef.get("def") or [] if isinstance(app_shortdef, dict) else []
            if isinstance(app_defs, list):
                for raw_definition in app_defs:
                    definition = clean_mw_text(raw_definition)
                    if definition:
                        break

        if not definition:
            continue

        senses.append(
            {
                "part_of_speech": part_of_speech,
                "definition": definition,
                "example": extract_first_example(item),
                "synonyms": extract_mw_synonyms(item, requested_word),
                "translations": [],
            }
        )
        used_pos.add(pos_key)

        if len(senses) >= 2:
            break

    if not senses:
        raise LookupError("Word has no usable definitions")

    return senses


def remove_stress_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    without_marks = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return unicodedata.normalize("NFC", without_marks)


def clean_wiktionary_term(value: object) -> str:
    text = str(value or "").strip()
    text = text.replace("[[", "").replace("]]", "")
    text = re.sub(r"<!--.*?-->", "", text)
    text = remove_stress_marks(text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:")
    return text


def _normalise_pos_heading(value: str) -> Optional[str]:
    heading = value.strip().lower()
    aliases = {
        "noun": "noun",
        "proper noun": "noun",
        "verb": "verb",
        "adjective": "adjective",
        "adverb": "adverb",
        "pronoun": "pronoun",
        "preposition": "preposition",
        "conjunction": "conjunction",
        "interjection": "interjection",
    }
    return aliases.get(heading)


def parse_wiktionary_translations(wikitext: str) -> Dict[str, List[str]]:
    """Extract Russian translations grouped by English part of speech.

    Wiktionary pages do not always use the same heading depth. For example,
    a simple page can have ``===Noun===`` / ``====Translations====``, while a
    page with several etymologies can use ``====Verb====`` /
    ``=====Translations=====``. Track heading levels instead of assuming one
    fixed layout so translations are also collected for verbs, adjectives,
    etc.
    """
    result: Dict[str, List[str]] = {}
    current_language: Optional[str] = None
    current_pos: Optional[str] = None
    current_pos_level: Optional[int] = None
    in_translations = False
    translations_level: Optional[int] = None

    translation_pattern = re.compile(
        r"\{\{(?:t\+?|t-check|t\+check|tt\+?)\|ru\|([^|}]+)",
        flags=re.IGNORECASE,
    )
    heading_pattern = re.compile(r"^(={2,6})\s*([^=]+?)\s*\1$")

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()

        heading_match = heading_pattern.fullmatch(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            title_lower = title.lower()

            if level == 2:
                current_language = title_lower
                current_pos = None
                current_pos_level = None
                in_translations = False
                translations_level = None
                continue

            if current_language != "english":
                continue

            pos = _normalise_pos_heading(title)
            if pos:
                current_pos = pos
                current_pos_level = level
                in_translations = False
                translations_level = None
                continue

            if (
                title_lower == "translations"
                and current_pos
                and current_pos_level is not None
                and level > current_pos_level
            ):
                in_translations = True
                translations_level = level
                continue

            # A heading at the same or higher level closes the current POS
            # section. A heading at the same or higher level than Translations
            # closes only that subsection.
            if in_translations and translations_level is not None and level <= translations_level:
                in_translations = False
                translations_level = None
            if current_pos_level is not None and level <= current_pos_level:
                current_pos = None
                current_pos_level = None
            continue

        if current_language != "english" or not current_pos or not in_translations:
            continue

        for match in translation_pattern.finditer(line):
            term = clean_wiktionary_term(match.group(1))
            if not term:
                continue
            bucket = result.setdefault(current_pos, [])
            if term.lower() not in {item.lower() for item in bucket}:
                bucket.append(term)

    return result


def parse_wiktionary_synonyms(wikitext: str) -> Dict[str, List[str]]:
    """Extract explicit synonyms from English Synonyms sections."""
    result: Dict[str, List[str]] = {}
    current_language = None
    current_pos: Optional[str] = None
    in_synonyms = False

    link_pattern = re.compile(r"\{\{(?:l|m)\|en\|([^|}]+)", re.IGNORECASE)
    wikilink_pattern = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
    syn_template_pattern = re.compile(r"\{\{syn\|en\|([^}]+)\}\}", re.IGNORECASE)

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()

        language_match = re.fullmatch(r"==([^=]+)==", line)
        if language_match:
            current_language = language_match.group(1).strip().lower()
            current_pos = None
            in_synonyms = False
            continue

        if current_language != "english":
            continue

        pos_match = re.fullmatch(r"===([^=]+)===", line)
        if pos_match:
            current_pos = _normalise_pos_heading(pos_match.group(1))
            in_synonyms = False
            continue

        subsection_match = re.fullmatch(r"====([^=]+)====", line)
        if subsection_match:
            in_synonyms = subsection_match.group(1).strip().lower() == "synonyms"
            continue

        if not current_pos or not in_synonyms:
            continue

        candidates: List[str] = []

        for match in link_pattern.finditer(line):
            candidates.append(match.group(1))

        for match in syn_template_pattern.finditer(line):
            for part in match.group(1).split("|"):
                if part and "=" not in part:
                    candidates.append(part)

        for match in wikilink_pattern.finditer(line):
            candidates.append(match.group(1))

        bucket = result.setdefault(current_pos, [])
        for candidate in candidates:
            word = clean_wiktionary_term(candidate)
            if not word or " " in word and len(word) > 35:
                continue
            if word.lower() not in {item.lower() for item in bucket}:
                bucket.append(word)

    return result


def parse_wiktionary_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Wiktionary response")
    if payload.get("error"):
        raise LookupError("Wiktionary page not found")

    parse_data = payload.get("parse")
    if not isinstance(parse_data, dict):
        raise ValueError("Wiktionary parse block missing")

    wikitext = parse_data.get("wikitext")
    if isinstance(wikitext, dict):
        wikitext = wikitext.get("*")

    if not isinstance(wikitext, str):
        raise ValueError("Wiktionary wikitext missing")

    return wikitext


async def fetch_wiktionary_wikitext(
    client: httpx.AsyncClient,
    page: str,
    api_base: str = WIKTIONARY_API_BASE,
) -> Optional[str]:
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
        "redirects": "1",
    }

    try:
        response = await client.get(api_base, params=params)
        response.raise_for_status()
        return parse_wiktionary_payload(response.json())
    except LookupError:
        return None


def parse_russian_wiktionary_english_translations(wikitext: str) -> List[str]:
    """Extract English equivalents from Russian Wiktionary translation blocks.

    Russian Wiktionary commonly stores translations in ``перев-блок`` templates
    with fields like ``|en=[[arm]], [[hand]]``. Keep the parser permissive because
    pages use several historical template variants.
    """
    if not wikitext:
        return []

    values: List[str] = []

    # Translation-block fields such as: |en=[[arm]], [[hand]]
    field_pattern = re.compile(
        r"(?i)\|\s*en\s*=\s*([^|\n\r}]*)"
    )
    raw_chunks = [m.group(1) for m in field_pattern.finditer(wikitext)]

    # Some pages use direct translation templates instead of a named field.
    direct_template_pattern = re.compile(
        r"\{\{(?:t\+?|t-check|t\+check|tt\+?|п|перевод)\|en\|([^|}]+)",
        flags=re.IGNORECASE,
    )
    raw_chunks.extend(m.group(1) for m in direct_template_pattern.finditer(wikitext))

    def add_term(raw: str) -> None:
        term = clean_wiktionary_term(raw)
        term = re.sub(r"\([^)]*\)", "", term).strip()
        term = re.sub(r"\s+", " ", term).strip(" ,;:")
        # Remove grammatical/template leftovers that are not translation text.
        term = re.sub(r"\{\{[^{}]*\}\}", "", term).strip(" ,;:")
        if not term or len(term) > 60:
            return
        if not re.search(r"[A-Za-z]", term):
            return
        lowered = term.lower()
        if lowered not in {item.lower() for item in values}:
            values.append(term)

    for chunk in raw_chunks:
        # Prefer explicit Wiktionary links because they isolate terms cleanly.
        linked = re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", chunk)
        if linked:
            for term in linked:
                add_term(term)
            continue

        # Template chunks usually already contain one clean term. Plain fields can
        # contain comma/semicolon-separated alternatives.
        clean_chunk = re.sub(r"\{\{[^{}]*\}\}", "", chunk)
        for part in re.split(r"[,;]", clean_chunk):
            add_term(part)

    return values[:8]


REVERSE_SENSE_SKIP_WORDS = (
    "количество",
    "мера",
    "объём",
    "перен",
    "воен",
    "техн",
    "жарг",
    "устар",
    "спец",
)


def parse_russian_wiktionary_translation_groups(wikitext: str) -> List[dict]:
    """Return English translations grouped by the Russian Wiktionary sense.

    This matters because a single Russian headword can have several meanings.
    For example, ``стакан`` has a primary vessel sense (``glass``) and a
    quantity sense (``glassful``). Flattening all ``|en=`` fields made the bot
    present ``glassful`` as if it were a direct synonym of the vessel.
    """
    if not wikitext:
        return []

    # Most modern Russian Wiktionary pages use {{перев-блок|<sense>|...}}.
    # Splitting on the template boundary is intentionally permissive and works
    # even when individual language fields are on one line or many lines.
    parts = re.split(r"(?i)\{\{\s*перев-блок\s*\|", wikitext)
    groups: List[dict] = []

    for part in parts[1:]:
        # The first template argument is the short description of the sense.
        label_raw = part.split("|", 1)[0].split("\n", 1)[0]
        label = clean_wiktionary_term(label_raw)
        label = re.sub(r"\{\{[^{}]*\}\}", "", label)
        label = re.sub(r"\s+", " ", label).strip(" -:;,.")

        translations = parse_russian_wiktionary_english_translations(part)
        if not translations:
            continue

        # The bot is for everyday language learning. Hide marked derived,
        # technical and quantity senses from the default reverse lookup.
        # The common unmarked meanings remain separate instead of being merged.
        label_lower = label.lower()
        if label and any(word in label_lower for word in REVERSE_SENSE_SKIP_WORDS):
            continue

        groups.append({
            "sense": label or None,
            "translations": translations[:4],
        })
        if len(groups) >= 3:
            break

    if groups:
        return groups

    # Compatibility fallback for older pages without перев-блок templates.
    flat = parse_russian_wiktionary_english_translations(wikitext)
    return [{"sense": None, "translations": flat[:6]}] if flat else []


def format_reverse_translation(query: str, groups: List[dict]) -> str:
    lines = [f"Слово: {query}", ""]

    if len(groups) == 1 and not groups[0].get("sense"):
        lines.append("Варианты на английском:")
        lines.extend(f"• {item}" for item in groups[0].get("translations", [])[:6])
    else:
        lines.append("Переводы по значениям:")
        for index, group in enumerate(groups[:3], start=1):
            if index > 1:
                lines.append("")
            sense = group.get("sense")
            if sense:
                lines.append(f"{index}. {sense}")
            else:
                lines.append(f"{index}. Основное значение")
            lines.extend(f"• {item}" for item in group.get("translations", [])[:4])

    lines.extend(
        [
            "",
            "Чтобы посмотреть подробное значение и пример, введи английский вариант через «🔎 Найти слово».",
        ]
    )
    return "\n".join(lines)


async def lookup_russian_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    requested_word: str,
) -> None:
    requested_word = requested_word.strip().lower()

    if len(requested_word) > 80 or not re.fullmatch(r"[а-яА-ЯёЁ][а-яА-ЯёЁ' -]*", requested_word):
        await safe_reply(
            update.message,
            "Напиши слово или короткое выражение на русском или английском. Например: рука или arm.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is missing")
        await safe_reply(
            update.message,
            "Переводчик пока не настроен: отсутствует GROQ_API_KEY.",
            reply_markup=main_menu_keyboard(),
        )
        return

    try:
        timeout = httpx.Timeout(20.0, connect=10.0)
        headers = {
            "User-Agent": "EnglishMate/1.0 (educational Telegram bot; ITMO University)"
        }
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            items = await groq_russian_to_english(client, requested_word)

        await safe_reply(
            update.message,
            format_groq_reverse_translation(requested_word, items),
            reply_markup=main_menu_keyboard(),
        )

    except LookupError:
        await safe_reply(
            update.message,
            f"Для слова «{requested_word}» не удалось подобрать надёжный английский вариант.",
            reply_markup=main_menu_keyboard(),
        )
    except httpx.TimeoutException:
        await safe_reply(
            update.message,
            "Переводчик сейчас отвечает слишком долго. Попробуй ещё раз через несколько секунд.",
            reply_markup=main_menu_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Groq HTTP error for %s: %s",
            requested_word,
            exc.response.status_code,
        )
        message = "Сервис перевода временно недоступен. Попробуй ещё раз через несколько секунд."
        if exc.response.status_code == 429:
            message = "Слишком много запросов к переводчику подряд. Подожди 10–20 секунд и попробуй ещё раз."
        elif exc.response.status_code in {401, 403}:
            message = "Не удалось авторизоваться в сервисе перевода. Проверь GROQ_API_KEY в .env."
        await safe_reply(update.message, message, reply_markup=main_menu_keyboard())
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.warning("Groq translation error for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Не удалось обработать перевод. Попробуй ещё раз или введи другое слово.",
            reply_markup=main_menu_keyboard(),
        )


async def lookup_and_send_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
) -> None:
    query = query.strip()
    has_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", query))
    has_latin = bool(re.search(r"[A-Za-z]", query))

    if has_cyrillic and not has_latin:
        await lookup_russian_and_send(update, context, query)
        return
    if has_latin and not has_cyrillic:
        await lookup_and_send_word(update, context, query)
        return

    await safe_reply(
        update.message,
        "Напиши одно слово или выражение только на русском или только на английском. Например: рука или arm.",
        reply_markup=main_menu_keyboard(),
    )


def attach_wiktionary_data(
    senses: List[dict],
    translation_wikitext: Optional[str],
    main_wikitext: Optional[str],
) -> None:
    translations_by_pos: Dict[str, List[str]] = {}
    synonyms_by_pos: Dict[str, List[str]] = {}

    if translation_wikitext:
        translations_by_pos = parse_wiktionary_translations(translation_wikitext)

    # Merge translations from the main page as well. Wiktionary often moves
    # only one part of speech to /translations and leaves another (for example
    # a verb) on the main page. Previously this meant that only the noun got a
    # Russian translation.
    if main_wikitext:
        main_translations = parse_wiktionary_translations(main_wikitext)
        for pos, values in main_translations.items():
            bucket = translations_by_pos.setdefault(pos, [])
            existing = {item.lower() for item in bucket}
            for value in values:
                if value.lower() not in existing:
                    bucket.append(value)
                    existing.add(value.lower())

        # Synonyms are optional: show them only when Wiktionary has a clean
        # explicit section for the same part of speech.
        synonyms_by_pos = parse_wiktionary_synonyms(main_wikitext)

    all_translations: List[str] = []
    for values in translations_by_pos.values():
        for value in values:
            if value.lower() not in {item.lower() for item in all_translations}:
                all_translations.append(value)

    for index, sense in enumerate(senses):
        pos = str(sense.get("part_of_speech") or "").lower()
        translations = list(translations_by_pos.get(pos, []))

        # If Wiktionary did not label the primary sense cleanly, use the first
        # translations only for the first Merriam-Webster block.
        if not translations and index == 0:
            translations = all_translations

        sense["translations"] = translations[:3]

        if not sense.get("synonyms"):
            sense["synonyms"] = synonyms_by_pos.get(pos, [])[:3]


def build_dictionary_entry(requested_word: str, senses: List[dict]) -> dict:
    primary = senses[0]
    translations = primary.get("translations") or []

    return {
        "word": requested_word,
        "translation": ", ".join(translations) if translations else None,
        "part_of_speech": primary.get("part_of_speech") or "—",
        "definition": primary.get("definition") or "",
        "example": primary.get("example"),
        "synonyms": primary.get("synonyms") or [],
        "senses": senses,
    }


def _format_sense_block(sense: dict, number: Optional[int] = None) -> List[str]:
    lines: List[str] = []
    pos = sense.get("part_of_speech") or "—"

    if number is None:
        lines.append(f"Часть речи: {pos}")
    else:
        lines.append(f"{number}. Часть речи: {pos}")

    translations = sense.get("translations") or []
    if translations:
        lines.append("")
        lines.append("Переводы:")
        lines.extend(f"• {item}" for item in translations[:3])

    lines.append("")
    lines.append("Значение:")
    lines.append(sense.get("definition") or "—")

    if sense.get("example"):
        lines.append("")
        lines.append("Пример:")
        lines.append(sense["example"])

    synonyms = sense.get("synonyms") or []
    if synonyms:
        lines.append("")
        lines.append("Синонимы:")
        lines.extend(f"• {item}" for item in synonyms[:3])

    return lines


def format_dictionary_entry(entry: dict) -> str:
    senses = entry.get("senses") or []
    lines = [f"Слово: {entry['word']}"]

    if not senses:
        # Defensive fallback for cached entries from an older version.
        if entry.get("translation"):
            lines.append(f"Перевод: {entry['translation']}")
        lines.append(f"Часть речи: {entry.get('part_of_speech') or '—'}")
        lines.append("")
        lines.append("Значение:")
        lines.append(entry.get("definition") or "—")
        return "\n".join(lines)

    lines.append("")

    if len(senses) == 1:
        lines.extend(_format_sense_block(senses[0]))
    else:
        for index, sense in enumerate(senses[:2], start=1):
            if index > 1:
                lines.append("")
            lines.extend(_format_sense_block(sense, number=index))

    return "\n".join(lines)


async def lookup_and_send_word(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    requested_word: str,
) -> None:
    requested_word = requested_word.strip().lower()

    if len(requested_word) > 50 or not re.fullmatch(r"[a-zA-Z][a-zA-Z' -]*", requested_word):
        await safe_reply(
            update.message,
            "Пожалуйста, введи английское слово латиницей.\nНапример: /word opportunity",
        )
        return

    if not MERRIAM_WEBSTER_API_KEY:
        logger.error("MERRIAM_WEBSTER_API_KEY is missing")
        await safe_reply(
            update.message,
            "Словарь пока не настроен: отсутствует API-ключ Merriam-Webster.",
        )
        return

    encoded_word = quote(requested_word, safe="")
    mw_url = f"{MERRIAM_WEBSTER_API_BASE}/{encoded_word}"
    mw_params = {"key": MERRIAM_WEBSTER_API_KEY}

    try:
        timeout = httpx.Timeout(15.0, connect=10.0)
        headers = {
            "User-Agent": "EnglishMate/1.0 (educational Telegram bot; ITMO University)"
        }

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            mw_response = await client.get(mw_url, params=mw_params)
            mw_response.raise_for_status()

            try:
                mw_payload = mw_response.json()
            except ValueError as exc:
                raise ValueError("Invalid JSON from Merriam-Webster") from exc

            try:
                senses = parse_merriam_webster(mw_payload, requested_word)
            except LookupError:
                await safe_reply(
                    update.message,
                    f"Не удалось найти слово «{requested_word}» в словаре.",
                )
                return

            # Groq translates each exact Merriam-Webster sense into Russian.
            # This avoids mixing unrelated meanings of polysemous words.
            translated_with_groq = False
            if GROQ_API_KEY:
                try:
                    await groq_translate_mw_senses(client, requested_word, senses)
                    translated_with_groq = any(sense.get("translations") for sense in senses)
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    logger.warning(
                        "Groq EN->RU translation failed for %s: %s",
                        requested_word,
                        exc,
                    )

            # Wiktionary remains only as a fallback if Groq is unavailable.
            if not translated_with_groq:
                try:
                    translation_wikitext = await fetch_wiktionary_wikitext(
                        client,
                        f"{requested_word}/translations",
                    )
                    main_wikitext = await fetch_wiktionary_wikitext(
                        client,
                        requested_word,
                    )
                    attach_wiktionary_data(
                        senses,
                        translation_wikitext,
                        main_wikitext,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning(
                        "Wiktionary fallback failed for %s: %s",
                        requested_word,
                        exc,
                    )

            entry = build_dictionary_entry(requested_word, senses)

    except httpx.TimeoutException as exc:
        logger.warning("Merriam-Webster timeout for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Словарь сейчас отвечает слишком долго. Попробуй ещё раз через несколько секунд.",
        )
        return
    except httpx.NetworkError as exc:
        logger.warning("Merriam-Webster network error for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Не удалось подключиться к словарю. Проверь интернет и попробуй ещё раз.",
        )
        return
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Merriam-Webster HTTP error for %s: %s",
            requested_word,
            exc.response.status_code,
        )
        await safe_reply(
            update.message,
            "Словарь временно недоступен. Попробуй позже.",
        )
        return
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Dictionary error for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Не удалось обработать ответ словаря. Попробуй другое слово.",
        )
        return

    cache = context.user_data.setdefault("dictionary_cache", {})
    cache[entry["word"].lower()] = entry

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "Сохранить слово",
                callback_data=f"saveword:{entry['word'][:45].lower()}",
            )
        ]]
    )

    await safe_reply(
        update.message,
        format_dictionary_entry(entry),
        reply_markup=keyboard,
    )



async def word_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_review_state(context)
    if not context.args:
        context.user_data["awaiting_dictionary_word"] = True
        await safe_reply(
            update.message,
            "Напиши слово на русском или английском одним сообщением. Например: рука или arm",
            reply_markup=main_menu_keyboard(),
        )
        return

    context.user_data.pop("awaiting_dictionary_word", None)
    requested_word = " ".join(context.args)
    await lookup_and_send_query(update, context, requested_word)


async def save_word_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        word = query.data.split(":", maxsplit=1)[1].strip().lower()
    except (AttributeError, IndexError):
        return

    entry = context.user_data.get("dictionary_cache", {}).get(word)
    if not entry:
        await edit_callback_message(
            query,
            "Данные этого слова уже не находятся в памяти бота. Нажми «🔎 Найти слово» и выполни поиск ещё раз.",
        )
        return

    added = save_word(
        telegram_id=update.effective_user.id,
        word=entry["word"],
        translation=entry.get("translation"),
        part_of_speech=entry.get("part_of_speech"),
        definition=entry.get("definition"),
        example=entry.get("example"),
    )

    if added:
        status = "Слово сохранено в твой словарь."
    else:
        status = "Это слово уже есть в твоём словаре."

    await edit_callback_message(
        query,
        format_dictionary_entry(entry) + f"\n\n{status}",
    )


def _primary_translation(value: Optional[str]) -> str:
    """Take one short Russian translation for a quiz answer."""
    raw = (value or "").strip()
    if not raw:
        return ""

    # Stored dictionary cards may contain several translations separated by
    # commas, semicolons, bullets or line breaks. For a quiz we need one clear
    # answer, so use the first non-empty variant.
    parts = re.split(r"[\n,;•]+", raw)
    for part in parts:
        clean = re.sub(r"^[-–—\s]+", "", part).strip()
        if clean:
            return clean[:60]
    return ""


def _review_items(rows: List[tuple]) -> List[dict]:
    items: List[dict] = []
    seen = set()

    for row in rows:
        if len(row) < 2:
            continue
        word = str(row[0] or "").strip()
        translation = _primary_translation(row[1])
        if not word or not translation:
            continue
        if not re.search(r"[A-Za-z]", word):
            continue
        if not re.search(r"[А-Яа-яЁё]", translation):
            continue

        key = (word.lower(), translation.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({"word": word, "translation": translation})

    return items


def _format_saved_words(words: List[tuple]) -> str:
    lines = ["Последние сохранённые слова:\n"]

    for index, item in enumerate(words, start=1):
        word, translation, part_of_speech, definition, example, added_at = item
        title = f"{index}. {word}"
        if translation:
            title += f" — {translation}"

        lines.append(title)
        lines.append(f"{part_of_speech or '—'}: {definition}")
        lines.append("")

    return "\n".join(lines).strip()


def _mywords_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧠 Повторить слова", callback_data="review:start")],
            [InlineKeyboardButton("🗑 Удалить слово", callback_data="delete:start")],
        ]
    )


def _review_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Повторить ещё", callback_data="review:start")],
            [InlineKeyboardButton("📚 Мои слова", callback_data="review:mywords")],
        ]
    )


def _build_review_question(context: ContextTypes.DEFAULT_TYPE) -> tuple:
    items = context.user_data["review_items"]
    pool = context.user_data["review_pool"]
    index = context.user_data["review_index"]
    target = items[index]

    # Alternate EN→RU and RU→EN so both directions are trained.
    en_to_ru = index % 2 == 0
    if en_to_ru:
        prompt = f'Как переводится «{target["word"]}»?'
        correct = target["translation"]
        all_values = [item["translation"] for item in pool]
    else:
        prompt = f'Какое английское слово означает «{target["translation"]}»?'
        correct = target["word"]
        all_values = [item["word"] for item in pool]

    distractors = []
    seen = {correct.lower()}
    candidates = list(all_values)
    random.shuffle(candidates)
    for value in candidates:
        clean = str(value or "").strip()
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        distractors.append(clean)
        if len(distractors) >= 3:
            break

    options = distractors + [correct]
    random.shuffle(options)
    correct_index = options.index(correct)

    context.user_data["review_current"] = {
        "index": index,
        "correct": correct,
        "correct_index": correct_index,
        "options": options,
        "word": target["word"],
        "translation": target["translation"],
    }

    total = len(items)
    text = (
        f"🧠 Повторение слов — {index + 1}/{total}\n\n"
        f"{prompt}\n\n"
        "Выбери ответ:"
    )
    return text, options


def _review_keyboard(context: ContextTypes.DEFAULT_TYPE, options: List[str]) -> InlineKeyboardMarkup:
    session_id = context.user_data["review_session_id"]
    index = context.user_data["review_index"]
    rows = []
    for option_index, option in enumerate(options):
        label = option if len(option) <= 55 else option[:52] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"review:answer:{session_id}:{index}:{option_index}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


async def mywords_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_review_state(context)
    words = get_saved_words(update.effective_user.id, limit=10)

    if not words:
        await safe_reply(
            update.message,
            "Ты пока не сохранил ни одного слова.\nНажми «🔎 Найти слово», чтобы добавить первое.",
        )
        return

    await safe_reply(
        update.message,
        _format_saved_words(words),
        reply_markup=_mywords_keyboard(),
    )

async def delete_start_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    words = get_saved_words(update.effective_user.id, limit=10)

    if not words:
        await edit_callback_message(
            query,
            "В словаре пока нет сохранённых слов.",
        )
        return

    delete_words = [row[0] for row in words]
    context.user_data["delete_words"] = delete_words

    keyboard = [
        [InlineKeyboardButton(f"🗑 {word}", callback_data=f"delete:choose:{index}")]
        for index, word in enumerate(delete_words)
    ]
    keyboard.append(
        [InlineKeyboardButton("↩️ Назад", callback_data="review:mywords")]
    )

    await edit_callback_message(
        query,
        "Какое слово удалить из словаря?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_choose_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        index = int(query.data.split(":")[2])
        words = context.user_data.get("delete_words", [])
        word = words[index]
    except (ValueError, IndexError, AttributeError):
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Да, удалить",
                    callback_data=f"delete:confirm:{index}",
                )
            ],
            [InlineKeyboardButton("↩️ Назад", callback_data="delete:start")],
        ]
    )

    await edit_callback_message(
        query,
        f'Удалить слово «{word}» из словаря?',
        reply_markup=keyboard,
    )


async def delete_confirm_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        index = int(query.data.split(":")[2])
        words = context.user_data.get("delete_words", [])
        word = words[index]
    except (ValueError, IndexError, AttributeError):
        return

    deleted = delete_word(update.effective_user.id, word)
    context.user_data.pop("delete_words", None)

    if deleted:
        text = f'✅ Слово «{word}» удалено из словаря.'
    else:
        text = "Не удалось найти это слово в словаре."

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 Удалить ещё", callback_data="delete:start")],
            [InlineKeyboardButton("📚 Мои слова", callback_data="review:mywords")],
        ]
    )

    await edit_callback_message(
        query,
        text,
        reply_markup=keyboard,
    )
    
async def start_review_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    words = get_saved_words(update.effective_user.id, limit=50)
    pool = _review_items(words)

    if len(pool) < 2:
        clear_review_state(context)
        await edit_callback_message(
            query,
            "Для повторения нужно хотя бы 2 сохранённых слова с переводом.\n\n"
            "Сохрани ещё несколько слов через «🔎 Найти слово».",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📚 Мои слова", callback_data="review:mywords")]]
            ),
        )
        return

    clear_review_state(context)
    selected = random.sample(pool, k=min(5, len(pool)))
    context.user_data["review_session_id"] = uuid4().hex[:8]
    context.user_data["review_pool"] = pool
    context.user_data["review_items"] = selected
    context.user_data["review_index"] = 0
    context.user_data["review_score"] = 0
    context.user_data["review_mistakes"] = []

    text, options = _build_review_question(context)
    await edit_callback_message(
        query,
        text,
        reply_markup=_review_keyboard(context, options),
    )


async def review_answer_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        _, _, session_id, question_str, option_str = query.data.split(":")
        question_index = int(question_str)
        option_index = int(option_str)
    except (AttributeError, ValueError):
        return

    if session_id != context.user_data.get("review_session_id"):
        return
    if question_index != context.user_data.get("review_index"):
        return

    current = context.user_data.get("review_current") or {}
    options = current.get("options") or []
    if not (0 <= option_index < len(options)):
        return

    selected = options[option_index]
    correct_index = current.get("correct_index")
    is_correct = option_index == correct_index

    if is_correct:
        context.user_data["review_score"] = context.user_data.get("review_score", 0) + 1
        feedback = f"✅ Верно! {current.get('word')} — {current.get('translation')}"
    else:
        feedback = (
            f"❌ Неверно. Правильный ответ: {current.get('correct')}\n"
            f"{current.get('word')} — {current.get('translation')}"
        )
        context.user_data.setdefault("review_mistakes", []).append(
            f"{current.get('word')} — {current.get('translation')}"
        )

    next_index = question_index + 1
    context.user_data["review_index"] = next_index
    items = context.user_data.get("review_items", [])

    if next_index >= len(items):
        score = context.user_data.get("review_score", 0)
        total = len(items)
        mistakes = context.user_data.get("review_mistakes", [])

        result = (
            f"{feedback}\n\n"
            "Повторение завершено!\n\n"
            f"Результат: {score}/{total}"
        )
        if mistakes:
            result += "\n\nПовтори ещё:\n" + "\n".join(f"• {item}" for item in mistakes[:5])
        else:
            result += "\n\nОтлично — все ответы правильные."

        clear_review_state(context)
        await edit_callback_message(
            query,
            result,
            reply_markup=_review_result_keyboard(),
        )
        return

    next_text, next_options = _build_review_question(context)
    await edit_callback_message(
        query,
        f"{feedback}\n\n{next_text}",
        reply_markup=_review_keyboard(context, next_options),
    )


async def review_mywords_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)
    clear_review_state(context)
    words = get_saved_words(update.effective_user.id, limit=10)

    if not words:
        await edit_callback_message(
            query,
            "Ты пока не сохранил ни одного слова. Нажми «🔎 Найти слово», чтобы добавить первое.",
        )
        return

    await edit_callback_message(
        query,
        _format_saved_words(words),
        reply_markup=_mywords_keyboard(),
    )


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_review_state(context)
    user = get_user(update.effective_user.id)

    if not user:
        text = "Пока нет сохранённого профиля. Нажми «🧪 Тест уровня» и пройди placement test."
    else:
        goal = user[3] if user[3] else "ещё не выбрана"
        lessons_completed, average_percentage = get_lesson_stats(
            update.effective_user.id
        )
        text = (
            "Твой прогресс:\n\n"
            f"Уровень: {user[2]}\n"
            f"Цель: {goal}\n"
            f"Placement test: {user[4]}/{user[5]}\n"
            f"Завершено уроков: {lessons_completed}\n"
            f"Средний результат уроков: {average_percentage:.0f}%"
        )

    await safe_reply(update.message, text)


async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_review_state(context)
    query = update.callback_query
    await acknowledge_callback(query)

    clear_lesson_state(context)
    context.user_data["test_score"] = 0
    context.user_data["question_index"] = 0
    context.user_data["answered_questions"] = set()
    context.user_data.pop("goal_saved", None)

    await edit_callback_message(
        query,
        "Начинаем! Выбери один вариант ответа.\n\n"
        f"Вопрос 1/{len(QUESTIONS)}\n\n{QUESTIONS[0]['question']}",
        reply_markup=answer_keyboard(0),
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        _, question_str, option_str = query.data.split(":")
        question_index = int(question_str)
        selected_index = int(option_str)
    except (ValueError, AttributeError):
        logger.warning("Некорректный callback_data: %r", query.data)
        return

    current_index = context.user_data.get("question_index")
    answered_questions = context.user_data.setdefault("answered_questions", set())

    if question_index in answered_questions or current_index != question_index:
        return

    answered_questions.add(question_index)

    question = QUESTIONS[question_index]
    is_correct = selected_index == question["correct"]

    if is_correct:
        context.user_data["test_score"] = context.user_data.get("test_score", 0) + 1
        feedback = "✅ Верно!"
    else:
        correct_answer = question["options"][question["correct"]]
        feedback = f"❌ Неверно. Правильный ответ: {correct_answer}"

    next_index = question_index + 1
    context.user_data["question_index"] = next_index

    if next_index < len(QUESTIONS):
        next_text = (
            f"{feedback}\n\n"
            f"Вопрос {next_index + 1}/{len(QUESTIONS)}\n\n"
            f"{QUESTIONS[next_index]['question']}"
        )
        await edit_callback_message(
            query,
            next_text,
            reply_markup=answer_keyboard(next_index),
        )
        return

    score = context.user_data.get("test_score", 0)
    level = get_level(score)
    tg_user = update.effective_user

    save_test_result(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        level=level,
        score=score,
        total_questions=len(QUESTIONS),
    )

    final_text = (
        f"{feedback}\n\n"
        "Тест завершён!\n\n"
        f"Результат: {score}/{len(QUESTIONS)}\n"
        f"Ориентировочный стартовый уровень: {level}\n\n"
        "Это короткая первичная оценка, а не полноценная CEFR-сертификация.\n\n"
        "Теперь выбери главную цель изучения английского:"
    )

    await edit_callback_message(query, final_text, reply_markup=goal_keyboard())


async def handle_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        goal = query.data.split(":", maxsplit=1)[1]
    except (AttributeError, IndexError):
        logger.warning("Некорректный goal callback_data: %r", query.data)
        return

    if context.user_data.get("goal_saved"):
        return

    user = get_user(update.effective_user.id)
    if not user:
        await edit_callback_message(query, "Сначала нужно пройти placement test. Нажми «🧪 Тест уровня».")
        return

    context.user_data["goal_saved"] = True
    update_goal(update.effective_user.id, goal)

    await edit_callback_message(
        query,
        f"Готово! Цель сохранена: {goal}.\n\n"
        "Профиль EnglishMate создан.\n"
        f"Начать персональный урок: {BTN_LESSON}\n"
        f"Посмотреть прогресс: {BTN_PROGRESS}",
    )


async def lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_review_state(context)
    user = get_user(update.effective_user.id)

    if not user:
        await safe_reply(
            update.message,
            "Сначала нужно пройти placement test. Нажми «🧪 Тест уровня».",
        )
        return

    level = user[2]
    goal = user[3]

    if not goal:
        await safe_reply(
            update.message,
            "У тебя ещё не выбрана цель обучения. Нажми «🧪 Тест уровня» и заверши настройку профиля.",
        )
        return

    recent_questions = context.user_data.get("recent_lesson_questions", [])
    saved_word_rows = get_saved_words(update.effective_user.id, limit=20)
    saved_word_items = _review_items(saved_word_rows)
    lesson_tasks = await generate_lesson_with_groq(
        level,
        goal,
        recent_questions,
        saved_words=saved_word_items,
    )
    if not lesson_tasks:
        # API fallback keeps the same short, modern lesson style.
        lesson_tasks = build_modern_fallback_lesson(level, goal)

    # Remember several recent lessons in memory so the next generated lesson is fresh.
    updated_recent = list(recent_questions)
    updated_recent.extend(task.get("question", "") for task in lesson_tasks)
    context.user_data["recent_lesson_questions"] = [q for q in updated_recent if q][-30:]

    session_id = uuid4().hex[:8]

    context.user_data["lesson_session_id"] = session_id
    context.user_data["lesson_tasks"] = lesson_tasks
    context.user_data["lesson_index"] = 0
    context.user_data["lesson_score"] = 0
    context.user_data["lesson_answered"] = set()
    context.user_data["lesson_level"] = level
    context.user_data["lesson_goal"] = goal

    intro = (
        f"Персональный урок готов.\n\n"
        f"Уровень: {level}\n"
        f"Цель: {goal}\n"
        f"Заданий: {len(lesson_tasks)}\n\n"
    )

    first_task = lesson_tasks[0]
    text = intro + format_lesson_task(0, len(lesson_tasks), first_task)

    if first_task["type"] == "mcq":
        await safe_reply(
            update.message,
            text,
            reply_markup=lesson_keyboard(session_id, 0, first_task),
        )
    else:
        await safe_reply(update.message, text)


async def send_next_lesson_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    feedback: str,
    from_callback: bool,
) -> None:
    tasks = context.user_data.get("lesson_tasks", [])
    index = context.user_data.get("lesson_index", 0)

    if index >= len(tasks):
        score = context.user_data.get("lesson_score", 0)
        total = len(tasks)
        percentage = (score / total * 100) if total else 0.0
        level = context.user_data.get("lesson_level", "")
        goal = context.user_data.get("lesson_goal", "")

        save_lesson_result(
            telegram_id=update.effective_user.id,
            level=level,
            goal=goal,
            score=score,
            total_questions=total,
            percentage=percentage,
        )

        if percentage >= 80:
            comment = "Отличный результат. Можно постепенно усложнять задания."
        elif percentage >= 60:
            comment = "Хорошая база. Стоит повторить ошибки из этого урока."
        else:
            comment = "Лучше ещё раз пройти похожие задания и закрепить тему."

        final_text = (
            f"{feedback}\n\n"
            "Урок завершён!\n\n"
            f"Результат: {score}/{total}\n"
            f"Процент: {percentage:.0f}%\n"
            f"{comment}\n\n"
            f"Новый урок: {BTN_LESSON}\n"
            f"Прогресс: {BTN_PROGRESS}"
        )

        if from_callback:
            await safe_reply(update.callback_query.message, final_text)
        else:
            await safe_reply(update.message, final_text)

        clear_lesson_state(context)
        return

    task = tasks[index]
    next_text = (
        f"{feedback}\n\n"
        + format_lesson_task(index, len(tasks), task)
    )

    if from_callback:
        # Do not overwrite the previous lesson card. Sending a new message keeps
        # every question and its feedback visible in chat history.
        if task["type"] == "mcq":
            await safe_reply(
                update.callback_query.message,
                next_text,
                reply_markup=lesson_keyboard(
                    context.user_data["lesson_session_id"],
                    index,
                    task,
                ),
            )
        else:
            await safe_reply(update.callback_query.message, next_text)
    else:
        if task["type"] == "mcq":
            await safe_reply(
                update.message,
                next_text,
                reply_markup=lesson_keyboard(
                    context.user_data["lesson_session_id"],
                    index,
                    task,
                ),
            )
        else:
            await safe_reply(update.message, next_text)


async def handle_lesson_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await acknowledge_callback(query)

    try:
        _, session_id, task_str, option_str = query.data.split(":")
        task_index = int(task_str)
        selected_index = int(option_str)
    except (ValueError, AttributeError):
        return

    if session_id != context.user_data.get("lesson_session_id"):
        return

    current_index = context.user_data.get("lesson_index")
    answered = context.user_data.setdefault("lesson_answered", set())

    if task_index in answered or current_index != task_index:
        return

    task = current_lesson_task(context)
    if not task or task.get("type") != "mcq":
        return

    answered.add(task_index)

    # Freeze the answered question so the user cannot click it again, while
    # preserving the question itself in the chat history.
    try:
        await retry_telegram_call(
            query.edit_message_reply_markup,
            reply_markup=None,
            retries=1,
        )
    except TelegramError as exc:
        logger.warning("Could not remove lesson buttons: %s", exc)

    is_correct = selected_index == task["correct"]

    if is_correct:
        context.user_data["lesson_score"] = context.user_data.get("lesson_score", 0) + 1
        feedback = f"✅ Верно!\n{task['explanation']}"
    else:
        correct_answer = task["options"][task["correct"]]
        feedback = (
            f"❌ Неверно.\n"
            f"Правильный ответ: {correct_answer}\n"
            f"{task['explanation']}"
        )

    context.user_data["lesson_index"] = task_index + 1
    await send_next_lesson_task(update, context, feedback, from_callback=True)


async def evaluate_lesson_text_with_groq(task: dict, user_answer: str) -> Optional[dict]:
    """Grade a short free-text lesson answer by meaning and communicative success.

    The reference answer is only an example, not a phrase the learner must copy.
    Only serious mistakes should make the answer wrong.
    """
    if not GROQ_API_KEY:
        return None

    schema = {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["correct", "wrong"],
            },
            "core_meaning_preserved": {"type": "boolean"},
            "error_severity": {
                "type": "string",
                "enum": ["none", "minor", "major"],
            },
            "feedback_ru": {"type": "string"},
            "better_answer": {"type": "string"},
        },
        "required": [
            "verdict",
            "core_meaning_preserved",
            "error_severity",
            "feedback_ru",
            "better_answer",
        ],
        "additionalProperties": False,
    }

    system_prompt = (
        "You are a supportive English teacher grading ONE short learner answer. "
        "Judge whether the learner successfully completed the task, NOT whether they copied the reference answer. "
        "The reference answer is only one possible example. "
        "Use only two verdicts: correct or wrong. "

        "Mark CORRECT whenever the core meaning/communicative goal is achieved and the English is understandable. "
        "Minor grammar issues, articles, capitalization, punctuation, spelling, commas, stylistic differences, "
        "or slightly non-native wording must still be CORRECT. Do not mention such tiny issues in feedback. "
        "A different but natural phrasing is also CORRECT. "

        "For open-ended reply tasks (for example 'Reply to a colleague...'), accept any natural response that "
        "appropriately answers the situation; do NOT require all wording or details from the reference. "
        "For translation tasks, require the essential situation and message, but allow natural paraphrases. "
        "Differences in nuance or strength such as 'unlikely' versus 'not sure', or a slightly different natural modal, "
        "must still be CORRECT unless that exact nuance is the explicit language point being tested. "
        "If the answer communicates essentially the same real-world message, give the learner the point. "
        "For rewrite/register tasks, require the requested tone/register, not identical wording. "

        "Mark WRONG only for a serious problem: an essential event, participant, time reference, polarity, or requested action "
        "is missing or changed; the response contradicts the task; does not actually answer it; is largely unintelligible; "
        "or the specific grammar/lexical point explicitly being tested is substantially wrong. "
        "Set core_meaning_preserved=true whenever the learner communicates the same practical message, even if modality, "
        "probability strength, register, or wording is slightly different. Differences like 'unlikely' vs 'not sure' are minor, "
        "not major, unless the exercise explicitly asks to distinguish that exact nuance. "
        "Use error_severity='minor' for small nuance or naturalness issues and 'major' only for a truly failed task. "

        "If correct, feedback_ru should usually be empty. If there is a meaningful nuance improvement, phrase it only as "
        "'Можно точнее: ...' and still keep the verdict correct. Never criticize articles, commas, capitalization, punctuation, "
        "or harmless stylistic choices. "
        "If wrong, explain the single main problem briefly in Russian. "
        "better_answer should be a short natural example, but never imply it is the only acceptable answer."
    )

    payload = {
        "task": task.get("question", ""),
        "reference_answer_example": task.get("answer_display", ""),
        "teacher_note": task.get("explanation", ""),
        "student_answer": user_answer,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            result = await groq_json(
                client,
                system_prompt,
                json.dumps(payload, ensure_ascii=False),
                300,
                schema_name="lesson_answer_grade",
                schema=schema,
            )
    except Exception as exc:
        logger.warning("Could not semantically grade lesson answer: %s", exc)
        return None

    # Extra safety: this tutor should fail only hard mistakes.
    # If the model itself says the core message is preserved or the issue is minor,
    # the learner gets the point even if the raw verdict came back as "wrong".
    feedback = (result.get("feedback_ru") or "").lower()
    cosmetic_markers = (
        "артикл", "запят", "пунктуац", "заглав", "регистр",
        "capital", "comma", "punctuation", "article",
    )
    nuance_markers = (
        "нюанс", "оттенок", "точнее", "естественнее", "степень уверенности",
        "неопредел", "малая вероят", "вероятност", "чуть мягче", "чуть сильнее",
        "менее категор", "более категор", "слабее", "сильнее",
    )
    hard_error_markers = (
        "противополож", "противореч", "другой смысл", "смысл измен",
        "не выполн", "не отвечает", "не передаёт основной", "не передает основной",
        "потерян основной", "другое время", "неверное время", "не тот субъект",
        "отрицание измен", "уже заверш", "вчера",
    )

    core_preserved = bool(result.get("core_meaning_preserved"))
    severity = result.get("error_severity")
    nuance_only = any(marker in feedback for marker in nuance_markers) and not any(
        marker in feedback for marker in hard_error_markers
    )

    # Final deterministic policy for EnglishMate:
    # only genuinely meaning-changing errors lose the point.
    # If Groq labels a difference in probability/modality/register as "major" but its own
    # explanation shows that the practical message is still the same, we override it.
    if any(marker in feedback for marker in cosmetic_markers):
        result["verdict"] = "correct"
        result["feedback_ru"] = ""
    elif nuance_only:
        result["verdict"] = "correct"
        result["error_severity"] = "minor"
    elif severity in {"none", "minor"}:
        result["verdict"] = "correct"
    elif severity == "major":
        result["verdict"] = "wrong"
    elif core_preserved:
        result["verdict"] = "correct"
    else:
        result["verdict"] = "wrong"

    return result


async def handle_text_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    task = current_lesson_task(context)

    if not task or task.get("type") != "text":
        return

    task_index = context.user_data.get("lesson_index")
    answered = context.user_data.setdefault("lesson_answered", set())

    if task_index in answered:
        return

    answered.add(task_index)

    raw_user_answer = (update.message.text or "").strip()
    user_answer = normalize_text(raw_user_answer)
    accepted_answers = [normalize_text(answer) for answer in task["answers"]]
    is_correct = user_answer in accepted_answers
    semantic_grade = None

    if not is_correct:
        semantic_grade = await evaluate_lesson_text_with_groq(task, raw_user_answer)
        if semantic_grade is not None:
            is_correct = semantic_grade.get("verdict") == "correct"

    if is_correct:
        context.user_data["lesson_score"] = context.user_data.get("lesson_score", 0) + 1

        # Keep feedback clean: if the answer communicates the right thing, do not nitpick.
        if semantic_grade:
            note = (semantic_grade.get("feedback_ru") or "").strip()
            better = (semantic_grade.get("better_answer") or "").strip()

            feedback = "✅ Верно!"
            if note:
                feedback += f"\n{note}"
                if better and normalize_text(better) != user_answer:
                    feedback += f"\nМожно ещё так: {better}"
        else:
            feedback = f"✅ Верно!\n{task['explanation']}"
    else:
        if semantic_grade:
            note = (semantic_grade.get("feedback_ru") or "Смысл задания передан неверно.").strip()
            better = (semantic_grade.get("better_answer") or task["answer_display"]).strip()
            feedback = (
                f"❌ Неверно.\n{note}\n"
                f"Один из хороших вариантов: {better}"
            )
        else:
            feedback = (
                "❌ Неверно.\n"
                f"Один из хороших вариантов: {task['answer_display']}\n"
                f"{task['explanation']}"
            )

    context.user_data["lesson_index"] = task_index + 1
    await send_next_lesson_task(update, context, feedback, from_callback=False)


async def handle_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route normal text messages from the persistent menu.

    A free-text lesson answer has priority, so adding the menu does not break
    the existing lesson flow.
    """
    task = current_lesson_task(context)
    if task and task.get("type") == "text":
        await handle_text_answer(update, context)
        return

    text = (update.message.text or "").strip()

    # Menu buttons should always cancel a pending dictionary input.
    if text == BTN_FIND_WORD:
        context.user_data["awaiting_dictionary_word"] = True
        await safe_reply(
            update.message,
            "Напиши слово на русском или английском одним сообщением. Например: рука или arm",
            reply_markup=main_menu_keyboard(),
        )
        return

    if text == BTN_MY_WORDS:
        context.user_data.pop("awaiting_dictionary_word", None)
        await mywords_command(update, context)
        return

    if text == BTN_LESSON:
        context.user_data.pop("awaiting_dictionary_word", None)
        await lesson_command(update, context)
        return

    if text == BTN_PROGRESS:
        context.user_data.pop("awaiting_dictionary_word", None)
        await progress(update, context)
        return

    if text == BTN_TEST:
        context.user_data.pop("awaiting_dictionary_word", None)
        await safe_reply(
            update.message,
            "Нажми кнопку ниже, чтобы начать placement test.",
            reply_markup=placement_test_keyboard(),
        )
        return

    if text == BTN_HELP:
        context.user_data.pop("awaiting_dictionary_word", None)
        await help_command(update, context)
        return

    if context.user_data.get("awaiting_dictionary_word"):
        context.user_data.pop("awaiting_dictionary_word", None)
        await lookup_and_send_query(update, context, text)
        return

    await safe_reply(
        update.message,
        "Выбери действие кнопкой внизу. Для поиска слова нажми «🔎 Найти слово».",
        reply_markup=main_menu_keyboard(),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error

    if isinstance(error, TimedOut):
        logger.warning("Telegram request timed out. Bot keeps running.")
        return

    if isinstance(error, NetworkError):
        logger.warning("Temporary Telegram network error: %s. Bot keeps running.", error)
        return

    if isinstance(error, TelegramError):
        logger.error("Telegram API error: %s", error)
        return

    logger.exception("Unhandled exception while processing update", exc_info=error)


async def post_init(application: Application) -> None:
    try:
        await retry_telegram_call(
            application.bot.set_my_commands,
            [
                ("start", "Пройти или повторить placement test"),
                ("lesson", "Начать персональный урок"),
                ("word", "Перевести слово RU/EN"),
                ("mywords", "Показать сохранённые слова"),
                ("progress", "Посмотреть прогресс"),
                ("help", "Помощь"),
            ],
            retries=2,
        )
    except (TimedOut, NetworkError):
        logger.warning("Не удалось обновить список команд при запуске.")


def build_application() -> Application:
    return (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(15)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(10)
        .get_updates_connect_timeout(15)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(10)
        .post_init(post_init)
        .build()
    )


def main() -> None:
    if not TOKEN or TOKEN == "your_bot_token_here":
        raise RuntimeError(
            "Не найден корректный TELEGRAM_BOT_TOKEN. "
            "Проверь файл .env и вставь реальный токен BotFather."
        )

    init_db()

    application = build_application()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("lesson", lesson_command))
    application.add_handler(CommandHandler("word", word_command))
    application.add_handler(CommandHandler("mywords", mywords_command))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(start_test, pattern=r"^start_test$"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^answer:"))
    application.add_handler(CallbackQueryHandler(handle_goal, pattern=r"^goal:"))
    application.add_handler(
        CallbackQueryHandler(save_word_callback, pattern=r"^saveword:")
    )
    application.add_handler(
        CallbackQueryHandler(start_review_callback, pattern=r"^review:start$")
    )
    application.add_handler(
        CallbackQueryHandler(review_answer_callback, pattern=r"^review:answer:")
    )
    application.add_handler(
        CallbackQueryHandler(review_mywords_callback, pattern=r"^review:mywords$")
    )
    application.add_handler(
    CallbackQueryHandler(delete_start_callback, pattern=r"^delete:start$")
)
application.add_handler(
    CallbackQueryHandler(delete_choose_callback, pattern=r"^delete:choose:")
)
application.add_handler(
    CallbackQueryHandler(delete_confirm_callback, pattern=r"^delete:confirm:")
)
    application.add_handler(
        CallbackQueryHandler(handle_lesson_choice, pattern=r"^lesson:")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    application.add_error_handler(error_handler)

    print("EnglishMate Lab 3 review words v4 запущен. Для остановки нажми Ctrl+C.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        timeout=30,
        bootstrap_retries=3,
    )


if __name__ == "__main__":
    main()
