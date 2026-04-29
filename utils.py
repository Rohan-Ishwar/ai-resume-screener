import io
import json
import re
import PyPDF2
import pdfplumber
from docx import Document
from google import genai
from google.genai import types


# ──────────────────────────────────────────────────────────────
# Text Extraction
# ──────────────────────────────────────────────────────────────

def extract_text_from_pdf(file) -> str:
    """Extract text from a PDF file-like object using pdfplumber (fallback: PyPDF2)."""
    text = ""
    try:
        file.seek(0)
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        try:
            file.seek(0)
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        except Exception as e:
            text = f"[Error extracting PDF text: {e}]"
    return text.strip()


def extract_text_from_docx(file) -> str:
    """Extract text from a DOCX file-like object."""
    try:
        file.seek(0)
        doc = Document(io.BytesIO(file.read()))
        return "\n".join(para.text for para in doc.paragraphs).strip()
    except Exception as e:
        return f"[Error extracting DOCX text: {e}]"


def extract_text_from_txt(file) -> str:
    """Extract text from a plain-text file."""
    try:
        file.seek(0)
        return file.read().decode("utf-8", errors="ignore").strip()
    except Exception as e:
        return f"[Error reading text file: {e}]"


# ──────────────────────────────────────────────────────────────
# Gemini AI Analysis
# ──────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """
You are an expert ATS (Applicant Tracking System) and HR analyst.
Carefully compare the RESUME against the JOB DESCRIPTION below and return a structured JSON response.

### RESUME:
{resume}

### JOB DESCRIPTION:
{jd}

### INSTRUCTIONS:
Analyze the match and return ONLY a valid JSON object (no markdown, no extra text) with this exact schema:
{{
  "overall_score": <integer 0-100>,
  "fit_level": "<one of: Strong Fit | Good Fit | Moderate Fit | Weak Fit>",
  "matched_skills": [<list of skills/keywords from JD found in resume>],
  "missing_skills": [<list of required skills/keywords from JD NOT found in resume>],
  "experience_match": "<brief assessment of experience level match>",
  "education_match": "<brief assessment of education/qualification match>",
  "strengths": [<list of 3-5 key strengths of this candidate for this role>],
  "areas_for_improvement": [<list of 3-5 gaps or weaknesses for this role>],
  "overall_feedback": "<2-3 sentence overall summary of the candidate's suitability>",
  "recommendation": "<one of: Strongly Recommend | Recommend | Consider | Do Not Recommend>"
}}

Scoring guide:
- 80-100 → Strong Fit
- 60-79  → Good Fit
- 40-59  → Moderate Fit
- 0-39   → Weak Fit
"""


# Preferred models tried in order — broader list so quota on one cascades to the next
PREFERRED_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-pro",
]


def _get_available_models(client) -> list[str]:
    """Return available models for this API key, sorted by preference."""
    try:
        available = set()
        for m in client.models.list():
            short = m.name.split("/")[-1] if "/" in m.name else m.name
            available.add(short)
        ordered = [m for m in PREFERRED_MODELS if m in available]
        # Append any extras not in our preferred list (future models)
        extras = [m for m in available if m not in PREFERRED_MODELS and "gemini" in m]
        return ordered + extras or list(available)
    except Exception:
        return PREFERRED_MODELS  # fall back to full list if listing fails


def _is_quota_error(err_str: str) -> bool:
    return "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()


def _extract_retry_seconds(err_str: str) -> int | None:
    """Parse 'retry in X seconds' from a quota error message."""
    m = re.search(r"retry[^\d]*([0-9]+(?:\.[0-9]+)?)\s*s", err_str, re.IGNORECASE)
    return int(float(m.group(1))) + 1 if m else None


def _call_model(client, model_name: str, prompt: str) -> tuple[str, str | None]:
    """Call generate_content; try JSON mime type first, plain text as fallback."""
    for use_json_mime in (True, False):
        try:
            cfg = types.GenerateContentConfig(temperature=0.2)
            if use_json_mime:
                cfg = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=cfg,
            )
            return (response.text or "").strip(), None
        except Exception as e:
            err = str(e)
            if _is_quota_error(err):
                return "", err   # quota error — no point retrying with plain text
            if not use_json_mime:
                return "", err   # both attempts failed for a non-quota reason
    return "", "Unknown error"


def analyze_resume(resume_text: str, jd_text: str, api_key: str) -> tuple[dict | None, str | None]:
    """Send resume + JD to Gemini and return (result_dict, error_message).

    Tries every available model in preference order, skipping quota-exhausted ones.
    On success  → (dict, None)
    On failure  → (None, "human-readable error")
    """
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return None, f"Could not initialise Gemini client: {e}"

    models = _get_available_models(client)

    prompt = ANALYSIS_PROMPT.format(
        resume=resume_text[:8000],
        jd=jd_text[:4000],
    )

    quota_errors: list[str] = []
    last_error = "No models available."

    for model_name in models:
        raw, err = _call_model(client, model_name, prompt)

        if err and _is_quota_error(err):
            retry_s = _extract_retry_seconds(err)
            hint = f" (retry in ~{retry_s}s)" if retry_s else ""
            quota_errors.append(f"• **{model_name}** — quota exhausted{hint}")
            continue   # try the next model

        if err or not raw:
            last_error = f"Model '{model_name}' error: {err or 'empty response'}"
            continue

        # ── Got a response — parse JSON ──────────────────────────────────────
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

        try:
            return json.loads(raw), None
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group()), None
                except Exception:
                    pass
            last_error = f"Model '{model_name}' returned non-JSON output: {raw[:200]}"
            continue

    # All models failed — compose a helpful summary
    if quota_errors:
        summary = (
            "**All available models have exceeded their free-tier quota.**\n\n"
            + "\n".join(quota_errors)
            + "\n\n**Solutions:**\n"
            "1. Wait a minute and try again (per-minute quota resets).\n"
            "2. Use a different Gemini API key.\n"
            "3. Enable billing at https://console.cloud.google.com to get higher limits."
        )
        return None, summary

    return None, last_error


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def fit_color(fit_level: str) -> str:
    colors = {
        "Strong Fit": "#28a745",
        "Good Fit": "#17a2b8",
        "Moderate Fit": "#ffc107",
        "Weak Fit": "#dc3545",
    }
    return colors.get(fit_level, "#6c757d")


def score_color(score: int) -> str:
    if score >= 80:
        return "#28a745"
    elif score >= 60:
        return "#17a2b8"
    elif score >= 40:
        return "#ffc107"
    return "#dc3545"
