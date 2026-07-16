import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Google Sheets (direct HTTP — no API key needed for public sheets) ──────────
LESSON_REVIEW_SHEET_ID = os.getenv(
    "LESSON_REVIEW_SHEET_ID", "1nU8GdiNpyaiWmgaK4hiCZsAv2OI3CT_PIdZpsrSh3jE"
)
# Direct XLSX export URL (works when sheet is shared "anyone with link can view")
LESSON_REVIEW_XLSX_URL = (
    f"https://docs.google.com/spreadsheets/d/{LESSON_REVIEW_SHEET_ID}/export?format=xlsx"
)

# ── Classroom review admin ─────────────────────────────────────────────────────
# Stable production URL + JSON submissions API. The old deployment-hash URL
# (…-rhqeqhqzo-…/admin) 302-redirects to Vercel login (401); the app fetches its
# data from /api/admin/submissions?key=… (see classroom_reader).
CLASSROOM_ADMIN_URL = os.getenv(
    "CLASSROOM_ADMIN_URL",
    "https://classroomreviewagent.vercel.app/api/admin/submissions",
)
CLASSROOM_ADMIN_KEY = os.getenv("CLASSROOM_ADMIN_KEY", "Cu3L3@rn")

# ── Exit-ticket data sheet (student exit-ticket performance) ──────────────────
# Per-widget avg-score / max-score with a learnosity_activity_ref that matches
# the review sheet's Activity Reference ID. Exit score per lesson = mean over its
# items of (avg-score/max-score)*100, then linearly to 1-5 (×5/100) for health.
EXIT_TICKET_SHEET_ID = os.getenv(
    "EXIT_TICKET_SHEET_ID", "1fKhGSfYIfFO14-9jIqwJ6PPxaBZJo7vQ1cwi0HkaSik"
)
EXIT_TICKET_XLSX_URL = (
    f"https://docs.google.com/spreadsheets/d/{EXIT_TICKET_SHEET_ID}/export?format=xlsx"
)

# ── Lesson lookup sheet (grade / chapter / lesson backfill) ───────────────────
LESSON_LOOKUP_SHEET_ID = os.getenv(
    "LESSON_LOOKUP_SHEET_ID", "1zAjDQhJ4dUNWBaNYGtivLFak5BKfUFQb2dB8MHjouT4"
)
LESSON_LOOKUP_XLSX_URL = (
    f"https://docs.google.com/spreadsheets/d/{LESSON_LOOKUP_SHEET_ID}/export?format=xlsx"
)

# ── Michelangelo Studio — Supabase ────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://yyksazeprxfcvcepabzg.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl5a3NhemVwcnhmY3ZjZXBhYnpnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzNDQ2NDYsImV4cCI6MjA4OTkyMDY0Nn0.E5xN2ugB1HhyuF0lJoxhf1g45oc-XdKJsVVVlpYDogA",
)
SUPABASE_LESSONS_ENDPOINT = f"{SUPABASE_URL}/rest/v1/lessons"

# ── Flow weights (must sum to 100) ────────────────────────────────────────────
WEIGHTING_LEARNING = int(os.getenv("WEIGHTING_LEARNING", "40"))
WEIGHTING_PRACTICE = int(os.getenv("WEIGHTING_PRACTICE", "20"))
WEIGHTING_EXIT_TICKET = int(os.getenv("WEIGHTING_EXIT_TICKET", "10"))
WEIGHTING_CLASSROOM = int(os.getenv("WEIGHTING_CLASSROOM", "30"))

# ── AI Expert Review Doc ──────────────────────────────────────────────────────
AI_REVIEW_DOC_ID = os.getenv(
    "AI_REVIEW_DOC_ID", "1fHNiey9JkcIJC5FGo_CLhf3gM88ZPi6ylDg2etvMsqU"
)
AI_REVIEW_EXPORT_URL = (
    f"https://docs.google.com/document/d/{AI_REVIEW_DOC_ID}/export?format=txt"
)

# ── Learnosity viewer (Michelangelo Studio) ───────────────────────────────────
LEARNOSITY_VIEWER_URL = os.getenv(
    "LEARNOSITY_VIEWER_URL",
    "https://pretty-compassion-production.up.railway.app/#",
)

# On Railway, use private internal networking for service-to-service calls
# (no egress, lower latency, bypasses the public load balancer).
# RAILWAY_ENVIRONMENT is set automatically by the Railway platform.
_on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT", ""))
_default_backend = (
    "http://curriculum-studio-k-8.railway.internal"
    if _on_railway
    else "https://curriculum-studio-k-8-production.up.railway.app"
)
RAILWAY_BACKEND_URL = os.getenv("RAILWAY_BACKEND_URL", _default_backend)

# ── Cuemath data gateway (Learnosity item content) ────────────────────────────
# All Learnosity reads go through the gateway (proxies to the LEARNOSITY service).
# Set both in .env (local) and in the Railway service Variables (production).
DATA_GATEWAY_BASE_URL    = os.getenv("DATA_GATEWAY_BASE_URL", "")
DATA_GATEWAY_TOKEN       = os.getenv("DATA_GATEWAY_TOKEN", "")
LEARNOSITY_MS_DOMAIN_URL = os.getenv("LEARNOSITY_MS_DOMAIN_URL", "leap.cuemath.com")

# ── AI review gating ──────────────────────────────────────────────────────────
# The AI review of learning items (20% of health) stays BLANK with a placeholder
# until we have Learnosity content access (the data-gateway IP allowlist). Flip
# AI_REVIEW_ENABLED=1 in the environment once access is granted to let the app
# generate + populate AI reviews (and fold the 20% component into health).
AI_REVIEW_ENABLED = os.getenv("AI_REVIEW_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")

# ── Cuemath LLM gateway (AI Expert Review synthesis) ──────────────────────────
# The Claude call routes through the LiteLLM proxy (fronting Bedrock), which
# exposes an Anthropic-shaped /v1/messages endpoint with virtual-key auth —
# no direct Anthropic key. Set LLM_MODEL to a model alias the gateway exposes.
LLM_GATEWAY_BASE_URL = os.getenv("LLM_GATEWAY_BASE_URL", "https://llm-gateway.cuemath.com")
LLM_API_KEY          = os.getenv("LLM_API_KEY", "")
LLM_MODEL            = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

# ── App ────────────────────────────────────────────────────────────────────────
_cache_env = os.getenv("CACHE_DIR", "")
# If CACHE_DIR is an absolute path (e.g. /data on Railway), use it directly.
# Otherwise resolve relative to the project root.
CACHE_DIR = Path(_cache_env) if (_cache_env and Path(_cache_env).is_absolute()) else BASE_DIR / (_cache_env or ".cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

COLUMN_MAP = {
    "A": "review_date",   "B": "activity_ref",   "C": "grade",
    "D": "chapter",       "E": "lesson",          "F": "reviewer_name",
    "G": "reviewer_phone","H": "item_ref",
    "I": "understanding", "J": "understanding_details",
    "K": "examples_practice","L": "examples_practice_details",
    "M": "engagement",    "N": "engagement_details",
    "O": "length",        "P": "language",
    "Q": "practice_quality","R": "practice_observations",
    "S": "exit_ticket_quality","T": "exit_ticket_observations",
    "U": "overall_rating","V": "additional_suggestions",
}

RAG_COLORS = {"Good": "#22c55e", "Average": "#f59e0b", "Bad": "#ef4444", "Pending": "#94a3b8"}
