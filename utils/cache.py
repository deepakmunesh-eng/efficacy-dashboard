"""Hash-based JSON cache — avoids reprocessing unchanged lessons."""
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from config.settings import CACHE_DIR

_RESULTS_FILE = CACHE_DIR / "processed_results.json"
_HASHES_FILE = CACHE_DIR / "data_hashes.json"
_LEARNOSITY_FILE = CACHE_DIR / "learnosity_content.json"


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")


# ── Data hash helpers ──────────────────────────────────────────────────────────

def compute_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def get_stored_hash(activity_ref: str) -> str | None:
    return _load(_HASHES_FILE).get(activity_ref)


def store_hash(activity_ref: str, hash_val: str) -> None:
    d = _load(_HASHES_FILE)
    d[activity_ref] = hash_val
    _save(_HASHES_FILE, d)


def has_changed(activity_ref: str, current_hash: str) -> bool:
    return get_stored_hash(activity_ref) != current_hash


def all_hashes() -> dict:
    """Load the whole hash map once (avoid re-reading the file per lesson)."""
    return _load(_HASHES_FILE)


# ── Processed results ─────────────────────────────────────────────────────────

def get_result(activity_ref: str) -> dict | None:
    return _load(_RESULTS_FILE).get(activity_ref)


def store_result(activity_ref: str, result: dict) -> None:
    d = _load(_RESULTS_FILE)
    result["_cached_at"] = time.time()
    d[activity_ref] = result
    _save(_RESULTS_FILE, d)


def all_results() -> dict:
    return _load(_RESULTS_FILE)


def clear_result(activity_ref: str) -> None:
    d = _load(_RESULTS_FILE)
    d.pop(activity_ref, None)
    _save(_RESULTS_FILE, d)


# ── Learnosity content cache ───────────────────────────────────────────────────

def get_learnosity_content(activity_ref: str) -> dict | None:
    return _load(_LEARNOSITY_FILE).get(activity_ref)


def get_all_learnosity_content() -> dict:
    return _load(_LEARNOSITY_FILE)


def store_learnosity_content(activity_ref: str, content: dict) -> None:
    d = _load(_LEARNOSITY_FILE)
    content["_cached_at"] = time.time()
    d[activity_ref] = content
    _save(_LEARNOSITY_FILE, d)


def bulk_store_learnosity_content(updates: dict) -> None:
    """Write many learnosity entries in a single file write."""
    d = _load(_LEARNOSITY_FILE)
    ts = time.time()
    for ref, content in updates.items():
        content["_cached_at"] = ts
        d[ref] = content
    _save(_LEARNOSITY_FILE, d)


def bulk_store_results(results: dict, hashes: dict) -> None:
    """Write all processed results and hashes in two file writes."""
    existing_r = _load(_RESULTS_FILE)
    existing_h = _load(_HASHES_FILE)
    ts = time.time()
    for ref, res in results.items():
        res["_cached_at"] = ts
        existing_r[ref] = res
    existing_h.update(hashes)
    _save(_RESULTS_FILE, existing_r)
    _save(_HASHES_FILE, existing_h)


def store_hashes(hashes: dict) -> None:
    """Merge change-detection hashes into the store."""
    d = _load(_HASHES_FILE)
    d.update(hashes)
    _save(_HASHES_FILE, d)


def save_all_results(results: dict) -> None:
    """Overwrite the results cache with the FULL current state (Complete AND
    Pending), pruning entries for lessons no longer present. This keeps the
    persisted cache in sync so a page load never shows a stale Complete entry for
    a lesson that has since become Pending (e.g. lost a reviewer)."""
    ts = time.time()
    for res in results.values():
        if isinstance(res, dict):
            res.setdefault("_cached_at", ts)
    _save(_RESULTS_FILE, results)


# ── Curriculum review actions ─────────────────────────────────────────────────
_CURRICULUM_FILE = CACHE_DIR / "curriculum_reviews.json"


def get_curriculum_review(key: str) -> dict:
    return _load(_CURRICULUM_FILE).get(key, {})


def store_curriculum_review(key: str, data: dict) -> None:
    d = _load(_CURRICULUM_FILE)
    data["_saved_at"] = time.time()
    d[key] = data
    _save(_CURRICULUM_FILE, d)


def all_curriculum_reviews() -> dict:
    return _load(_CURRICULUM_FILE)
