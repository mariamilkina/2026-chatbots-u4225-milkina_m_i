import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from database import init_db, get_user, save_test_result, update_goal


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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


def get_level(score: int) -> str:
    """Return an approximate starting level based on the short placement test."""
    if score <= 3:
        return "A1"
    if score <= 6:
        return "A2"
    if score <= 9:
        return "B1"
    return "B2"


def answer_keyboard(question_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=option, callback_data=f"answer:{question_index}:{i}")]
        for i, option in enumerate(QUESTIONS[question_index]["options"])
    ]
    return InlineKeyboardMarkup(buttons)


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
    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Доступные команды:\n"
        "/start — начать или пройти тест заново\n"
        "/progress — посмотреть сохранённый результат\n"
        "/help — показать помощь"
    )
    await update.message.reply_text(text)


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "Пока нет сохранённого результата. Нажми /start и пройди placement test."
        )
        return

    goal = user[3] if user[3] else "ещё не выбрана"
    await update.message.reply_text(
        "Твой прогресс:\n\n"
        f"Уровень: {user[2]}\n"
        f"Цель: {goal}\n"
        f"Placement test: {user[4]}/{user[5]}"
    )


async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    context.user_data["test_score"] = 0
    context.user_data["question_index"] = 0

    await query.edit_message_text(
        "Начинаем! Выбери один вариант ответа.\n\n"
        f"Вопрос 1/{len(QUESTIONS)}\n\n{QUESTIONS[0]['question']}",
        reply_markup=answer_keyboard(0),
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, question_str, option_str = query.data.split(":")
        question_index = int(question_str)
        selected_index = int(option_str)
    except (ValueError, AttributeError):
        await query.answer("Не удалось обработать ответ.", show_alert=True)
        return

    current_index = context.user_data.get("question_index")
    if current_index != question_index:
        await query.answer("Этот вопрос уже обработан.", show_alert=True)
        return

    question = QUESTIONS[question_index]
    is_correct = selected_index == question["correct"]
    if is_correct:
        context.user_data["test_score"] = context.user_data.get("test_score", 0) + 1

    # Remove buttons from the answered question so it cannot be answered twice.
    await query.edit_message_reply_markup(reply_markup=None)

    feedback = "Верно!" if is_correct else (
        f"Неверно. Правильный ответ: {question['options'][question['correct']]}"
    )
    await query.message.reply_text(feedback)

    next_index = question_index + 1
    context.user_data["question_index"] = next_index

    if next_index < len(QUESTIONS):
        await query.message.reply_text(
            f"Вопрос {next_index + 1}/{len(QUESTIONS)}\n\n"
            f"{QUESTIONS[next_index]['question']}",
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

    goal_keyboard = InlineKeyboardMarkup(
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

    await query.message.reply_text(
        f"Тест завершён!\n\n"
        f"Результат: {score}/{len(QUESTIONS)}\n"
        f"Ориентировочный стартовый уровень: {level}\n\n"
        "Это короткая первичная оценка, а не полноценная CEFR-сертификация.\n\n"
        "Теперь выбери главную цель изучения английского:",
        reply_markup=goal_keyboard,
    )


async def handle_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    goal = query.data.split(":", maxsplit=1)[1]
    user = get_user(update.effective_user.id)

    if not user:
        await query.edit_message_text(
            "Сначала нужно пройти placement test. Нажми /start."
        )
        return

    update_goal(update.effective_user.id, goal)
    await query.edit_message_text(
        f"Готово! Цель сохранена: {goal}.\n\n"
        "Профиль EnglishMate создан. Посмотреть результат можно командой /progress."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception while processing update", exc_info=context.error)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            ("start", "Начать и пройти тест"),
            ("progress", "Посмотреть прогресс"),
            ("help", "Помощь"),
        ]
    )


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "Не найден TELEGRAM_BOT_TOKEN. Создай файл .env и добавь в него токен BotFather."
        )

    init_db()

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(start_test, pattern=r"^start_test$"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^answer:"))
    application.add_handler(CallbackQueryHandler(handle_goal, pattern=r"^goal:"))
    application.add_error_handler(error_handler)

    print("EnglishMate запущен. Для остановки нажми Ctrl+C.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
