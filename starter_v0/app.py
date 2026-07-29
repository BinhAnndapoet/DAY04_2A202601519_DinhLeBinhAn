"""Streamlit UI for the Day 04 Research Agent.

Reuses ``run_model_tool_loop`` from ``chat.py`` so the UI and the CLI share the
exact same agent loop. Saves a transcript per session into ``transcripts/``.

Run:
    streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

# chat.py / agent.py live next to this file and expose the shared agent loop,
# the env loader, provider factory, tool declarations and versioning helpers.
from chat import (
    ROOT,
    ARTIFACTS_DIR,
    now_iso,
    run_model_tool_loop,
    trim_history,
    write_transcript,
)
from env_loader import load_lab_env
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version

load_lab_env(ROOT)

PROVIDERS = ["openrouter", "openai", "anthropic", "gemini"]


def reset_session(artifact_version) -> None:
    """Start a fresh chat transcript for the current artifact version."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    transcript_id = f"{st.session_state.version}_{st.session_state.provider}_{timestamp}"
    st.session_state.transcript = {
        "transcript_id": transcript_id,
        **artifact_version_dict(artifact_version),
        "provider": st.session_state.provider,
        "model": st.session_state.model or None,
        "system_prompt": str(st.session_state.system_prompt_path),
        "tools": str(st.session_state.tools_path),
        "max_tool_rounds": st.session_state.max_tool_rounds,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "turns": [],
    }
    st.session_state.history: list[dict[str, str]] = []
    st.session_state.chat = []  # list of turns: {user, assistant_text, rounds, tool_events, status}


def main() -> None:
    st.set_page_config(page_title="Research Agent", page_icon="🔬", layout="wide")
    st.title("🔬 Day 04 — Research Agent")

    # ---------------- Sidebar: config ----------------
    st.sidebar.header("Cấu hình")
    st.session_state.provider = st.sidebar.selectbox("Provider", PROVIDERS, index=0)
    st.session_state.model = st.sidebar.text_input(
        "Model (để trống = default của provider)", value=""
    )
    st.session_state.version = st.sidebar.text_input(
        "Version label", value="v3", help="Nhãn artifact version, ví dụ v0, v1, v2, v3."
    )
    st.session_state.system_prompt_path = st.sidebar.text_input(
        "system_prompt", value=str(ARTIFACTS_DIR / "system_prompt.md")
    )
    st.session_state.tools_path = st.sidebar.text_input(
        "tools.yaml", value=str(ARTIFACTS_DIR / "tools.yaml")
    )
    st.session_state.max_tool_rounds = st.sidebar.slider(
        "Max tool rounds", min_value=1, max_value=8, value=4
    )
    history_window = st.sidebar.slider("History window (cặp turn)", 0, 10, 5)

    # Build artifact version + provider + tool declarations up front so errors
    # surface immediately in the sidebar instead of mid-conversation.
    try:
        system_prompt = Path(st.session_state.system_prompt_path).read_text(encoding="utf-8")
        tool_declarations = load_tool_declarations(Path(st.session_state.tools_path))
        openai_tools = to_openai_tools(tool_declarations)
        artifact_version = build_artifact_version(
            st.session_state.version,
            Path(st.session_state.system_prompt_path),
            Path(st.session_state.tools_path),
        )
        provider = make_provider(st.session_state.provider)
    except Exception as exc:  # noqa: BLE001 - surface config errors to the user
        st.sidebar.error(f"Lỗi cấu hình: {exc}")
        return

    st.sidebar.success(f"artifact_version:\n`{artifact_version.artifact_version}`")
    st.sidebar.caption(
        f"Provider: {st.session_state.provider} | "
        f"Model: {st.session_state.model or getattr(provider, 'default_model', '?')}"
    )

    # (Re)start session whenever the version label changes so the same scenario
    # can be compared across prompt/tool versions, as the README asks.
    if (
        "transcript" not in st.session_state
        or st.session_state.get("transcript", {}).get("version") != st.session_state.version
    ):
        reset_session(artifact_version)

    if st.sidebar.button("🔄 Bắt đầu phiên mới"):
        reset_session(artifact_version)

    # ---------------- Main: chat ----------------
    st.caption(
        f"Transcript: `{st.session_state.transcript['transcript_id']}` · "
        f"{len(openai_tools)} tools declared"
    )

    # Replay previous turns.
    for entry in st.session_state.chat:
        with st.chat_message("user"):
            st.markdown(entry["user"])
        with st.chat_message("assistant"):
            st.markdown(entry.get("assistant_text") or "_(không có văn bản)_")
            _render_rounds(entry.get("rounds", []), entry.get("status"))

    user_input = st.chat_input("Nhập request nghiên cứu...")
    if not user_input:
        return

    with st.chat_message("user"):
        st.markdown(user_input)

    messages = [
        {"role": "system", "content": system_prompt},
        *trim_history(st.session_state.history, history_window),
        {"role": "user", "content": user_input},
    ]

    turn_record = {
        "turn_index": len(st.session_state.transcript["turns"]) + 1,
        "started_at": now_iso(),
        "user": user_input,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }

    with st.chat_message("assistant"):
        try:
            result = run_model_tool_loop(
                provider=provider,
                messages=messages,
                tools=openai_tools,
                model=st.session_state.model or None,
                max_tool_rounds=st.session_state.max_tool_rounds,
            )
            assistant_text = result["assistant_text"]
            turn_record.update(result)
            st.markdown(assistant_text or "_(không có văn bản)_")
            _render_rounds(result.get("rounds", []), result.get("status"))
        except Exception as exc:  # noqa: BLE001 - show provider/runtime errors inline
            turn_record.update({
                "status": "provider_error",
                "error": f"{type(exc).__name__}: {exc}",
            })
            st.error(f"Lỗi: {turn_record['error']}")

    # Persist history + transcript.
    final_text = turn_record.get("assistant_text") or ""
    st.session_state.history.append({"role": "user", "content": user_input})
    st.session_state.history.append({"role": "assistant", "content": final_text})
    st.session_state.chat.append({
        "user": user_input,
        "assistant_text": final_text,
        "rounds": turn_record.get("rounds", []),
        "tool_events": turn_record.get("tool_events", []),
        "status": turn_record.get("status"),
    })

    turn_record["ended_at"] = now_iso()
    st.session_state.transcript["turns"].append(turn_record)
    transcripts_dir = ROOT / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcripts_dir / f"{st.session_state.transcript['transcript_id']}.transcript.json"
    write_transcript(transcript_path, st.session_state.transcript)

    with st.expander("🧾 Chi tiết transcript (JSON)"):
        st.json({
            "transcript_id": st.session_state.transcript["transcript_id"],
            "artifact_version": st.session_state.transcript["artifact_version"],
            "status": turn_record.get("status"),
            "tool_events": turn_record.get("tool_events", []),
            "saved_to": str(transcript_path),
        })


def _render_rounds(rounds: list[dict], status: str | None) -> None:
    """Render each round's tool calls + results as expanders (the eval trace)."""
    if not rounds:
        return
    st.caption(f"Status: `{status}` · {len(rounds)} round(s)")
    for rnd in rounds:
        calls = rnd.get("tool_calls", [])
        results = rnd.get("tool_results", [])
        header = f"Round {rnd.get('round')} · {len(calls)} tool call(s)"
        with st.expander(header, expanded=False):
            if rnd.get("assistant_text"):
                st.markdown(rnd["assistant_text"])
            if not calls:
                st.info("Không gọi tool (câu trả lời cuối).")
                continue
            for call, res in zip(calls, results):
                tool = call.get("name")
                args = call.get("args", {})
                result = res.get("result", res)
                errored = isinstance(result, dict) and bool(result.get("error"))
                badge = "❌ error" if errored else "✅ ok"
                with st.container(border=True):
                    st.markdown(f"**🔧 {tool}** `{badge}`")
                    st.caption("Args")
                    st.json(args)
                    st.caption("Result")
                    st.json(result)


if __name__ == "__main__":
    main()
