import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

import httpx

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Определить мой уровень", callback_data="start_test")]]
    )
    text = (
        "Привет! Я EnglishMate — помощник для изучения английского языка.\n\n"
        "Сначала я проведу короткий placement test из 12 вопросов и определю "
        "примерную стартовую сложность обучения. Затем ты сможешь выбрать цель занятий.\n\n"
        "Нажми кнопку ниже, чтобы начать."
    )
    await safe_reply(update.message, text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Доступные команды:\n"
        "/start — пройти или повторить placement test\n"
        "/lesson — начать персональный урок\n"
        "/word <слово> — найти слово в английском словаре\n"
        "/mywords — показать последние сохранённые слова\n"
        "/progress — посмотреть прогресс\n"
        "/help — показать помощь"
    )
    await safe_reply(update.message, text)



DICTIONARY_API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"


def _first_nonempty(values):
    for value in values:
        if value:
            return value
    return None


def parse_dictionary_entry(payload: object, requested_word: str) -> dict:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("Unexpected Dictionary API response")

    entry = payload[0]
    word = str(entry.get("word") or requested_word).strip()

    phonetic = entry.get("phonetic")
    if not phonetic:
        phonetics = entry.get("phonetics") or []
        if isinstance(phonetics, list):
            phonetic = _first_nonempty(
                item.get("text")
                for item in phonetics
                if isinstance(item, dict)
            )

    meanings = entry.get("meanings") or []
    if not isinstance(meanings, list) or not meanings:
        raise ValueError("Dictionary API response has no meanings")

    meaning = next(
        (item for item in meanings if isinstance(item, dict) and item.get("definitions")),
        None,
    )
    if not meaning:
        raise ValueError("Dictionary API response has no definitions")

    part_of_speech = str(meaning.get("partOfSpeech") or "—")
    definitions = meaning.get("definitions") or []
    definition_item = next(
        (item for item in definitions if isinstance(item, dict) and item.get("definition")),
        None,
    )
    if not definition_item:
        raise ValueError("Dictionary API response has no definition text")

    definition = str(definition_item.get("definition")).strip()
    example = definition_item.get("example")

    synonyms = []
    for source in (
        definition_item.get("synonyms") or [],
        meaning.get("synonyms") or [],
    ):
        if isinstance(source, list):
            for synonym in source:
                synonym = str(synonym).strip()
                if synonym and synonym.lower() not in {s.lower() for s in synonyms}:
                    synonyms.append(synonym)
                if len(synonyms) >= 3:
                    break
        if len(synonyms) >= 3:
            break

    return {
        "word": word,
        "phonetic": str(phonetic).strip() if phonetic else None,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "example": str(example).strip() if example else None,
        "synonyms": synonyms,
    }


def format_dictionary_entry(entry: dict) -> str:
    lines = [f"Слово: {entry['word']}"]

    if entry.get("phonetic"):
        lines.append(f"Транскрипция: {entry['phonetic']}")

    lines.append(f"Часть речи: {entry['part_of_speech']}")
    lines.append(f"Определение: {entry['definition']}")

    if entry.get("example"):
        lines.append(f"Пример: {entry['example']}")

    if entry.get("synonyms"):
        lines.append("Синонимы: " + ", ".join(entry["synonyms"]))

    return "\n".join(lines)


async def word_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await safe_reply(
            update.message,
            "После команды укажи английское слово.\nНапример: /word opportunity",
        )
        return

    requested_word = " ".join(context.args).strip().lower()

    if len(requested_word) > 50 or not re.fullmatch(r"[a-zA-Z][a-zA-Z' -]*", requested_word):
        await safe_reply(
            update.message,
            "Пожалуйста, введи английское слово латиницей.\nНапример: /word opportunity",
        )
        return

    url = f"{DICTIONARY_API_BASE}/{quote(requested_word)}"

    try:
        timeout = httpx.Timeout(10.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)

        if response.status_code == 404:
            await safe_reply(
                update.message,
                f"Не удалось найти слово «{requested_word}» в словаре.",
            )
            return

        response.raise_for_status()

        try:
            payload = response.json()
            entry = parse_dictionary_entry(payload, requested_word)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Dictionary API returned invalid data for %s: %s", requested_word, exc)
            await safe_reply(
                update.message,
                "Словарь вернул неожиданный ответ. Попробуй другое слово чуть позже.",
            )
            return

    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        logger.warning("Dictionary API network error for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Словарь сейчас отвечает слишком долго. Попробуй ещё раз через несколько секунд.",
        )
        return
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Dictionary API HTTP error for %s: %s",
            requested_word,
            exc.response.status_code,
        )
        await safe_reply(
            update.message,
            "Не удалось получить данные из словаря. Попробуй позже.",
        )
        return
    except httpx.HTTPError as exc:
        logger.warning("Dictionary API error for %s: %s", requested_word, exc)
        await safe_reply(
            update.message,
            "Не удалось подключиться к словарю. Попробуй позже.",
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
            "Данные этого слова уже не находятся в памяти бота. Выполни поиск через /word ещё раз.",
        )
        return

    added = save_word(
        telegram_id=update.effective_user.id,
        word=entry["word"],
        phonetic=entry.get("phonetic"),
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


async def mywords_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    words = get_saved_words(update.effective_user.id, limit=10)

    if not words:
        await safe_reply(
            update.message,
            "Ты пока не сохранил ни одного слова.\nНайди слово через /word <слово>.",
        )
        return

    lines = ["Последние сохранённые слова:\n"]

    for index, item in enumerate(words, start=1):
        word, phonetic, part_of_speech, definition, example, added_at = item

        title = f"{index}. {word}"
        if phonetic:
            title += f" — {phonetic}"

        lines.append(title)
        lines.append(f"{part_of_speech or '—'}: {definition}")
        if example:
            lines.append(f"Пример: {example}")
        lines.append("")

    await safe_reply(update.message, "\n".join(lines).strip())


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)

    if not user:
        text = "Пока нет сохранённого профиля. Нажми /start и пройди placement test."
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
        await edit_callback_message(query, "Сначала нужно пройти placement test. Нажми /start.")
        return

    context.user_data["goal_saved"] = True
    update_goal(update.effective_user.id, goal)

    await edit_callback_message(
        query,
        f"Готово! Цель сохранена: {goal}.\n\n"
        "Профиль EnglishMate создан.\n"
        "Начать персональный урок: /lesson\n"
        "Посмотреть прогресс: /progress",
    )


async def lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)

    if not user:
        await safe_reply(
            update.message,
            "Сначала нужно пройти placement test. Нажми /start.",
        )
        return

    level = user[2]
    goal = user[3]

    if not goal:
        await safe_reply(
            update.message,
            "У тебя ещё не выбрана цель обучения. Нажми /start и заверши настройку профиля.",
        )
        return

    lesson_tasks = build_lesson(level, goal)
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
            "Новый урок: /lesson\n"
            "Прогресс: /progress"
        )

        if from_callback:
            await edit_callback_message(update.callback_query, final_text)
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
        if task["type"] == "mcq":
            await edit_callback_message(
                update.callback_query,
                next_text,
                reply_markup=lesson_keyboard(
                    context.user_data["lesson_session_id"],
                    index,
                    task,
                ),
            )
        else:
            # После MCQ следующий вопрос может требовать текстовый ответ:
            # редактируем текущую карточку и убираем кнопки.
            await edit_callback_message(update.callback_query, next_text)
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


async def handle_text_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    task = current_lesson_task(context)

    if not task or task.get("type") != "text":
        # Обычные сообщения вне задания не мешают боту.
        return

    task_index = context.user_data.get("lesson_index")
    answered = context.user_data.setdefault("lesson_answered", set())

    if task_index in answered:
        return

    answered.add(task_index)

    user_answer = normalize_text(update.message.text)
    accepted_answers = [normalize_text(answer) for answer in task["answers"]]
    is_correct = user_answer in accepted_answers

    if is_correct:
        context.user_data["lesson_score"] = context.user_data.get("lesson_score", 0) + 1
        feedback = f"✅ Верно!\n{task['explanation']}"
    else:
        feedback = (
            "❌ Не совсем.\n"
            f"Один из хороших вариантов: {task['answer_display']}\n"
            f"{task['explanation']}"
        )

    context.user_data["lesson_index"] = task_index + 1
    await send_next_lesson_task(update, context, feedback, from_callback=False)


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
                ("word", "Найти английское слово"),
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
        CallbackQueryHandler(handle_lesson_choice, pattern=r"^lesson:")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer)
    )
    application.add_error_handler(error_handler)

    print("EnglishMate Lab 2 запущен. Для остановки нажми Ctrl+C.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        timeout=30,
        bootstrap_retries=3,
    )


if __name__ == "__main__":
    main()
