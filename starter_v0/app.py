from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import streamlit as st

from chat import append_agent_trace, now_iso, run_model_tool_loop, trim_history, write_transcript
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from ui.workbench import (
    build_initial_state,
    build_transcript,
    extract_safe_links,
    json_for_display,
    load_version_evidence,
    make_transcript_identity,
    queue_submission,
    sanitize_error,
    tool_event_error,
    tool_event_status,
    transcript_download_bytes,
)
from versioning import artifact_version_dict, build_artifact_version


ROOT = Path(__file__).parent
ARTIFACTS_DIR = ROOT / "artifacts"
SYSTEM_PROMPT_PATH = ARTIFACTS_DIR / "system_prompt.md"
TOOLS_PATH = ARTIFACTS_DIR / "tools.yaml"
TRANSCRIPTS_DIR = ROOT / "transcripts"
AGENT_TRACE_PATH = ARTIFACTS_DIR / "agent_trace.csv"
CSS_PATH = ROOT / "ui" / "styles.css"

PROVIDERS = {
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
}

SAMPLE_QUERIES = [
    "Tin AI nổi bật hôm nay là gì? Tóm tắt 5 nguồn đáng chú ý.",
    "Tìm 5 bài đăng mới nhất của tài khoản karpathy.",
    "Đọc URL này và tóm tắt các luận điểm chính giúp tôi.",
    "Tìm 3 paper mới về AI agents và nêu đóng góp chính.",
]

STATUS_LABELS = {
    "Ready": "Ready",
    "Running": "Running",
    "Waiting for input": "Waiting for input",
    "Error": "Error",
}


def load_styles() -> None:
    if CSS_PATH.is_file():
        css = CSS_PATH.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def reset_session() -> None:
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()


def render_header() -> None:
    transcript = st.session_state.transcript or {}
    current_model = (
        transcript.get("model")
        or st.session_state.model_name.strip()
        or "Provider default"
    )
    status = STATUS_LABELS.get(st.session_state.status, st.session_state.status)
    status_class = {
        "Running": "running",
        "Waiting for input": "waiting",
        "Error": "error",
    }.get(status, "ready")
    provider_label = PROVIDERS.get(
        st.session_state.provider_name,
        st.session_state.provider_name,
    )
    st.markdown(
        f"""
        <section class="workbench-header" aria-label="Research Agent status">
          <div class="workbench-title-wrap">
            <p class="workbench-kicker">Technical research workspace</p>
            <h1>Research Agent Workbench</h1>
          </div>
          <div class="workbench-meta" role="list" aria-label="Session metadata">
            <span class="meta-pill" role="listitem">{html.escape(provider_label)}</span>
            <span class="meta-pill" role="listitem">{html.escape(str(current_model))}</span>
            <span class="meta-pill active" role="listitem">{html.escape(st.session_state.version_label)}</span>
            <span class="meta-pill artifact" role="listitem">{html.escape(st.session_state.artifact_version)}</span>
            <span class="status-pill {status_class}" role="status">{html.escape(status)}</span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_safe_links(value: Any) -> None:
    links = extract_safe_links(value)
    if not links:
        return
    items = "".join(
        (
            '<a class="source-link" target="_blank" rel="noopener noreferrer" '
            f'href="{html.escape(item["url"], quote=True)}">'
            f'{html.escape(item["label"])}</a>'
        )
        for item in links
    )
    st.markdown(
        f'<div class="source-links" aria-label="Sources">{items}</div>',
        unsafe_allow_html=True,
    )


def render_chat_message(message: dict[str, Any]) -> None:
    role = message.get("role", "assistant")
    with st.chat_message(role):
        content = str(message.get("content") or "")
        kind = message.get("kind")
        if kind == "error":
            if "Missing API key env var" in content:
                st.error(f"Missing provider credentials. {content}")
            else:
                st.error(f"Provider error. {content}")
        elif kind == "waiting":
            st.warning("Waiting for user clarification")
            st.markdown(content)
        elif kind == "max_rounds":
            st.warning(
                "Maximum tool rounds reached. Open Tool Trace to inspect the "
                "last completed round."
            )
            if content:
                st.markdown(content)
        elif content:
            st.markdown(content)
        else:
            st.caption("The provider returned no assistant text.")

        turn_index = message.get("turn_index")
        if role == "assistant" and isinstance(turn_index, int):
            turns = st.session_state.turns
            if 0 < turn_index <= len(turns):
                render_safe_links(turns[turn_index - 1].get("tool_events", []))


def render_tool_event(
    event: dict[str, Any],
    *,
    label_prefix: str,
    event_index: int,
) -> None:
    tool_name = str(event.get("tool") or "unknown")
    status = tool_event_status(event)
    status_label = {
        "success": "Success",
        "waiting": "Waiting",
        "error": "Error",
    }[status]
    st.markdown(
        (
            '<div class="tool-event-heading">'
            f'<span class="tool-pill">{html.escape(tool_name)}</span>'
            f'<span class="tool-status {status}">{status_label}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    with st.expander(
        f"Arguments · {label_prefix} · {event_index}",
        expanded=False,
    ):
        st.code(json_for_display(event.get("args", {})), language="json")
    with st.expander(
        f"Result · {label_prefix} · {event_index}",
        expanded=False,
    ):
        st.code(json_for_display(event.get("result")), language="json")
        render_safe_links(event.get("result"))
    error = tool_event_error(event)
    if error:
        st.error(f"Tool execution error: {error}")


def render_trace(turn: dict[str, Any] | None, *, label_prefix: str) -> None:
    if not turn:
        st.info("No chat yet")
        return

    rounds = turn.get("rounds") or []
    flat_events = turn.get("tool_events") or []
    if not rounds and not flat_events:
        st.info("No tool called")
        return

    rendered_event_ids: set[int] = set()
    for round_record in rounds:
        round_number = round_record.get("round", "—")
        calls = round_record.get("tool_calls") or []
        st.markdown(
            (
                '<div class="round-heading">'
                f"<strong>Round {html.escape(str(round_number))}</strong>"
                f"<span>{len(calls)} tool call(s)</span>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        intermediate = round_record.get("assistant_text")
        if intermediate:
            st.caption(f"Assistant intermediate text: {intermediate}")
        for index, event in enumerate(
            round_record.get("tool_results") or [],
            start=1,
        ):
            rendered_event_ids.add(id(event))
            render_tool_event(
                event,
                label_prefix=f"{label_prefix} R{round_number}",
                event_index=index,
            )

    remaining = [
        event for event in flat_events
        if id(event) not in rendered_event_ids
    ]
    if remaining:
        st.markdown('<div class="round-heading"><strong>Tool events</strong></div>', unsafe_allow_html=True)
        for index, event in enumerate(remaining, start=1):
            render_tool_event(
                event,
                label_prefix=label_prefix,
                event_index=index,
            )


def render_transcript_tab() -> None:
    transcript = st.session_state.transcript
    transcript_path = st.session_state.transcript_path
    if not transcript or not transcript_path:
        st.info("No transcript yet")
        return

    metadata = [
        ("Transcript ID", transcript.get("transcript_id")),
        ("Created at", transcript.get("created_at")),
        ("Updated at", transcript.get("updated_at")),
        ("Provider", transcript.get("provider")),
        ("Model", transcript.get("model")),
        ("Version", transcript.get("version")),
        ("Artifact version", transcript.get("artifact_version")),
        ("Chat turns", len(transcript.get("turns") or [])),
        ("File", str(transcript_path)),
    ]
    for label, value in metadata:
        st.markdown(
            (
                '<div class="metadata-row">'
                f"<span>{html.escape(label)}</span>"
                f"<strong>{html.escape(str(value or '—'))}</strong>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )
    st.download_button(
        "Download transcript JSON",
        data=transcript_download_bytes(transcript),
        file_name=Path(transcript_path).name,
        mime="application/json",
        use_container_width=True,
    )


def render_evidence_tab() -> None:
    evidence = load_version_evidence(ROOT)
    if not evidence["has_evidence"]:
        st.info("Chưa có run evidence để so sánh. Hãy chạy eval trước.")
    else:
        version_rows = evidence["version_rows"]
        if version_rows:
            st.markdown("#### Version log")
            st.dataframe(version_rows, use_container_width=True, hide_index=True)
        if evidence["runs"]:
            st.markdown("#### Eval runs")
            for run in evidence["runs"]:
                label = " · ".join(
                    part for part in [
                        run.get("version"),
                        run.get("suite"),
                        run.get("filename"),
                    ]
                    if part
                )
                with st.expander(label or run["filename"], expanded=False):
                    st.caption(run["path"])
                    st.json(run.get("summary") or {})
    for error in evidence["errors"]:
        st.warning(f"Could not read evidence file: {error}")


st.set_page_config(
    page_title="Research Agent Workbench",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)
load_styles()

for state_key, default_value in build_initial_state().items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value

try:
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    tool_declarations = load_tool_declarations(TOOLS_PATH)
    openai_tools = to_openai_tools(tool_declarations)
except (OSError, KeyError, TypeError, ValueError) as exc:
    st.error(f"Workbench configuration error: {sanitize_error(exc)}")
    st.stop()

version_label = st.session_state.version_label.strip() or "v0"
artifact = build_artifact_version(
    version_label,
    SYSTEM_PROMPT_PATH,
    TOOLS_PATH,
)
st.session_state.artifact_version = artifact.artifact_version

sample_submission: str | None = None
with st.sidebar:
    st.markdown("## Session controls")
    st.caption("Provider settings are locked after the first submitted turn.")
    if st.button("New session", type="primary", use_container_width=True):
        reset_session()

    st.selectbox(
        "Provider",
        options=list(PROVIDERS),
        format_func=lambda value: PROVIDERS[value],
        key="provider_name",
        disabled=st.session_state.session_started,
    )
    st.text_input(
        "Model (optional)",
        key="model_name",
        placeholder="Use provider default",
        disabled=st.session_state.session_started,
    )
    st.text_input(
        "Version label",
        key="version_label",
        placeholder="v0",
        disabled=st.session_state.session_started,
    )
    st.slider(
        "History window",
        min_value=0,
        max_value=20,
        key="history_window",
    )
    st.slider(
        "Maximum tool rounds",
        min_value=1,
        max_value=10,
        key="max_tool_rounds",
    )

    with st.expander(f"Available tools · {len(tool_declarations)}", expanded=False):
        for declaration in tool_declarations:
            st.markdown(
                f"**`{declaration.get('name', 'unknown')}`**  \n"
                f"{declaration.get('description', 'No description')}"
            )

    st.markdown("### Sample queries")
    for index, query in enumerate(SAMPLE_QUERIES):
        if st.button(
            query,
            key=f"sidebar_sample_{index}",
            use_container_width=True,
            disabled=st.session_state.is_running,
        ):
            sample_submission = query

    st.markdown("### Current transcript")
    if st.session_state.transcript:
        st.caption(f"ID: {st.session_state.transcript_id}")
        st.caption(f"Turns: {len(st.session_state.turns)}")
        st.code(str(st.session_state.transcript_path), language=None)
    else:
        st.caption("No transcript yet")

render_header()

chat_column, trace_column = st.columns([1.65, 1], gap="large")
with chat_column:
    st.markdown('<h2 class="section-title">Chat workspace</h2>', unsafe_allow_html=True)
    if not st.session_state.messages:
        st.markdown(
            """
            <div class="empty-state">
              <strong>No chat yet</strong>
              <span>Ask a research question or try one of the prompts below.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        empty_columns = st.columns(2)
        for index, query in enumerate(SAMPLE_QUERIES):
            with empty_columns[index % 2]:
                if st.button(
                    query,
                    key=f"empty_sample_{index}",
                    use_container_width=True,
                    disabled=st.session_state.is_running,
                ):
                    sample_submission = query
    else:
        for chat_message in st.session_state.messages:
            render_chat_message(chat_message)

    chat_prompt = st.chat_input(
        "Ask the Research Agent…",
        disabled=st.session_state.is_running,
    )

with trace_column:
    st.markdown('<h2 class="section-title">Tool Trace</h2>', unsafe_allow_html=True)
    selected_turn = (
        st.session_state.turns[st.session_state.selected_turn_index]
        if st.session_state.turns
        and isinstance(st.session_state.selected_turn_index, int)
        and 0 <= st.session_state.selected_turn_index < len(st.session_state.turns)
        else None
    )
    render_trace(selected_turn, label_prefix="Panel")

current_trace_tab, transcript_tab, evidence_tab, raw_tab = st.tabs([
    "Current Trace",
    "Transcript",
    "Version Evidence",
    "Raw JSON",
])
with current_trace_tab:
    render_trace(selected_turn, label_prefix="Timeline")
with transcript_tab:
    render_transcript_tab()
with evidence_tab:
    render_evidence_tab()
with raw_tab:
    raw_value = selected_turn or st.session_state.transcript
    if raw_value is None:
        st.info("No transcript yet")
    else:
        with st.expander("Show raw JSON", expanded=False):
            st.code(json_for_display(raw_value), language="json")

pending_text = str(st.session_state.pending_submission or "").strip()
if pending_text and st.session_state.is_running:
    submitted_text = pending_text
    turn_index = len(st.session_state.turns) + 1
    turn_record: dict[str, Any] = {
        "turn_index": turn_index,
        "started_at": now_iso(),
        "user": submitted_text,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }

    with st.spinner("Provider is running"):
        try:
            provider = make_provider(st.session_state.provider_name)
            selected_model = (
                st.session_state.model_name.strip()
                or getattr(provider, "default_model", None)
            )

            if st.session_state.transcript is None:
                transcript_id = make_transcript_identity(
                    version_label,
                    st.session_state.provider_name,
                )
                transcript_path = (
                    TRANSCRIPTS_DIR / f"{transcript_id}.transcript.json"
                )
                st.session_state.transcript_id = transcript_id
                st.session_state.transcript_path = transcript_path
                st.session_state.transcript = build_transcript(
                    transcript_id=transcript_id,
                    artifact=artifact_version_dict(artifact),
                    provider=st.session_state.provider_name,
                    model=selected_model,
                    system_prompt_path=SYSTEM_PROMPT_PATH.relative_to(ROOT),
                    tools_path=TOOLS_PATH.relative_to(ROOT),
                    history_window=st.session_state.history_window,
                    max_tool_rounds=st.session_state.max_tool_rounds,
                    created_at=now_iso(),
                )

            model_messages = [
                {"role": "system", "content": system_prompt},
                *trim_history(
                    st.session_state.history,
                    st.session_state.history_window,
                ),
                {"role": "user", "content": submitted_text},
            ]
            result = run_model_tool_loop(
                provider=provider,
                messages=model_messages,
                tools=openai_tools,
                model=st.session_state.model_name.strip() or None,
                max_tool_rounds=st.session_state.max_tool_rounds,
            )
            turn_record.update(result)
            assistant_text = str(result.get("assistant_text") or "")
            result_status = result.get("status")
            message_kind = None
            if result_status == "waiting_for_user":
                st.session_state.status = "Waiting for input"
                message_kind = "waiting"
            elif result_status == "max_tool_rounds":
                st.session_state.status = "Ready"
                message_kind = "max_rounds"
            else:
                st.session_state.status = "Ready"
            st.session_state.messages.append({
                "role": "assistant",
                "content": assistant_text,
                "kind": message_kind,
                "turn_index": turn_index,
            })
            st.session_state.history.extend([
                {"role": "user", "content": submitted_text},
                {"role": "assistant", "content": assistant_text},
            ])
            st.session_state.last_result = result
            # Persist a Thinking / Tool-call / Tool-result trace for this turn so
            # the demo leaves a replayable record in artifacts/agent_trace.csv.
            # Best-effort: never let a log write failure mask the real result.
            try:
                append_agent_trace(
                    AGENT_TRACE_PATH,
                    version=version_label,
                    provider=st.session_state.provider_name,
                    model=selected_model,
                    turn_index=turn_index,
                    rounds=result.get("rounds") or [],
                )
            except OSError as exc:
                st.session_state.last_error = sanitize_error(exc)
        except Exception as exc:
            safe_error = sanitize_error(exc)
            turn_record.update({
                "status": "provider_error",
                "error": safe_error,
            })
            st.session_state.status = "Error"
            st.session_state.last_error = safe_error
            st.session_state.messages.append({
                "role": "assistant",
                "content": safe_error,
                "kind": "error",
                "turn_index": turn_index,
            })

    turn_record["ended_at"] = now_iso()
    st.session_state.turns.append(turn_record)
    st.session_state.selected_turn_index = len(st.session_state.turns) - 1
    st.session_state.pending_submission = None
    st.session_state.is_running = False

    transcript = st.session_state.transcript
    transcript_path = st.session_state.transcript_path
    if transcript is not None and transcript_path is not None:
        transcript["history_window"] = st.session_state.history_window
        transcript["max_tool_rounds"] = st.session_state.max_tool_rounds
        transcript["turns"] = list(st.session_state.turns)
        try:
            write_transcript(Path(transcript_path), transcript)
        except OSError as exc:
            safe_write_error = sanitize_error(exc)
            st.session_state.status = "Error"
            st.session_state.last_error = safe_write_error
    st.rerun()
else:
    submitted_text = (chat_prompt or sample_submission or "").strip()
    if queue_submission(st.session_state, submitted_text):
        turn_index = len(st.session_state.turns) + 1
        st.session_state.messages.append({
            "role": "user",
            "content": submitted_text,
            "turn_index": turn_index,
        })
        st.rerun()
