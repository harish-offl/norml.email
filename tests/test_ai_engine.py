import subprocess
from ai_engine import generate_cold_email


def test_generate_cold_email_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ai_engine.requests", None)
    monkeypatch.setattr("ai_engine.MIN_BODY_WORDS", 50)
    monkeypatch.setattr("ai_engine.MAX_BODY_WORDS", 250)
    monkeypatch.setattr("ai_engine.DEFAULT_SENDER_NAME", "Rviswa")
    monkeypatch.setattr("ai_engine.DEFAULT_COMPANY_NAME", "GrowthPilot")

    class Dummy:
        stdout = (
            "Subject: Better SEO Services lead flow for construction brands\n"
            "Hi Ram,\n\n"
            "Dear Ram,\n"
            "As a professional in the Construction sector, you know how important it is to stay ahead of competitors and maintain steady growth.\n\n"
            "With competition increasing and buyer behavior changing online, many firms struggle to generate consistent qualified leads.\n\n"
            "At GrowthPilot, we help Construction businesses grow through SEO Services tailored to market demand.\n\n"
            "- Increased qualified website traffic\n"
            "- Improved lead generation from digital channels\n"
            "- Stronger brand authority in the local market\n\n"
            "Would you be open to a quick 15-minute call to explore growth opportunities?\n\n"
            "Best regards,\nRviswa\n\n"
            "P.S. Many Construction businesses are already using SEO Services to capture demand."
        )
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Dummy())

    lead = {"name": "Ram", "niche": "SEO Services", "industry": "Construction", "company": "Ram Constructions"}
    result = generate_cold_email(lead)
    assert "Subject" in result
    assert "Hi Ram" in result
    assert "SEO Services" in result
    assert "Dear Ram" in result
    assert "15-minute call" in result
    assert "Best regards" in result

    content = (tmp_path / "ai_generation.log").read_text(encoding="utf-8")
    assert "Subject: Better SEO Services lead flow for construction brands" in content


def test_generate_cold_email_uses_detailed_fallback_when_ollama_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ai_engine.requests", None)
    monkeypatch.setattr("ai_engine.DEFAULT_SENDER_NAME", "Rviswa")
    monkeypatch.setattr("ai_engine.DEFAULT_COMPANY_NAME", "GrowthPilot")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=args[0], stderr="command failed")

    monkeypatch.setattr("subprocess.run", fail)

    lead = {"name": "Annamalai", "niche": "App Development", "industry": "IT Services", "company": "TechNova"}
    result = generate_cold_email(lead)

    assert result.startswith("Subject:")
    assert "Hi Annamalai" in result
    assert "Dear Annamalai" in result
    assert "15-minute call" in result
    assert "Best regards" in result
    assert "We thought you might be interested in ..." not in result
