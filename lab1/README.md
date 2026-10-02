# EnglishMate — Lab 1

EnglishMate is a Telegram bot for an initial English level assessment and creation of a basic learning profile.

## Features in v1

- `/start` — starts the placement test
- 12 multiple-choice questions with Telegram inline buttons
- approximate starting level: A1, A2, B1 or B2
- learning goal selection: General English, Speaking, Travel or Work
- SQLite storage for the user's result and goal
- `/progress` — shows the saved profile
- `/help` — shows available commands

> The 12-question test is only an initial level estimate and is not a full CEFR assessment.

## Requirements

- Python 3.10+
- Telegram bot token created with BotFather

## Installation

### 1. Create a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create `.env`

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Open `.env` and replace `your_bot_token_here` with the real BotFather token:

```text
TELEGRAM_BOT_TOKEN=YOUR_REAL_TOKEN
```

Never commit `.env` or the real token to GitHub.

### 4. Run the bot

```bash
python bot.py
```

If the bot starts successfully, the terminal will show:

```text
EnglishMate запущен. Для остановки нажми Ctrl+C.
```

Then open the bot in Telegram and send `/start`.

## Project files

- `bot.py` — Telegram bot logic and placement test
- `database.py` — SQLite storage
- `requirements.txt` — Python dependencies
- `.env.example` — environment variable template
- `englishmate.db` — created automatically on first run and should not be committed
