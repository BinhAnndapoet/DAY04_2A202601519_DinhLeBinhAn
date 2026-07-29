from __future__ import annotations

import csv
import json
import re
from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


MAX_DISPLAY_JSON_CHARS = 8_000
MAX_ERROR_CHARS = 1_200


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("_") or "session"


def make_transcript_identity(
    version: str,
    provider: str,
    *,
    now: datetime | None = None,
) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%dT%H%M%S%f")
    suffix = uuid4().hex[:8]
    return "_".join([
        _safe_slug(version),
        _safe_slug(provider),
        timestamp,
        suffix,
    ])


def build_initial_state() -> dict[str, Any]:
    return {
        "messages": [],
        "history": [],
        "turns": [],
        "transcript": None,
        "transcript_path": None,
        "transcript_id": None,
        "provider_name": "openrouter",
        "model_name": "",
        "version_label": "v0",
        "artifact_version": "",
        "selected_turn_index": None,
        "last_result": None,
        "is_running": False,
        "pending_submission": None,
        "status": "Ready",
        "session_started": False,
        "last_error": None,
        "history_window": 5,
        "max_tool_rounds": 4,
    }


def queue_submission(state: MutableMapping[str, Any], value: str) -> bool:
    submitted_text = value.strip()
    if not submitted_text or state.get("is_running"):
        return False
    state["pending_submission"] = submitted_text
    state["is_running"] = True
    state["session_started"] = True
    state["status"] = "Running"
    state["last_error"] = None
    return True


def build_transcript(
    *,
    transcript_id: str,
    artifact: dict[str, str],
    provider: str,
    model: str | None,
    system_prompt_path: Path,
    tools_path: Path,
    history_window: int,
    max_tool_rounds: int,
    created_at: str,
) -> dict[str, Any]:
    return {
        "transcript_id": transcript_id,
        **artifact,
        "provider": provider,
        "model": model,
        "system_prompt": str(system_prompt_path),
        "tools": str(tools_path),
        "history_window": history_window,
        "max_tool_rounds": max_tool_rounds,
        "created_at": created_at,
        "updated_at": created_at,
        "turns": [],
    }


def is_safe_external_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except (AttributeError, ValueError):
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _redact_secrets(text: str) -> str:
    patterns = [
        (
            re.compile(
                r"(?i)(authorization\s*[:=]\s*bearer\s+)"
                r"[A-Za-z0-9._~+/=-]+"
            ),
            r"\1[REDACTED]",
        ),
        (
            re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}"),
            "Bearer [REDACTED]",
        ),
        (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
        (re.compile(r"\bAIza[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
        (
            re.compile(
                r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|key)=)"
                r"[^&#\s]+"
            ),
            r"\1[REDACTED]",
        ),
        (
            re.compile(
                r"(?i)(['\"]?(?:x-api-key|api[_-]?key|access[_-]?token)"
                r"['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+"
            ),
            r"\1[REDACTED]",
        ),
    ]
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def sanitize_error(value: BaseException | str) -> str:
    if isinstance(value, BaseException):
        text = f"{type(value).__name__}: {value}"
    else:
        text = str(value)
    text = _redact_secrets(text)
    if len(text) > MAX_ERROR_CHARS:
        return text[:MAX_ERROR_CHARS] + "...<truncated>"
    return text


def tool_event_status(event: dict[str, Any]) -> str:
    result = event.get("result")
    if isinstance(result, dict):
        if result.get("awaiting_user"):
            return "waiting"
        if result.get("error"):
            return "error"
    return "success"


def tool_event_error(event: dict[str, Any]) -> str | None:
    result = event.get("result")
    if not isinstance(result, dict) or not result.get("error"):
        return None
    error = sanitize_error(str(result["error"]))
    message = result.get("message")
    if message:
        return f"{error}: {sanitize_error(str(message))}"
    return error


def json_for_display(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    rendered = _redact_secrets(rendered)
    if len(rendered) > MAX_DISPLAY_JSON_CHARS:
        return rendered[:MAX_DISPLAY_JSON_CHARS] + "...<truncated>"
    return rendered


def extract_safe_links(value: Any) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and is_safe_external_url(url) and url not in seen:
                raw_label = item.get("title") or item.get("source") or url
                links.append({"label": str(raw_label).strip() or url, "url": url})
                seen.add(url)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return links


def transcript_download_bytes(transcript: dict[str, Any]) -> bytes:
    return json.dumps(
        transcript,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")


def load_version_evidence(root: Path) -> dict[str, Any]:
    root = Path(root)
    version_rows: list[dict[str, str]] = []
    runs: list[dict[str, Any]] = []
    errors: list[str] = []

    version_log = root / "artifacts" / "version_log.csv"
    if version_log.is_file():
        try:
            with version_log.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    normalized = {
                        str(key): str(value or "").strip()
                        for key, value in row.items()
                        if key is not None
                    }
                    if any(normalized.values()):
                        version_rows.append(normalized)
        except (OSError, csv.Error) as exc:
            errors.append(
                f"{version_log.name}: {sanitize_error(exc)}"
            )

    runs_dir = root / "runs"
    if runs_dir.is_dir():
        for path in sorted(runs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Run JSON root must be an object")
                runs.append({
                    "filename": path.name,
                    "path": str(path.relative_to(root)),
                    "version": data.get("version"),
                    "artifact_version": data.get("artifact_version"),
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "suite": data.get("suite"),
                    "created_at": data.get("created_at"),
                    "summary": data.get("summary", {}),
                })
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{path.name}: {sanitize_error(exc)}")

    return {
        "has_evidence": bool(version_rows or runs),
        "version_rows": version_rows,
        "runs": runs,
        "errors": errors,
    }
