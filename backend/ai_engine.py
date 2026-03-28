import os
import re
import subprocess

from backend.env_utils import load_project_env

try:
    import requests  # type: ignore
except Exception:
    requests = None

load_project_env()

# name of the ollama model to use (must be installed locally or accessible via ollama)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "180"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "100"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.4"))
MIN_BODY_WORDS = int(os.getenv("MIN_COLD_EMAIL_WORDS", "95"))
MAX_BODY_WORDS = int(os.getenv("MAX_COLD_EMAIL_WORDS", "150"))
DEFAULT_SENDER_NAME = os.getenv("SENDER_NAME", os.getenv("EMAIL_ADDRESS", "Your Name").split("@")[0] or "Your Name")
DEFAULT_COMPANY_NAME = os.getenv("AGENCY_NAME", "Your Company Name")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences that may appear in CLI output."""
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text or "")


def _ascii_safe(text: str) -> str:
    """Normalize generated text so SMTP headers/body stay portable."""
    return (text or "").encode("ascii", "ignore").decode("ascii").strip()


def _lead_value(lead: dict, key: str, default: str) -> str:
    value = str(lead.get(key, "") or "").strip()
    return value if value else default


def _build_prompt(lead: dict) -> str:
    name        = _lead_value(lead, "name",     "there")
    company     = _lead_value(lead, "company",  "your business")
    solution    = _lead_value(lead, "niche",    "digital growth")
    industry    = _lead_value(lead, "industry", "your industry")
    sender_name = DEFAULT_SENDER_NAME
    agency_name = DEFAULT_COMPANY_NAME

    return (
        f"Write a cold email using EXACTLY this structure. "
        f"Replace the placeholders with the values provided. Output ONLY the final email.\n\n"
        f"VALUES:\n"
        f"FirstName = {name}\n"
        f"Industry = {industry}\n"
        f"AgencyName = {agency_name}\n"
        f"Service = {solution}\n"
        f"CompanyName = {company}\n"
        f"SenderName = {sender_name}\n\n"
        f"TEMPLATE (copy exactly, only replace values):\n\n"
        f"Subject: {solution} growth strategy for {company}\n\n"
        f"Hi {name},\n\n"
        f"As a professional in the {industry} sector, you know how important it is to stay ahead of competitors and maintain steady growth.\n\n"
        f"With competition increasing and buyer behavior shifting online, many {industry} businesses find it difficult to generate consistent qualified leads and maintain visibility.\n\n"
        f"At {agency_name}, we help {industry} businesses improve online growth through {solution} tailored to their market and customer intent.\n\n"
        f"- Increased qualified website traffic and online visibility\n"
        f"- Improved lead generation from digital channels\n"
        f"- Stronger brand authority in the local market\n\n"
        f"Would you be open to a quick 15-minute call to explore how {solution} can help {company} attract more clients?\n\n"
        f"Best regards,\n"
        f"{sender_name}\n\n"
        f"P.S. Many businesses in {industry} are already using {solution} to capture more demand. This is a strong time to stay ahead.\n\n"
        f"STRICT RULES:\n"
        f"1. Start with Subject: line\n"
        f"2. Only ONE greeting: Hi {name}, — never add Dear\n"
        f"3. Each bullet on its OWN line starting with '- '\n"
        f"4. Signature = two lines: 'Best regards,' then '{sender_name}' on next line\n"
        f"5. P.S. line is mandatory\n"
        f"6. One blank line between every paragraph\n"
        f"7. Plain text only — no HTML, no markdown, no emoji\n"
        f"8. Do NOT change the structure — only personalise the content\n"
        f"9. Keep body under 150 words"
    )




def _generate_with_ollama(prompt: str) -> tuple[str, str]:
    """Try Ollama HTTP API first, then CLI fallbacks for compatibility."""
    errors = []

    if requests is not None:
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_predict": OLLAMA_NUM_PREDICT,
                        "temperature": OLLAMA_TEMPERATURE,
                    },
                },
                timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            generated_text = _strip_ansi(payload.get("response", "")).strip()
            if generated_text:
                return generated_text, ""
            errors.append("ollama http: empty response")
        except Exception as exc:
            errors.append(f"ollama http: {exc}")

    commands = [
        ["ollama", "run", OLLAMA_MODEL, prompt],
        ["ollama", "generate", OLLAMA_MODEL, "--prompt", prompt],
    ]

    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return _strip_ansi(proc.stdout).strip(), ""
        except FileNotFoundError as exc:
            errors.append(f"{' '.join(cmd[:3])}: {exc}")  # type: ignore
            break
        except subprocess.CalledProcessError as exc:
            stderr = _strip_ansi(exc.stderr).strip()
            errors.append(f"{' '.join(cmd[:3])}: {stderr or str(exc)}")  # type: ignore

    return "", " | ".join(errors)


def _format_email(text: str, sender_name: str) -> str:
    """
    Post-processor: cleans, restructures and normalises every email.
    Rules applied:
    - Remove standalone brand/company line at top
    - Keep only one greeting (Hi ...,) — drop Dear
    - Vertical bullet points, never inline
    - Blank line between every paragraph
    - Two-line signature: Best regards,\\n{name}
    - Remove incomplete footer/unsubscribe text
    - P.S. on its own paragraph
    """
    if not text:
        return text

    lines = text.splitlines()

    # ── 1. Separate subject from body ──────────────────────────────────────
    subject_line = ""
    body_lines = lines
    if lines and lines[0].strip().lower().startswith("subject:"):
        subject_line = lines[0].strip()
        body_lines = lines[1:]

    # ── 2. Remove leading blank lines ──────────────────────────────────────
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]

    # ── 3. Remove standalone brand/company line at top ─────────────────────
    agency = DEFAULT_COMPANY_NAME.strip().lower()
    if body_lines and body_lines[0].strip().lower() == agency:
        body_lines = body_lines[1:]
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]

    # ── 4. Remove duplicate greeting — keep only "Hi ..., " ────────────────
    greeting_seen = False
    cleaned = []
    for line in body_lines:
        s = line.strip().lower()
        is_hi   = s.startswith("hi ") and s.endswith(",")
        is_dear = s.startswith("dear ") and s.endswith(",")
        if is_hi or is_dear:
            if not greeting_seen:
                if is_dear:
                    name_part = line.strip()[5:].rstrip(",").strip()
                    cleaned.append(f"Hi {name_part},")
                else:
                    cleaned.append(line.strip())
                greeting_seen = True
            # skip any subsequent greeting line
        else:
            cleaned.append(line)
    body_lines = cleaned

    # ── 5. Fix inline bullets ───────────────────────────────────────────────
    expanded = []
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("- ") and re.search(r"\s-\s", stripped[2:]):
            parts = re.split(r"\s+-\s+", stripped)
            for i, part in enumerate(parts):
                part = part.strip().lstrip("- ").strip()
                if part:
                    expanded.append(f"- {part}")
        else:
            expanded.append(line)
    body_lines = expanded

    # ── 6. Rejoin and fix signature on one line ────────────────────────────
    rejoined = "\n".join(body_lines)
    rejoined = re.sub(
        r"(Best regards),\s+([A-Za-z][^\n]+)",
        r"\1,\n\2",
        rejoined,
        flags=re.IGNORECASE,
    )

    # ── 7. Remove incomplete footer / unsubscribe text ─────────────────────
    rejoined = re.sub(
        r"\n+You received this email because.*$", "",
        rejoined, flags=re.IGNORECASE | re.DOTALL
    )
    rejoined = re.sub(
        r"\n+To unsubscribe.*$", "",
        rejoined, flags=re.IGNORECASE | re.DOTALL
    )

    # ── 8. Ensure blank line before bullets ────────────────────────────────
    rejoined = re.sub(r"([^\n])\n(- )", r"\1\n\n\2", rejoined)

    # ── 9. Ensure blank line after bullet block ────────────────────────────
    rejoined = re.sub(r"(^- [^\n]+)(\n)([^-\n])", r"\1\n\n\3", rejoined, flags=re.MULTILINE)

    # ── 10. Ensure blank line before "Best regards" ────────────────────────
    rejoined = re.sub(r"([^\n])\n(Best regards)", r"\1\n\n\2", rejoined, flags=re.IGNORECASE)

    # ── 11. Ensure blank line before P.S. ─────────────────────────────────
    rejoined = re.sub(r"([^\n])\n(P\.S\.)", r"\1\n\n\2", rejoined, flags=re.IGNORECASE)

    # ── 12. Collapse 3+ blank lines → 2 ───────────────────────────────────
    rejoined = re.sub(r"\n{3,}", "\n\n", rejoined)

    # ── 13. Reassemble with subject ───────────────────────────────────────
    final = f"{subject_line}\n\n{rejoined.strip()}" if subject_line else rejoined.strip()
    return final.strip()



def _normalize_email(raw_text: str, lead: dict) -> str:
    name = _lead_value(lead, "name", "there")
    solution = _lead_value(lead, "niche", "digital growth")
    industry = _lead_value(lead, "industry", "your industry")
    lines = [line.rstrip() for line in (raw_text or "").splitlines()]
    lines = [line for line in lines if line.strip()]

    if not lines:
        return _detailed_fallback(lead)

    first = _ascii_safe(lines[0].strip())
    if first.lower().startswith("subject:"):
        subject = first
        body_lines = lines[1:]  # type: ignore
    else:
        subject = f"Subject: Growth strategy opportunity for {solution} in {industry}"
        body_lines = lines

    if not body_lines:
        return _detailed_fallback(lead)

    body = _ascii_safe("\n".join(body_lines).strip())
    body_word_count = _word_count(body)
    if body_word_count < MIN_BODY_WORDS or body_word_count > MAX_BODY_WORDS:
        return _detailed_fallback(lead)

    final_text = _ascii_safe(f"{subject}\n{body}")
    if not _solution_alignment_ok(final_text, solution):
        return _detailed_fallback(lead)
    if not _structure_alignment_ok(final_text, name, industry):
        return _detailed_fallback(lead)

    return _format_email(final_text, DEFAULT_SENDER_NAME)


def _detailed_fallback(lead: dict) -> str:
    """Guaranteed-format fallback — matches the exact approved template."""
    name        = _lead_value(lead, "name",     "there")
    company     = _lead_value(lead, "company",  "your business")
    solution    = _lead_value(lead, "niche",    "digital growth")
    industry    = _lead_value(lead, "industry", "your industry")
    sender_name = DEFAULT_SENDER_NAME
    agency_name = DEFAULT_COMPANY_NAME

    email = (
        f"Subject: {solution} growth strategy for {company}\n"
        f"\n"
        f"Hi {name},\n"
        f"\n"
        f"As a professional in the {industry} sector, you know how important it is to stay ahead of competitors and maintain steady growth.\n"
        f"\n"
        f"With competition increasing and buyer behavior shifting online, many {industry} businesses find it difficult to generate consistent qualified leads and maintain visibility.\n"
        f"\n"
        f"At {agency_name}, we help {industry} businesses improve online growth through {solution} tailored to their market and customer intent.\n"
        f"\n"
        f"- Increased qualified website traffic and online visibility\n"
        f"- Improved lead generation from digital channels\n"
        f"- Stronger brand authority in the local market\n"
        f"\n"
        f"Would you be open to a quick 15-minute call to explore how {solution} can help {company} attract more clients?\n"
        f"\n"
        f"Best regards,\n"
        f"{sender_name}\n"
        f"\n"
        f"P.S. Many businesses in {industry} are already using {solution} to capture more demand. This is a strong time to stay ahead."
    )

    return _ascii_safe(email)




def _solution_alignment_ok(email_text: str, solution: str) -> bool:
    expected = (solution or "").strip().lower()
    if not expected:
        return True

    lines = email_text.splitlines()
    if not lines:
        return False

    subject = lines[0].lower()
    body = "\n".join(lines[1:]).lower()  # type: ignore
    return expected in subject and expected in body


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def _structure_alignment_ok(email_text: str, name: str, industry: str) -> bool:
    lines = [line.strip().lower() for line in email_text.splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    lowered = "\n".join(lines)
    if f"hi {name.lower()}," not in lowered:
        return False
    if "dear" in lowered:
        return False  # reject if Dear slipped in
    if "best regards" not in lowered:
        return False
    if "15-minute call" not in lowered:
        return False
    if "p.s." not in lowered:
        return False
    bullet_lines = [l for l in lines if l.startswith("- ")]
    return len(bullet_lines) >= 3




def _log_result(result: str, error: str) -> None:
    try:
        with open("ai_generation.log", "a", encoding="utf-8") as logf:
            if error:
                logf.write(f"[OLLAMA_ERROR] {error}\n")
            logf.write(result + "\n---\n")
    except Exception:
        pass


def generate_cold_email(lead: dict) -> str:
    """Generate a detailed cold email using Ollama with resilient fallback."""
    prompt = _build_prompt(lead)
    raw_result, error = _generate_with_ollama(prompt)
    result = _normalize_email(raw_result, lead) if raw_result else _detailed_fallback(lead)
    _log_result(result, error)
    return result
