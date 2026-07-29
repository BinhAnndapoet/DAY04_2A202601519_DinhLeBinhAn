from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from providers.base import Provider, ToolCall
from tools import TOOL_FUNCTIONS

# ===== Message / tool-result helpers (shared shape with chat.py) =====

def json_text(value: Any, *, max_chars: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + "\n...<truncated>"
    return text


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
    except Exception as exc:  # keep eval robust; failures are evidence
        result = {"error": type(exc).__name__, "message": str(exc)}
    return {"tool": call.name, "args": call.args, "result": result}


def assistant_tool_message(text: str | None, calls: list[ToolCall]) -> dict[str, str]:
    call_summary = [{"name": call.name, "args": call.args} for call in calls]
    content = text or "I will call the selected tool(s)."
    return {
        "role": "assistant",
        "content": f"{content}\n\nTOOL_CALLS_JSON:\n{json_text(call_summary)}",
    }


def tool_results_message(events: list[dict[str, Any]], notes: str | None = None) -> dict[str, str]:
    """Build the user-role message feeding tool results back to the model.

    When ``notes`` is provided (an auto-generated summary of the raw results), it
    is appended as a RESEARCH_NOTES block the model should prefer for reasoning.
    """
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


# ===== Content summarization step =====
# Mirrors deep research's summarize_webpage_content / compress_research: after a
# round of data tools, compress the raw content into short notes so the agent can
# reason over many sources without overflowing the context window.

SUMMARIZATION_PROMPT = (
    "You are a research note-taker. Compress the raw tool results below into concise research notes.\n"
    "Rules:\n"
    "- Preserve concrete facts, numbers, dates, names, and source identifiers (titles/URLs).\n"
    "- Drop filler, boilerplate, navigation text, and duplicates.\n"
    "- Keep the original language of each source.\n"
    "- Output 3-10 short bullet notes, no preamble."
)

# Tools whose output carries no research content worth summarizing.
SUMMARY_TOOL_DENYLIST = {"think", "clarify", "format", "send"}
SUMMARIZE_THRESHOLD = 1200
_SUMMARY_BLOB_CAP = 6000


def collect_content(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Extract (tool, text) content blobs from tool-result events for summarization."""
    blobs: list[tuple[str, str]] = []
    for event in events:
        tool = event.get("tool", "")
        if tool in SUMMARY_TOOL_DENYLIST:
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        texts: list[str] = []
        items = result.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    chunk = item.get("summary") or item.get("content") or item.get("title")
                    if chunk:
                        texts.append(str(chunk))
        if result.get("content"):
            texts.append(str(result["content"]))
        if texts:
            blobs.append((tool, "\n".join(texts)))
    return blobs


def summarize_tool_results(
    provider: Provider,
    model: str | None,
    events: list[dict[str, Any]],
    *,
    threshold: int = SUMMARIZE_THRESHOLD,
) -> str | None:
    """Summarize a round's tool results into notes via the provider.

    Returns None when there is too little content to justify an extra model call
    or when summarization fails, so callers can always fall back to the raw output.
    """
    blobs = collect_content(events)
    total_chars = sum(len(text) for _, text in blobs)
    if total_chars < threshold:
        return None
    joined = "\n\n".join(
        f"[{tool}] {text[:_SUMMARY_BLOB_CAP]}" for tool, text in blobs
    )
    messages = [
        {"role": "system", "content": SUMMARIZATION_PROMPT},
        {"role": "user", "content": joined[:20000]},
    ]
    try:
        response = provider.complete(messages, tools=None, model=model, temperature=0.0)
    except Exception:
        return None
    return response.text


# ===== Agent =====

@dataclass
class AgentRun:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    # Richer loop metadata (used by chat.py transcripts; ignored by run_eval.py).
    status: str = "answered"
    rounds: list[dict[str, Any]] = field(default_factory=list)


class ResearchAgent:
    """Tool-calling research agent.

    By default runs a single tool step (``max_tool_rounds=1``), which keeps the
    eval path in run_eval.py unchanged. Set ``max_tool_rounds > 1`` to enable the
    multi-step ReAct loop: the model calls tools, results are fed back, and it can
    use ``think`` to reflect between steps. Enable ``summarize_results`` to compress
    each round's content into notes before the next step.
    """

    def __init__(
        self,
        provider: Provider,
        *,
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tool_rounds: int = 1,
        summarize_results: bool = False,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.model = model
        self.max_tool_rounds = max(1, max_tool_rounds)
        self.summarize_results = summarize_results

    def _summarize(self, events: list[dict[str, Any]]) -> str | None:
        if not self.summarize_results:
            return None
        return summarize_tool_results(self.provider, self.model, events)

    def run(self, user_messages: list[dict[str, str]], *, tool_choice: Any | None = None) -> AgentRun:
        """Run the agent, looping over tool calls up to ``max_tool_rounds``."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            *user_messages,
        ]
        rounds: list[dict[str, Any]] = []
        all_results: list[dict[str, Any]] = []
        first_calls: list[ToolCall] | None = None
        first_text: str | None = None
        last_text: str | None = None
        status = "answered"

        for round_index in range(1, self.max_tool_rounds + 1):
            # Only the first round may honor a forced tool_choice; later rounds must
            # be free to either call another tool or produce the final answer.
            forced = tool_choice if round_index == 1 else None
            response = self.provider.complete(
                messages, self.tools, model=self.model, temperature=0.0, tool_choice=forced,
            )
            calls = response.tool_calls

            if first_calls is None:
                first_calls = calls
                first_text = response.text

            round_record: dict[str, Any] = {
                "round": round_index,
                "assistant_text": response.text,
                "tool_calls": [{"name": call.name, "args": call.args} for call in calls],
                "tool_results": [],
            }

            # No tool calls => the model produced its final answer.
            if not calls:
                status = "answered"
                last_text = response.text
                rounds.append(round_record)
                break

            messages.append(assistant_tool_message(response.text, calls))

            # Execute all tool calls for this round.
            paused_question: str | None = None
            for call in calls:
                event = execute_tool_call(call)
                round_record["tool_results"].append(event)
                all_results.append(event)
                result = event.get("result")
                # Rename-proof clarification/pause detection (output flag, not tool name).
                if (
                    paused_question is None
                    and isinstance(result, dict)
                    and result.get("awaiting_user")
                ):
                    paused_question = (
                        result.get("question")
                        or call.args.get("question")
                        or "Bạn bổ sung thêm thông tin nhé."
                    )

            if paused_question is not None:
                status = "waiting_for_user"
                rounds.append(round_record)
                return AgentRun(
                    text=paused_question,
                    tool_calls=first_calls,
                    tool_results=all_results,
                    status=status,
                    rounds=rounds,
                )

            # Content summarization step (compress this round's raw results).
            notes = self._summarize(round_record["tool_results"])

            messages.append(tool_results_message(round_record["tool_results"], notes=notes))
            rounds.append(round_record)
            last_text = response.text
            status = "max_tool_rounds"

        # Loop exhausted without a clean final answer.
        final_text = last_text if last_text else (first_text or "")
        if status == "max_tool_rounds" and not (final_text and final_text.strip()):
            final_text = (
                f"Stopped after {self.max_tool_rounds} tool rounds. "
                "Inspect the transcript for details."
            )

        return AgentRun(
            text=final_text,
            tool_calls=first_calls or [],
            tool_results=all_results,
            status=status,
            rounds=rounds,
        )
