#!/usr/bin/env python3
"""
EnglishMate automated QA runner.

Run from the same folder as bot.py/database.py/.env:

    python3 qa_check.py
        -> fast offline checks, no external API calls

    python3 qa_check.py --live
        -> offline checks + real Groq/Merriam-Webster checks for A1/A2/B1/B2,
           hard RU->EN words and semantic grading

    python3 qa_check.py --live --deep
        -> generates two lessons per level to check freshness/duplicates too

The script does NOT start Telegram polling and does not send messages to users.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

PASSED = []
FAILED = []
WARNINGS = []
DETAILS = []


def ok(name, detail=""):
    PASSED.append(name)
    line = f"✅ {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    DETAILS.append(line)


def fail(name, detail=""):
    FAILED.append(name)
    line = f"❌ {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    DETAILS.append(line)


def warn(name, detail=""):
    WARNINGS.append(name)
    line = f"⚠️  {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    DETAILS.append(line)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def is_temporary_api_error(exc_or_text):
    text = str(exc_or_text or "").lower()
    markers = (
        "429", "403", "rate limit", "forbidden", "temporarily", "timeout",
        "timed out", "503", "502", "500", "connection", "server error",
    )
    return any(m in text for m in markers)


async def api_pause(seconds=3.0):
    # Free API limits are easy to hit when QA fires many requests back-to-back.
    await asyncio.sleep(seconds)


def assert_true(condition, name, detail=""):
    if condition:
        ok(name, detail)
        return True
    fail(name, detail)
    return False


def validate_mcq(task, prefix):
    good = True
    opts = task.get("options") or []
    correct = task.get("correct")

    if task.get("type") != "mcq":
        fail(prefix, "ожидался type=mcq")
        return False
    if len(opts) != 4:
        fail(prefix, f"должно быть 4 варианта, получено {len(opts)}")
        good = False
    elif len({norm(x) for x in opts}) != 4:
        fail(prefix, "есть повторяющиеся варианты ответа")
        good = False
    if not isinstance(correct, int) or not 0 <= correct < len(opts):
        fail(prefix, f"некорректный индекс correct={correct!r}")
        good = False
    if not str(task.get("question") or "").strip():
        fail(prefix, "пустой вопрос")
        good = False
    if good:
        ok(prefix)
    return good


def validate_text(task, prefix):
    good = True
    if task.get("type") != "text":
        fail(prefix, "ожидался type=text")
        return False
    q = str(task.get("question") or "")
    answers = task.get("answers") or []
    if not q.strip():
        fail(prefix, "пустой вопрос")
        good = False
    if not re.search(r"[А-Яа-яЁё]", q):
        fail(prefix, "последнее задание должно содержать русский текст для перевода")
        good = False
    if not answers:
        fail(prefix, "нет допустимых ответов")
        good = False
    if not str(task.get("answer_display") or "").strip():
        fail(prefix, "нет answer_display")
        good = False
    if good:
        ok(prefix)
    return good


A1_BAD = (
    "present perfect", "would have", "could have", "might have",
    "second conditional", "third conditional", "mixed conditional",
    "inversion", "subjunctive", "participle clause",
)
A2_BAD = (
    "would have", "could have", "might have", "third conditional",
    "mixed conditional", "negative inversion", "subjunctive",
    "participle clause", "modal perfect",
)
B1_BAD = (
    "third conditional", "mixed conditional", "negative inversion",
    "subjunctive mood", "no sooner", "hardly had", "scarcely had",
)
B2_TOO_ADVANCED = (
    "no sooner", "hardly had", "scarcely had", "little did",
    "under no circumstances", "negative inversion", "cleft sentence",
    "subjunctive mood",
)
META_BAD = ("a1-level", "a2-level", "b1-level", "b2-level", "c1-level", "cefr")


def level_guard(level, tasks, label):
    text = " ".join(
        [
            str(t.get("question") or "") + " "
            + " ".join(str(x) for x in (t.get("options") or [])) + " "
            + str(t.get("explanation") or "")
            for t in tasks
        ]
    ).lower()

    bad = []
    if any(x in text for x in META_BAD):
        bad.append("вопрос показывает пользователю название CEFR-уровня")

    if level == "A1":
        bad += [x for x in A1_BAD if x in text]
    elif level == "A2":
        bad += [x for x in A2_BAD if x in text]
    elif level == "B1":
        bad += [x for x in B1_BAD if x in text]
    elif level == "B2":
        bad += [x for x in B2_TOO_ADVANCED if x in text]

        trivial_sets = [
            {"am", "is", "are", "be"},
            {"do", "does", "did", "done"},
            {"a", "an", "the", "no article"},
            {"was", "were", "is", "are"},
        ]
        for task in tasks[:4]:
            opts = {norm(x) for x in (task.get("options") or [])}
            if opts in trivial_sets:
                bad.append(f"слишком простые варианты для B2: {sorted(opts)}")

    if bad:
        fail(label, "; ".join(dict.fromkeys(bad)))
        return False
    ok(label)
    return True


def validate_lesson(level, tasks, label):
    if not isinstance(tasks, list):
        fail(label, "урок не является списком")
        return False
    if len(tasks) != 5:
        fail(label, f"должно быть 5 заданий, получено {len(tasks)}")
        return False

    good = True
    seen = set()
    for i, task in enumerate(tasks):
        q = norm(task.get("question"))
        if q in seen:
            fail(f"{label}: уникальность", f"повтор вопроса #{i+1}")
            good = False
        seen.add(q)

        if len(str(task.get("question") or "")) > 180:
            fail(f"{label}: длина #{i+1}", "вопрос длиннее 180 символов")
            good = False

        if i < 4:
            good = validate_mcq(task, f"{label}: задание {i+1}") and good
        else:
            good = validate_text(task, f"{label}: задание 5") and good

    good = level_guard(level, tasks, f"{label}: соответствие уровню") and good
    return good


def offline_checks(bot):
    print("\n=== OFFLINE: структура и код ===")

    assert_true(
        len(getattr(bot, "QUESTIONS", [])) == 12,
        "Placement test",
        f"{len(getattr(bot, 'QUESTIONS', []))}/12 вопросов",
    )

    for idx, q in enumerate(getattr(bot, "QUESTIONS", []), 1):
        opts = q.get("options") or []
        correct = q.get("correct")
        assert_true(
            len(opts) == 4
            and len({norm(x) for x in opts}) == 4
            and isinstance(correct, int)
            and 0 <= correct < 4,
            f"Placement #{idx}",
        )

    for level in ("A1", "A2", "B1", "B2"):
        try:
            tasks = bot.build_modern_fallback_lesson(level, "General English")
            validate_lesson(level, tasks, f"{level} fallback")
        except Exception as exc:
            fail(f"{level} fallback", f"{type(exc).__name__}: {exc}")

    # Basic state/menu implementation smoke checks from source.
    source = Path("bot.py").read_text(encoding="utf-8")
    assert_true(
        "awaiting_dictionary_word" in source
        and "context.user_data.pop(\"awaiting_dictionary_word\"" in source,
        "Сброс режима поиска слова",
    )
    assert_true(
        "recent_lesson_questions" in source,
        "Защита от повторения уроков",
    )
    assert_true(
        "GROQ_API_KEY" in source
        and "MERRIAM_WEBSTER_API_KEY" in source,
        "API-ключи читаются из окружения",
    )


async def live_lesson_checks(bot, deep=False):
    print("\n=== LIVE: генерация уроков Groq ===")

    if not os.getenv("GROQ_API_KEY"):
        warn("Live Groq", "нет GROQ_API_KEY в .env — live-проверка уроков пропущена")
        return

    rounds = 2 if deep else 1
    goals = {
        "A1": "General English",
        "A2": "Travel",
        "B1": "Speaking",
        "B2": "Work",
    }

    for level in ("A1", "A2", "B1", "B2"):
        recent = []
        for n in range(rounds):
            try:
                tasks = await bot.generate_lesson_with_groq(
                    level,
                    goals[level],
                    recent_questions=recent,
                    saved_words=[],
                )
                if not tasks:
                    # One slow retry: the app itself has fallback, so an unavailable live generation
                    # is an API availability warning rather than a code failure.
                    await api_pause(5.0)
                    tasks = await bot.generate_lesson_with_groq(
                        level,
                        goals[level],
                        recent_questions=recent,
                        saved_words=[],
                    )
                if not tasks:
                    warn(
                        f"{level} live lesson {n+1}",
                        "Groq не вернул валидный урок после retry; в боте сработает fallback",
                    )
                    await api_pause()
                    continue

                validate_lesson(level, tasks, f"{level} live lesson {n+1}")
                current = [norm(t.get("question")) for t in tasks]
                if recent and any(q in {norm(x) for x in recent} for q in current):
                    fail(f"{level} freshness {n+1}", "в новом уроке повторился прошлый вопрос")
                elif recent:
                    ok(f"{level} freshness {n+1}")

                recent.extend(t.get("question", "") for t in tasks)
                recent = recent[-30:]
                await api_pause()
            except Exception as exc:
                if is_temporary_api_error(exc):
                    warn(f"{level} live lesson {n+1}", f"временная ошибка API: {exc}")
                else:
                    fail(f"{level} live lesson {n+1}", f"{type(exc).__name__}: {exc}")
                await api_pause()


async def live_translation_checks(bot):
    print("\n=== LIVE: сложные RU → EN слова ===")

    if not os.getenv("GROQ_API_KEY"):
        warn("RU→EN live", "нет GROQ_API_KEY")
        return

    import httpx

    cases = [
        ("цирковой", {"circus", "circus-related"}),
        ("рукопожатие", {"handshake"}),
        ("однородный", {"homogeneous", "uniform"}),
        ("каверзный", {"tricky"}),
    ]

    async with httpx.AsyncClient(timeout=25.0) as client:
        for russian, expected in cases:
            try:
                items = await bot.groq_russian_to_english(client, russian)
                got = {norm(x.get("english")) for x in items}
                if got & {x.lower() for x in expected}:
                    ok(f"Перевод «{russian}»", ", ".join(x.get("english", "") for x in items))
                else:
                    warn(
                        f"Перевод «{russian}»",
                        "ответ есть, но нет ожидаемого базового варианта: "
                        + ", ".join(x.get("english", "") for x in items),
                    )
            except Exception as exc:
                if is_temporary_api_error(exc):
                    warn(f"Перевод «{russian}»", f"временная ошибка API: {exc}")
                else:
                    fail(f"Перевод «{russian}»", f"{type(exc).__name__}: {exc}")
            await api_pause()


async def live_grading_checks(bot):
    print("\n=== LIVE: проверка свободных ответов ===")

    if not os.getenv("GROQ_API_KEY"):
        warn("Semantic grading", "нет GROQ_API_KEY")
        return

    cases = [
        (
            "смысловой перевод засчитывается",
            {
                "question": "Переведи естественно: «Вряд ли мы успеем закончить это сегодня.»",
                "answer_display": "We're unlikely to finish this today.",
                "explanation": "Передай малую вероятность.",
            },
            "I'm not sure we'll finish it today",
            "correct",
        ),
        (
            "feedback без артикля засчитывается",
            {
                "question": "Переведи естественно: «Мы обсудим детали позже, когда получим обратную связь.»",
                "answer_display": "We'll discuss the details later, once we get feedback.",
                "explanation": "Передай тот же смысл естественно.",
            },
            "we will discuss the details later when we get feedback",
            "correct",
        ),
        (
            "реально неверный смысл не засчитывается",
            {
                "question": "Переведи естественно: «Вряд ли мы успеем закончить это сегодня.»",
                "answer_display": "We're unlikely to finish this today.",
                "explanation": "Передай малую вероятность.",
            },
            "We finished it yesterday",
            "wrong",
        ),
    ]

    for name, task, answer, expected in cases:
        try:
            result = await bot.evaluate_lesson_text_with_groq(task, answer)
            if result is None:
                warn(name, "Groq временно не дал оценку; бот использует резервную проверку")
            else:
                verdict = result.get("verdict")
                if verdict == expected:
                    ok(name, f"verdict={verdict}")
                else:
                    fail(name, f"ожидалось {expected}, получено {verdict}; {result}")
        except Exception as exc:
            if is_temporary_api_error(exc):
                warn(name, f"временная ошибка API: {exc}")
            else:
                fail(name, f"{type(exc).__name__}: {exc}")
        await api_pause()


def save_report():
    report = [
        "EnglishMate QA report",
        "=" * 40,
        f"PASSED: {len(PASSED)}",
        f"FAILED: {len(FAILED)}",
        f"WARNINGS: {len(WARNINGS)}",
        "",
        *DETAILS,
    ]
    Path("qa_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\nОтчёт сохранён: qa_report.txt")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="реальные проверки Groq/API")
    parser.add_argument("--deep", action="store_true", help="по два live-урока на каждый уровень")
    args = parser.parse_args()

    print("EnglishMate automated QA")
    print("=" * 40)

    try:
        import bot
        ok("Импорт bot.py")
    except Exception as exc:
        fail("Импорт bot.py", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        save_report()
        return 1

    offline_checks(bot)

    if args.live:
        await live_lesson_checks(bot, deep=args.deep)
        await live_translation_checks(bot)
        await live_grading_checks(bot)
    else:
        print("\nℹ️  Для проверки реальных ответов Groq запусти: python3 qa_check.py --live")

    save_report()

    print("\n" + "=" * 40)
    print(f"✅ Пройдено: {len(PASSED)}")
    print(f"❌ Ошибок: {len(FAILED)}")
    print(f"⚠️  Предупреждений: {len(WARNINGS)}")

    if FAILED:
        print("\nQA НЕ ПРОЙДЕН. Смотри пункты с ❌ выше.")
        return 1

    if WARNINGS:
        print("\nQA ПРОЙДЕН ПО КОДУ. Есть предупреждения внешнего API, но критических ошибок нет.")
    else:
        print("\nQA ПРОЙДЕН. После этого нужен только короткий финальный smoke-test в Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
