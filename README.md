# AI-Powered Email Automation for Agencies

This project provides an AI-driven email automation system tailored for agencies. Given a list of clients (email, name, niche, phone, industry, etc.), the system generates **unique cold emails** using an Ollama language model and dispatches them automatically. It ensures that even clients in the same niche or industry receive distinct messages.

---

## 📌 Goals

1. **Automate cold outreach** at scale with personalization and variety.
2. **Leverage an Ollama LLM** to craft context-aware, niche-specific emails.
3. Provide a **modern web interface** for uploading leads and managing campaigns.
4. Build extensible backend in Python (mandatory) and a contemporary frontend.

---

## 🧩 High-Level Architecture

```
Frontend (React/Next.js)
        ↓  REST/GraphQL API
Backend (Python + FastAPI/Django)
        ↓
Ollama Model  <–>  Email Generator
        ↓
SMTP / Email Service (sendgrid, mailgun, etc.)
        ↓
Leads Database  /  Campaign Logs  /  Analytics
```

- **Backend**: Python with FastAPI (lightweight, async-friendly) or Django REST Framework.
- **Frontend**: React or Next.js with Tailwind CSS for styling. It can be a single-page app or server-side rendered.
- **AI Engine**: Use Ollama CLI/HTTP; prompts instruct the model to produce unique cold emails given client attributes.
- **Email transport**: `smtplib` for direct SMTP or a transactional service (recommended for tracking & deliverability).
- **Storage**: SQLite/PostgreSQL for leads, campaign state and logs.
- **Background tasks**: Celery or FastAPI's `BackgroundTasks` to queue/send emails with rate limits.

---

## 🚀 Implementation Plan

1. **Project scaffolding**
   - Initialize Python project with `venv`, dependencies (`fastapi`, `uvicorn`, `pydantic`, `requests` for Ollama, etc.).
   - Create frontend repo (e.g. `frontend/`) using Next.js `create-next-app`.
   - Add Dockerfiles and `docker-compose.yml` for local development.

2. **Data model & ingestion**
   - Define `Lead` schema: `name`, `email`, `niche`, `industry`, `phone`, `company`, etc.
   - Endpoint to upload CSV or JSON list; validate inputs.
   - Persist leads in the database.

3. **Prompt engineering**
   - Design prompt template that instructs Ollama to:
     ```text
     "Compose a cold outreach email for a [niche] business in the [industry] industry. Use the recipient's name if available. The message must be unique in structure, avoid repeating phrases from other emails, and be professional."
     ```
   - Include randomness variables (e.g., different openings, closing, value propositions).
   - Optionally store previous prompts/responses to enforce uniqueness.

4. **AI integration module**
   - Create `ai_engine.py` to call Ollama (HTTP or CLI) with prepared prompt & parse output.
   - Cache or log generated text to avoid duplicates.

5. **Email generation & sending**
   - Combine generated content with optional template.
   - Use `smtp_sender.py` or a service SDK; include retry logic and delay management (`DELAY_BETWEEN_EMAILS`).
   - Record sent status, timestamps, and any errors.

6. **Campaign management**
   - Endpoint to start/stop a campaign, pause, resume, and view progress.
   - Dashboard on frontend showing statistics: sent, failed, opens/clicks (if tracking enabled).

7. **Frontend features**
   - Upload leads form (drag & drop CSV).
   - Campaign configuration (sender email, rate limit, template overrides).
   - Real‑time status updates via WebSocket or periodic polling.
   - View/edit template and prompt used for AI.

8. **Tracking & analytics** (optional but powerful)
   - Embed 1×1 pixel or link shortener to capture opens/clicks.
   - Store metrics per lead and aggregate by niche/industry.
   - Provide A/B test support to try alternate subject lines or messages.

9. **Security & Deployment**
   - Store secrets in environment variables (`.env` or Vault).
   - Use OAuth/API keys for Ollama if required.
   - Deploy backend with Gunicorn/Uvicorn behind NGINX, frontend on Vercel/Netlify.
   - Containerize for reproducible builds; use CI pipeline for tests.

10. **Extras & future expansions**
    - Rate‑limiting & retry queue with exponential backoff.
    - Support for multiple sender accounts and domains.
    - Model fine‑tuning or prompt refinement using campaign outcomes.
    - Multi-language support with language detection.
    - Integration with CRM tools (HubSpot, Salesforce) via webhooks.
    - User authentication and multi‑tenant architecture for agencies.

---

## ✅ Suggested Additional Features for Effectiveness

- **Email deliverability hooks** (bounces, spam complaints).
- **Throttling and scheduling** per client time zone.
- **Template versioning** and history.
- **Built‑in unsubscribe/opt‑out handling**.
- **Dashboard charts** (subject performance, open rates, response rates).
- **CLI utility** for power users who prefer scripts.
- **Unit/Integration tests** with mocked Ollama responses.

---

## 💡 Frontend & Backend Stack Recommendations

| Component        | Recommendation                         | Notes                          |
|------------------|----------------------------------------|-------------------------------|
| Frontend         | React / Next.js + Tailwind CSS         | SSR & API routes optional      |
| Backend          | Python + FastAPI                       | Async, lightweight             |
| AI Model         | Ollama (local or remote)               | Use `requests` or CLI wrapper  |
| Database         | PostgreSQL (SQLite for dev)            | Use SQLAlchemy / Tortoise ORM  |
| Background tasks | Celery / Redis or RQ                   | For rate‑limit & reliability   |
| Deployment       | Docker + Kubernetes / Heroku           | CI/CD via GitHub Actions       |

---

## 🏁 Getting Started (Development)

1. Clone repo and create Python virtual environment.
2. Install backend dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure `.env` with SMTP credentials, Ollama endpoint, DB URL, etc.
4. Run migrations (`alembic` or `django manage.py migrate`).
5. Start backend server:
   ```bash
   uvicorn app.main:app --reload
   ```
6. Navigate to `frontend/`, install npm packages, then `npm run dev`.

Refer to each folder's README for more details.

---

## 📄 Existing Files

This repository currently contains:

- `campaign.py`, `personalization.py`, `smtp_sender.py` – basic template-based mailing
- `leads.csv` sample file
- `templates/email_template.txt` with placeholders

The next steps will expand these modules with AI and web interfaces as outlined above.

---

If you have questions or want help building any component, feel free to ask!