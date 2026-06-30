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
CLASSROOM_ADMIN_URL = os.getenv(
    "CLASSROOM_ADMIN_URL",
    "https://classroomreviewagent-rhqeqhqzo-deepakmunesh-engs-projects.vercel.app/admin",
)
CLASSROOM_ADMIN_KEY = os.getenv("CLASSROOM_ADMIN_KEY", "Cu3L3@rn")

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
RAILWAY_BACKEND_URL = os.getenv(
    "RAILWAY_BACKEND_URL",
    "https://curriculum-studio-k-8-production.up.railway.app",
)

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
