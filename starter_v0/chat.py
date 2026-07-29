from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import summarize_tool_results
from env_loader import load_lab_env
from providers import make_provider
from providers.base import ToolCall
from tools import TOOL_FUNCTIONS, load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version


ROOT = Path(__file__).parent
ARTIFACTS_DIR = ROOT / "artifacts"
load_lab_env(ROOT)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("_") or "run"


def json_text(value: Any, *, max_chars: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + "\n...<truncated>"
    return text


def trim_history(history: list[dict[str, str]], window: int) -> list[dict[str, str]]:
    if window <= 0:
        return []
    return history[-window * 2:]


def execute_tool_call(call: ToolCall) -> dict[str, Any]:
    func = TOOL_FUNCTIONS.get(call.name)
    if not func:
        return {
            "tool": call.name,
            "args": call.args,
            "result": {"error": "unknown_tool", "message": f"No local implementation for {call.name}"},
        }
    try:
        result = func(**call.args)
    except Exception as exc:
        result = {"error": type(exc).__name__, "message": str(exc)}
    return {"tool": call.name, "args": call.args, "result": result}


def tool_results_message(events: list[dict[str, Any]], notes: str | None = None) -> dict[str, str]:
    content = (
        "TOOL_RESULTS_JSON:\n"
        f"{json_text(events, max_chars=24000)}\n\n"
        "Use only these tool results. If the user asked for a digest and the items are ready, "
        "call the formatting tool. Otherwise answer the user directly with cited sources when available."
    )
    if notes:
        content += (
            "\n\nRESEARCH_NOTES (auto-summarized from the results above):\n"
            f"{notes}\n\n"
            "Prefer these notes for reasoning; fall back to the raw results only if a needed detail is missing."
        )
    return {"role": "user", "content": content}


def assistant_tool_message(response_text: str | None, calls: list[ToolCall]) -> dict[str, str]:
    call_summary = [{"name": call.name, "args": call.args} for call in calls]
    content = response_text or "I will call the selected tool(s)."
    return {
        "role": "assistant",
        "content": f"{content}\n\nTOOL_CALLS_JSON:\n{json_text(call_summary)}",
    }


def run_model_tool_loop(
    *,
    provider: Any,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]],
    model: str | None,
    max_tool_rounds: int,
) -> dict[str, Any]:
    working_messages = list(messages)
    rounds: list[dict[str, Any]] = []
    all_tool_events: list[dict[str, Any]] = []

    for round_index in range(1, max_tool_rounds + 1):
        response = provider.complete(working_messages, tools, model=model, temperature=0.0)
        calls = response.tool_calls
        round_record: dict[str, Any] = {
            "round": round_index,
            "assistant_text": response.text,
            "tool_calls": [{"name": call.name, "args": call.args} for call in calls],
            "tool_results": [],
        }

        if not calls:
            rounds.append(round_record)
            return {
                "status": "answered",
                "assistant_text": response.text or "",
                "rounds": rounds,
                "tool_events": all_tool_events,
            }

        working_messages.append(assistant_tool_message(response.text, calls))
        non_clarification_events: list[dict[str, Any]] = []

        for call in calls:
            print(f"🔧 {call.name}({json.dumps(call.args, ensure_ascii=False, sort_keys=True)})")
            event = execute_tool_call(call)
            round_record["tool_results"].append(event)
            all_tool_events.append(event)

            # Detect the clarification/pause tool by its output flag (rename-proof),
            # not by a hard-coded tool name.
            result = event.get("result", {})
            if isinstance(result, dict) and result.get("awaiting_user"):
                question = result.get("question") or call.args.get("question") or "Bạn bổ sung thêm thông tin nhé."
                rounds.append(round_record)
                return {
                    "status": "waiting_for_user",
                    "assistant_text": question,
                    "rounds": rounds,
                    "tool_events": all_tool_events,
                }

            non_clarification_events.append(event)

        rounds.append(round_record)
        # Content summarization step: compress this round's raw results into notes
        # before feeding them back, so the agent reasons over many sources cleanly.
        notes = summarize_tool_results(provider, model, non_clarification_events)
        working_messages.append(tool_results_message(non_clarification_events, notes=notes))

    return {
        "status": "max_tool_rounds",
        "assistant_text": f"Stopped after {max_tool_rounds} tool rounds. Inspect the transcript for details.",
        "rounds": rounds,
        "tool_events": all_tool_events,
    }


def write_transcript(path: Path, transcript: dict[str, Any]) -> None:
    transcript["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# Columns logged for every Thinking / Tool-call / Tool-result step. Append-only,
# one row per step, so the demo leaves a replayable trace of how the agent moved.
AGENT_TRACE_HEADER = [
    "timestamp",
    "version",
    "provider",
    "model",
    "turn",
    "round",
    "step",
    "content",
]


def _trace_tool_call_content(call_summary: dict[str, Any]) -> str:
    name = call_summary.get("name", "unknown")
    args = call_summary.get("args", {})
    return f"{name}({json.dumps(args, ensure_ascii=False, sort_keys=True)})"


def _trace_tool_result_content(result: Any, *, max_chars: int = 240) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            message = result.get("message") or result.get("error")
            return f"error: {message}"[:max_chars]
        if isinstance(result.get("items"), list):
            return f"{len(result['items'])} item(s)"
        if result.get("awaiting_user"):
            return "awaiting_user"
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return text[:max_chars]


def append_agent_trace(
    trace_path: Path,
    *,
    version: str,
    provider: str,
    model: str | None,
    turn_index: int,
    rounds: list[dict[str, Any]],
) -> None:
    """Append one CSV row per agent step to ``trace_path``.

    Creates the file (with header) on first use. Each round contributes a
    ``thinking`` row (when the model emitted reasoning text) and, for every tool
    it invoked, a ``tool_call`` row immediately followed by its ``tool_result``
    row. Designed to be best-effort: callers wrap it in their own error handling.
    """
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not trace_path.exists() or trace_path.stat().st_size == 0
    model_label = model or "default"
    with trace_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(AGENT_TRACE_HEADER)
        for round_record in rounds or []:
            round_number = round_record.get("round", "")
            thinking = round_record.get("assistant_text")
            if thinking and str(thinking).strip():
                writer.writerow([
                    now_iso(), version, provider, model_label,
                    turn_index, round_number, "thinking",
                    str(thinking).strip()[:500],
                ])
            calls = round_record.get("tool_calls") or []
            results = round_record.get("tool_results") or []
            step_count = max(len(calls), len(results))
            for index in range(step_count):
                if index < len(calls):
                    writer.writerow([
                        now_iso(), version, provider, model_label,
                        turn_index, round_number, "tool_call",
                        _trace_tool_call_content(calls[index]),
                    ])
                if index < len(results):
                    writer.writerow([
                        now_iso(), version, provider, model_label,
                        turn_index, round_number, "tool_result",
                        _trace_tool_result_content(results[index].get("result")),
                    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Research Agent chat with transcript logging.")
    parser.add_argument("--provider", choices=["openrouter", "openai", "anthropic", "gemini"], required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--version", required=True, help="Student-chosen artifact version label, e.g. v0, v1, v2.")
    parser.add_argument("--system-prompt", type=Path, default=ARTIFACTS_DIR / "system_prompt.md")
    parser.add_argument("--tools", type=Path, default=ARTIFACTS_DIR / "tools.yaml")
    parser.add_argument("--transcripts-dir", type=Path, default=ROOT / "transcripts")
    parser.add_argument("--history-window", type=int, default=5, help="Keep the last N user/assistant pairs in context.")
    parser.add_argument("--max-tool-rounds", type=int, default=4)
    args = parser.parse_args()

    system_prompt = args.system_prompt.read_text(encoding="utf-8")
    tool_declarations = load_tool_declarations(args.tools)
    openai_tools = to_openai_tools(tool_declarations)
    provider = make_provider(args.provider)
    raw_model = (args.model or "").strip()
    default_model = getattr(provider, "default_model", None)
    # "openai"/"anthropic"/... are provider keys, not model ids — treat a blank
    # value or a provider name as "use the provider default" so we never send the
    # provider name to the API (it 404s as model_not_found).
    if not raw_model or raw_model.lower() == args.provider:
        selected_model = default_model
    else:
        selected_model = raw_model
    artifact_version = build_artifact_version(args.version, args.system_prompt, args.tools)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    transcript_id = "_".join([
        safe_slug(args.version),
        safe_slug(args.provider),
        timestamp,
    ])
    transcript_path = args.transcripts_dir / f"{transcript_id}.transcript.json"
    transcript: dict[str, Any] = {
        "transcript_id": transcript_id,
        **artifact_version_dict(artifact_version),
        "provider": args.provider,
        "model": selected_model,
        "system_prompt": str(args.system_prompt),
        "tools": str(args.tools),
        "history_window": args.history_window,
        "max_tool_rounds": args.max_tool_rounds,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "turns": [],
    }

    print(f"Research Agent chat. artifact_version={artifact_version.artifact_version}")
    print("Type /exit to stop.")

    history: list[dict[str, str]] = []
    turn_index = 0
    while True:
        try:
            user_text = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text in {"/exit", "/quit"}:
            break

        turn_index += 1
        messages = [
            {"role": "system", "content": system_prompt},
            *trim_history(history, args.history_window),
            {"role": "user", "content": user_text},
        ]

        turn_record: dict[str, Any] = {
            "turn_index": turn_index,
            "started_at": now_iso(),
            "user": user_text,
            "status": "started",
            "assistant_text": None,
            "rounds": [],
            "tool_events": [],
        }

        try:
            result = run_model_tool_loop(
                provider=provider,
                messages=messages,
                tools=openai_tools,
                model=selected_model,
                max_tool_rounds=args.max_tool_rounds,
            )
            turn_record.update(result)
            assistant_text = result["assistant_text"]
            print(f"\nAgent> {assistant_text}")
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": assistant_text})
        except Exception as exc:
            turn_record.update({
                "status": "provider_error",
                "error": f"{type(exc).__name__}: {str(exc)}",
            })
            print(f"\nERROR> {turn_record['error']}")

        turn_record["ended_at"] = now_iso()
        transcript["turns"].append(turn_record)
        write_transcript(transcript_path, transcript)
        print(f"Transcript saved: {transcript_path}")

    write_transcript(transcript_path, transcript)
    print(f"Final transcript: {transcript_path}")


if __name__ == "__main__":
    main()
