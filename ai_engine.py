import os
import re
import subprocess

try:
    import requests
except Exception:
    requests = None

# name of the ollama model to use (must be installed locally or accessible via ollama)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "180"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "280"))
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
    name = _lead_value(lead, "name", "there")
    company = _lead_value(lead, "company", "your business")
    solution = _lead_value(lead, "niche", "digital growth")
    industry = _lead_value(lead, "industry", "your industry")
    sender_name = DEFAULT_SENDER_NAME
    agency_name = DEFAULT_COMPANY_NAME

    return (
        "Write one professional cold email using this exact structure.\n"
        f"Recipient Name: {name}\n"
        f"Client Company: {company}\n"
        f"Solution We Provide: {solution}\n"
        f"Industry: {industry}\n\n"
        "Structure requirements:\n"
        "1) First line must be exactly in this format: Subject: <text>\n"
        "2) Body line 1: Hi <Client Name>,\n"
        "3) Body line 2: Dear <Client Name>,\n"
        "4) Respectful opening recognizing their experience in the industry.\n"
        "5) Problem context about current competition and changing buyer behavior.\n"
        f"6) Solution intro using {agency_name} and the exact service phrase '{solution}'.\n"
        "7) Add 2-3 measurable benefits as dash bullets.\n"
        "8) Add CTA inviting a 15-minute call.\n"
        f"9) Closing exactly as:\nBest regards,\n{sender_name}\n"
        "10) Add one optional PS line about urgency/opportunity.\n"
        "11) Keep body under 150 words (target 120-145 words).\n"
        "12) Output plain text only, no markdown tables, no emoji.\n"
        f"13) Must include the exact phrase '{solution}' at least once in subject and once in body.\n"
        "14) Do not suggest any different primary service."
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
            errors.append(f"{' '.join(cmd[:3])}: {exc}")
            break
        except subprocess.CalledProcessError as exc:
            stderr = _strip_ansi(exc.stderr).strip()
            errors.append(f"{' '.join(cmd[:3])}: {stderr or str(exc)}")

    return "", " | ".join(errors)


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
        body_lines = lines[1:]
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

    return final_text


def _detailed_fallback(lead: dict) -> str:
    """Template fallback used when Ollama output is invalid."""
    name = _lead_value(lead, "name", "there")
    company = _lead_value(lead, "company", "your business")
    solution = _lead_value(lead, "niche", "growth")
    industry = _lead_value(lead, "industry", "your industry")
    sender_name = DEFAULT_SENDER_NAME
    agency_name = DEFAULT_COMPANY_NAME

    fallback = (
        f"Subject: {solution} strategy to grow {industry} lead flow\n"
        f"Hi {name},\n\n"
        f"Dear {name},\n"
        f"As a professional in the {industry} sector, you know how important it is to stay ahead of competitors and maintain steady growth.\n\n"
        f"With competition increasing and buyer behavior shifting online, many {industry} businesses find it difficult to generate consistent qualified leads and maintain visibility.\n\n"
        f"At {agency_name}, we help {industry} businesses improve online growth through {solution} tailored to their market and customer intent.\n\n"
        "- Increased qualified website traffic and online visibility\n"
        "- Improved lead generation from digital channels\n"
        "- Stronger brand authority in the local market\n\n"
        f"Would you be open to a quick 15-minute call to explore how {solution} can help {company} attract more clients?\n\n"
        f"Best regards,\n{sender_name}\n\n"
        f"P.S. Many businesses in {industry} are already using {solution} to capture more demand. This is a strong time to stay ahead."
    )
    body = "\n".join(fallback.splitlines()[1:])
    if _word_count(body) > MAX_BODY_WORDS:
        trimmed_ps = (
            f"Subject: {solution} strategy to grow {industry} lead flow\n"
            f"Hi {name},\n\n"
            f"Dear {name},\n"
            f"As a professional in the {industry} sector, you know steady growth depends on staying visible while competitors move fast.\n\n"
            f"Many {industry} businesses now struggle with rising competition, shifting buyer behavior, and inconsistent digital lead flow.\n\n"
            f"At {agency_name}, we help businesses like {company} grow through {solution} with focused execution.\n\n"
            "- Increased qualified traffic and visibility\n"
            "- Better lead generation from digital channels\n"
            "- Stronger brand authority in your local market\n\n"
            f"Would you be open to a quick 15-minute call to explore how {solution} can help {company} grow?\n\n"
            f"Best regards,\n{sender_name}"
        )
        return _ascii_safe(trimmed_ps)
    return _ascii_safe(fallback)


def _solution_alignment_ok(email_text: str, solution: str) -> bool:
    expected = (solution or "").strip().lower()
    if not expected:
        return True

    lines = email_text.splitlines()
    if not lines:
        return False

    subject = lines[0].lower()
    body = "\n".join(lines[1:]).lower()
    return expected in subject and expected in body


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def _structure_alignment_ok(email_text: str, name: str, industry: str) -> bool:
    lines = [line.strip().lower() for line in email_text.splitlines() if line.strip()]
    if len(lines) < 6:
        return False

    lowered = "\n".join(lines)
    expected_hi = f"hi {name.lower()}".strip()
    expected_dear = f"dear {name.lower()}".strip()
    if expected_hi not in lowered:
        return False
    if expected_dear not in lowered:
        return False
    if "best regards" not in lowered:
        return False
    if "15-minute call" not in lowered:
        return False
    if industry.lower() not in lowered:
        return False

    bullet_lines = [line for line in lines if line.startswith("- ")]
    return len(bullet_lines) >= 2


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
