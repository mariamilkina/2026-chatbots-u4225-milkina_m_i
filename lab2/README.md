# EnglishMate — Lab 2

Lab 2 extends the EnglishMate bot from Lab 1 with an external data source:
Free Dictionary API.

## New commands

- `/word <word>` — looks up an English word in Dictionary API.
- `/mywords` — shows the latest 10 words saved by the current Telegram user.

A dictionary result can include:
- word;
- phonetic transcription;
- part of speech;
- definition;
- example;
- up to 3 synonyms.

The **Save word** inline button stores the word in SQLite.

## API

`https://api.dictionaryapi.dev/api/v2/entries/en/<word>`

No API key is required.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
# Put the real BotFather token into .env
python3 bot.py
```

The existing Lab 1 functionality (`/start`, `/lesson`, `/progress`, `/help`)
remains available.
