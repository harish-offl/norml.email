# AI Email Automation (Django + Ollama)

This project uploads client leads, generates personalized cold emails with Ollama, and sends them through SMTP.

It is built with Django + Django REST Framework and includes a simple frontend page for uploading CSV files and starting campaigns.

## Current Features

- Django API for lead ingestion and campaign start.
- CSV upload with header normalization and alias mapping.
- Lead replacement mode on upload to avoid stale recipients.
- Solution-driven email generation (based on `niche` / `interest` / `solution` field).
- Structured cold email format validation.
- Ollama generation via HTTP API first, CLI fallback second.
- Parallel sending with reusable SMTP connections for faster throughput.

## Architecture

- `frontend/` -> static upload/start dashboard.
- `backend/app/main.py` -> Django routes and API views.
- `backend/campaign_runner.py` -> concurrent generation + sending workers.
- `backend/ai_engine.py` -> Ollama prompt + output validation + fallback template.
- `backend/smtp_sender.py` -> SMTP sender with retries and connection reuse.
- `backend/env_utils.py` -> .env loader and project paths.
- `data/leads.db` -> SQLite lead storage (default path; configure via `DATABASE_URL`).

## Project Layout

- `backend/` — Django app code, campaign engine, SMTP + Ollama logic, env loader, templates.
- `frontend/` — static React-in-HTML dashboard for upload/start.
- `tests/` — pytest suites for generation, runner, and campaign start.
- `data/` — sample lead data (`leads.csv`) and SQLite store (`leads.db` by default).
- `.env` — environment configuration (root, gitignored).

## Requirements

- Python 3.12+ (tested with 3.13)
- Ollama installed and running locally
- SMTP credentials (for example Gmail app password)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Create `.env` in project root with values like:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_ADDRESS=your_sender@gmail.com
EMAIL_PASSWORD=your_app_password
DATABASE_URL=data/leads.db

OLLAMA_MODEL=llama3.2:1b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_REQUEST_TIMEOUT_SECONDS=180
OLLAMA_KEEP_ALIVE=30m
OLLAMA_NUM_PREDICT=100
OLLAMA_TEMPERATURE=0.4

MAX_CONCURRENT_EMAILS=2
DELAY_BETWEEN_EMAILS=0
SMTP_MAX_RETRIES=1
SMTP_RETRY_DELAY_SECONDS=1

MIN_COLD_EMAIL_WORDS=95
MAX_COLD_EMAIL_WORDS=150
SENDER_NAME=Your Name
AGENCY_NAME=Your Company Name
```

## Run

Run migrations (from the project root):

```bash
python -m backend.main --migrate
```

Start server:

```bash
python -m backend.main --serve
```

Open:

- `http://127.0.0.1:8000/` (frontend)

Run campaign from CLI (without API):

```bash
python -m backend.main
```

## API Endpoints

- `GET /api/leads/` -> list leads
- `POST /api/leads/` -> create lead
- `POST /api/leads/upload/` -> upload CSV file
- `POST /api/campaign/start/` -> start background campaign

### Upload behavior

`POST /api/leads/upload/` accepts multipart file key: `file`

Optional form flags:

- `replace_existing` (default `true`)
- `require_solution` (default `true`)

If `replace_existing=true`, old leads are deleted before import.

Rows are skipped when:

- email is missing
- solution field is missing while `require_solution=true`

The response includes:

- `created`
- `updated`
- `skipped`
- `ignored_columns`

## Accepted CSV Headers

Headers are normalized and mapped automatically.

Mapped to `name`:

- `name`, `full name`, `client name`

Mapped to `email`:

- `email`, `email address`

Mapped to `phone`:

- `phone`, `phone number`, `mobile`

Mapped to `company`:

- `company`, `company name`

Mapped to `industry`:

- `industry`

Mapped to solution (`niche`):

- `niche`, `interest`, `solution`, `service`, `services`, `offering`

Example CSV:

```csv
Name,Email,Phone,Company,Industry,Interest
Annamalai,annamalaiharish54@gmail.com,9363973591,TechNova Solutions,IT Services,App Development
Ram Viswanath,rviswa60@gmail.com,8056353850,Nair Fashions,Fashion,Social Media Marketing
```

## Cold Email Generation Rules

The generator enforces a structured format and falls back to a safe template if Ollama output is invalid.

Required format:

1. Subject line as first line: `Subject: ...`
2. `Hi <Client Name>,`
3. `Dear <Client Name>,`
4. Respectful opening tied to industry
5. Problem context (competition + buyer behavior)
6. Solution intro using your service phrase
7. 2-3 dash bullet benefits
8. CTA with `15-minute call`
9. Closing with `Best regards,` and sender name
10. Optional PS line

Validation checks:

- Word count range (`MIN_COLD_EMAIL_WORDS` to `MAX_COLD_EMAIL_WORDS`)
- Service phrase present in subject and body
- Required structure elements present

## Performance Tuning

Main throughput controls:

- `MAX_CONCURRENT_EMAILS` -> parallel workers (default recommended: `2`)
- `DELAY_BETWEEN_EMAILS` -> delay after each send per worker
- `OLLAMA_NUM_PREDICT` -> generation length/speed tradeoff

Notes:

- Higher concurrency can reduce total time, but too high can slow Ollama on local hardware.
- SMTP provider limits still apply (Gmail sending limits, throttling, etc.).

## Tests

Run:

```bash
pytest -q tests/test_ai_engine.py
```

## Troubleshooting

- Campaign sends to old/test lead:
  - Re-upload with `replace_existing=true`.
- Upload says `No valid rows found`:
  - Ensure CSV contains `Email` and `Interest`/`Solution`/`Niche` column.
- Ollama output not matching structure:
  - Check `ai_generation.log` for `[OLLAMA_ERROR]` entries.
- Slow generation:
  - Reduce `OLLAMA_NUM_PREDICT`, keep `MAX_CONCURRENT_EMAILS=2`, or switch to a smaller model.

## Security Notes

- Do not commit `.env` with real credentials.
- Use app passwords for SMTP accounts.
- Keep `ai_generation.log` out of version control (already ignored).
