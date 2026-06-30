"""Auto-authentication for Railway deployment.

When SUPABASE_DASHBOARD_EMAIL and SUPABASE_DASHBOARD_PASSWORD are set as
Railway environment variables, the app signs in automatically and caches the
JWT for up to 55 minutes (token lifetime is 1 hour; we refresh 5 min early).

On local dev, the user pastes the token manually in the sidebar — this module
is a no-op in that case.
"""
from __future__ import annotations

import os
import time

import requests

_SUPABASE_URL  = os.getenv("SUPABASE_URL", "https://yyksazeprxfcvcepabzg.supabase.co")
_SUPABASE_KEY  = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl5a3NhemVwcnhmY3ZjZXBhYnpnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzNDQ2NDYsImV4cCI6MjA4OTkyMDY0Nn0.E5xN2ugB1HhyuF0lJoxhf1g45oc-XdKJsVVVlpYDogA",
)

_EMAIL    = os.getenv("SUPABASE_DASHBOARD_EMAIL", "")
_PASSWORD = os.getenv("SUPABASE_DASHBOARD_PASSWORD", "")

# Module-level cache so we don't sign in on every Streamlit render
_cached_token:      str   = ""
_token_expires_at:  float = 0.0


def auto_auth_available() -> bool:
    return bool(_EMAIL and _PASSWORD)


def get_effective_auth_token(manual_token: str = "") -> str:
    """Return the best available auth token.

    Priority:
      1. Auto-login via env credentials (Railway deployment)
      2. Manually-pasted token from the sidebar
    """
    if auto_auth_available():
        return _get_auto_token()
    return manual_token


def _get_auto_token() -> str:
    global _cached_token, _token_expires_at

    # Return cached token if still valid
    if _cached_token and time.time() < _token_expires_at:
        return _cached_token

    try:
        resp = requests.post(
            f"{_SUPABASE_URL}/auth/v1/token?grant_type=password",
            json={"email": _EMAIL, "password": _PASSWORD},
            headers={
                "apikey":       _SUPABASE_KEY,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _cached_token     = data.get("access_token", "")
        expires_in        = data.get("expires_in", 3600)
        _token_expires_at = time.time() + expires_in - 300  # refresh 5 min early
        return _cached_token
    except Exception as exc:
        print(f"[auth] Auto-login failed: {exc}")
        return ""
