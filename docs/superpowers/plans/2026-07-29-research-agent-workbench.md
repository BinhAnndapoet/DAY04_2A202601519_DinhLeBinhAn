# Research Agent Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user did not authorize sub-agent delegation, commits, or pushes.

**Goal:** Build a responsive Streamlit workbench that reuses the existing Research Agent loop, exposes real tool traces and evidence, and persists contract-compatible transcripts.

**Architecture:** Keep `app.py` as the Streamlit controller and place pure state, security, transcript, trace, and evidence helpers in `ui/workbench.py`. The controller lazily creates a provider only inside the chat-submit path and passes the existing history and declarations into `run_model_tool_loop`; all testable transformations remain independent of Streamlit.

**Tech Stack:** Python 3, Streamlit, standard-library `unittest`, CSS, existing provider/tool modules.

---

## File map

| Path | Responsibility |
|---|---|
| `starter_v0/app.py` | Streamlit rendering, session orchestration, lazy provider call, transcript write |
| `starter_v0/ui/workbench.py` | Pure state, transcript, sanitization, URL, trace, and evidence helpers |
| `starter_v0/ui/styles.css` | Design tokens, Streamlit overrides, responsive and accessibility rules |
| `starter_v0/ui/__init__.py` | Package marker and public helper exports |
| `starter_v0/.streamlit/config.toml` | Warm Streamlit theme and safe server/browser defaults |
| `starter_v0/tests/test_ui_workbench.py` | Unit coverage for all pure workbench behavior |
| `starter_v0/requirements.txt` | Add Streamlit dependency |

No change is permitted in `chat.py`, `agent.py`, `versioning.py`,
`tools/__init__.py`, prompt/tool artifacts, providers, or eval data.

### Task 1: Add dependency and configuration scaffold

**Files:**

- Modify: `starter_v0/requirements.txt`
- Create: `starter_v0/ui/__init__.py`
- Create: `starter_v0/.streamlit/config.toml`

- [ ] **Step 1: Add the required dependency**

Append exactly:

```text
streamlit>=1.30.0
```

- [ ] **Step 2: Add the UI package marker**

Create `starter_v0/ui/__init__.py` with:

```python
"""Presentation helpers for the Research Agent Workbench."""
```

- [ ] **Step 3: Add Streamlit configuration**

Create `starter_v0/.streamlit/config.toml` with:

```toml
[theme]
base = "light"
primaryColor = "#9B7A3A"
backgroundColor = "#FFFAF0"
secondaryBackgroundColor = "#F8F1E3"
textColor = "#2D2820"
font = "sans serif"

[browser]
gatherUsageStats = false

[server]
headless = true
```

- [ ] **Step 4: Verify the dependency/config diff**

Run:

```powershell
git diff --check
git diff -- starter_v0/requirements.txt starter_v0/.streamlit/config.toml starter_v0/ui/__init__.py
```

Expected: no whitespace errors; only the requested dependency and configuration files appear.

### Task 2: Build pure state, transcript, security, and trace helpers with TDD

**Files:**

- Create: `starter_v0/tests/test_ui_workbench.py`
- Create: `starter_v0/ui/workbench.py`

- [ ] **Step 1: Write failing tests for state and transcript construction**

Start `tests/test_ui_workbench.py` with tests that import:

```python
from ui.workbench import (
    build_initial_state,
    build_transcript,
    make_transcript_identity,
)
```

The assertions must prove:

```python
required = {
    "messages", "history", "turns", "transcript", "transcript_path",
    "transcript_id", "provider_name", "model_name", "version_label",
    "artifact_version", "selected_turn_index", "last_result",
    "is_running",
}
assert required <= set(build_initial_state())

first = make_transcript_identity("v3", "openrouter", now=datetime(2026, 7, 29, 9, 0, 0))
second = make_transcript_identity("v3", "openrouter", now=datetime(2026, 7, 29, 9, 0, 0))
assert first != second

assert transcript["transcript_id"] == "session-id"
assert transcript["turns"] == []
assert transcript["provider"] == "openrouter"
assert transcript["artifact_version"] == "v3+pabc+tdef"
```

- [ ] **Step 2: Run the state tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_workbench.WorkbenchStateTests -v
```

Expected: import failure because `ui.workbench` does not exist.

- [ ] **Step 3: Implement minimal state and transcript helpers**

Implement these stable APIs in `ui/workbench.py`:

```python
def make_transcript_identity(
    version: str,
    provider: str,
    *,
    now: datetime | None = None,
) -> str: ...

def build_initial_state() -> dict[str, Any]: ...

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
) -> dict[str, Any]: ...
```

`make_transcript_identity` combines safe version/provider slugs, a microsecond
timestamp, and a short UUID suffix. `build_initial_state` supplies independent
empty lists/dicts. `build_transcript` matches the top-level schema from
`chat.py`.

- [ ] **Step 4: Run the state tests and verify GREEN**

Run the same unittest command.

Expected: all state tests pass.

- [ ] **Step 5: Write failing security and trace tests**

Add tests for:

```python
is_safe_external_url("https://example.com") is True
is_safe_external_url("http://example.com") is True
is_safe_external_url("javascript:alert(1)") is False
is_safe_external_url("file:///C:/secret") is False

sanitize_error("Authorization: Bearer secret-token") does not contain "secret-token"
sanitize_error("sk-proj-abcdefghijklmnop") does not contain the key
sanitize_error("Missing API key env var: OPENAI_API_KEY") keeps the safe variable name

tool_event_status({"result": {"awaiting_user": True}}) == "waiting"
tool_event_status({"result": {"error": "TimeoutError"}}) == "error"
tool_event_status({"result": {"items": []}}) == "success"
```

- [ ] **Step 6: Run security/trace tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_workbench.WorkbenchSecurityTests -v
```

Expected: missing helper imports or assertions fail.

- [ ] **Step 7: Implement security and trace helpers**

Implement:

```python
def is_safe_external_url(value: str) -> bool: ...
def sanitize_error(value: BaseException | str) -> str: ...
def tool_event_status(event: dict[str, Any]) -> str: ...
def tool_event_error(event: dict[str, Any]) -> str | None: ...
def json_for_display(value: Any) -> str: ...
```

Use `urllib.parse.urlparse`, bounded output, and regular expressions that redact
bearer credentials, common `sk-...` keys, Google `AIza...` keys, and credential
query parameters. Preserve exception type but never the raw credential.

- [ ] **Step 8: Run all helper tests and verify GREEN**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

### Task 3: Add real evidence discovery with TDD

**Files:**

- Modify: `starter_v0/tests/test_ui_workbench.py`
- Modify: `starter_v0/ui/workbench.py`

- [ ] **Step 1: Write failing evidence tests**

Use `tempfile.TemporaryDirectory` to create:

```text
artifacts/version_log.csv
runs/v1-base.json
samples/runs/mock.json
```

Assert that:

- a header-only CSV plus no `runs/*.json` returns `has_evidence == False`;
- rows in `version_log.csv` are returned as real version rows;
- only direct `runs/*.json` files are returned;
- `samples/` is never scanned;
- malformed run JSON yields a bounded file error instead of crashing.

- [ ] **Step 2: Run evidence tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_workbench.WorkbenchEvidenceTests -v
```

Expected: missing `load_version_evidence`.

- [ ] **Step 3: Implement evidence loading**

Implement:

```python
def load_version_evidence(root: Path) -> dict[str, Any]:
    """Read only artifacts/version_log.csv and runs/*.json."""
```

Return:

```python
{
    "has_evidence": bool,
    "version_rows": list[dict[str, str]],
    "runs": list[dict[str, Any]],
    "errors": list[str],
}
```

Each run item contains the real path, version/artifact metadata, summary, and
top-level data needed by the evidence table. Do not synthesize metrics.

- [ ] **Step 4: Run all tests and verify GREEN**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

### Task 4: Implement Streamlit orchestration

**Files:**

- Create: `starter_v0/app.py`

- [ ] **Step 1: Add static contract test**

Add a test that parses `app.py` as text and asserts it contains calls/imports
for:

```text
run_model_tool_loop
write_transcript
trim_history
build_artifact_version
artifact_version_dict
load_tool_declarations
to_openai_tools
make_provider
```

Also assert `app.py` does not define a second function named
`run_model_tool_loop`.

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_workbench.AppContractTests -v
```

Expected: `app.py` is missing.

- [ ] **Step 3: Implement app initialization and rendering**

Create `app.py` with:

```python
st.set_page_config(
    page_title="Research Agent Workbench",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)
```

Then:

- load CSS from `ui/styles.css`;
- initialize each required session key only when absent;
- read prompt and tools paths without changing them;
- build the artifact version from current locked settings;
- render a compact header;
- render sidebar controls and dynamic tool declarations;
- disable provider/model/version after the first submitted turn;
- implement `New session` as a complete state reset followed by `st.rerun()`;
- render chat history with `st.chat_message`;
- render an empty state and sample-query buttons;
- render trace and evidence surfaces from structured state.

- [ ] **Step 4: Implement the single submit path**

Inside the chat-input handler:

1. Reject an empty input.
2. Append one user display message.
3. Create one turn record with `status="started"`.
4. Create the transcript once if missing.
5. Set `is_running=True` and status `Running`.
6. Call `make_provider(provider_name)` only here.
7. Resolve `selected_model = model_input or provider.default_model`.
8. Build messages from system prompt, `trim_history`, and current user text.
9. Call `run_model_tool_loop` exactly once.
10. Update turn, messages, history, `last_result`, and selected turn.
11. For provider exceptions, call `sanitize_error`, keep existing chat/history,
    set `provider_error`, and append a visible error assistant record.
12. Set `ended_at`, append the turn once, call `write_transcript`, and clear the
    running flag.

- [ ] **Step 5: Implement status-specific UI**

Render:

- clarification as a normal assistant message;
- a warning for `max_tool_rounds`;
- a visible provider-error panel without a fake answer;
- `No tool called` when a real result has an empty trace;
- structured tool errors inside their event rows;
- transcript metadata/download only after a transcript exists;
- the exact Vietnamese empty state when real version evidence is absent.

- [ ] **Step 6: Run contract and syntax checks**

Run:

```powershell
python -m py_compile app.py ui\workbench.py
python -m unittest discover -s tests -v
```

Expected: compilation succeeds and all tests pass.

### Task 5: Add the complete responsive visual layer

**Files:**

- Create: `starter_v0/ui/styles.css`

- [ ] **Step 1: Add design tokens and base surfaces**

Define the approved color variables, `8px` spacing rhythm, warm background,
deep header, flat white chat surfaces, system sans-serif UI stack, serif title
fallback, and monospace JSON.

- [ ] **Step 2: Style interaction and status components**

Add:

- pill buttons and badges;
- visible `:focus-visible` outlines;
- beige user message and bordered white assistant message;
- muted success/waiting/error treatments with text labels;
- divider-led trace rows;
- bounded JSON containers and collapsed expanders;
- `44px` practical control heights;
- light, warm shadows only where hierarchy requires them.

- [ ] **Step 3: Add responsive and reduced-motion rules**

At tablet and mobile widths:

- allow Streamlit columns to stack;
- remove fixed minimum widths;
- constrain code/JSON to the viewport;
- keep chat input full width;
- reduce gutters to `16px`;
- prevent page-level horizontal overflow at `360px`.

Use:

```css
@media (max-width: 768px) { ... }
@media (max-width: 480px) { ... }
@media (prefers-reduced-motion: reduce) { ... }
```

- [ ] **Step 4: Validate CSS and static app checks**

Run:

```powershell
git diff --check
python -m py_compile app.py ui\workbench.py
python -m unittest discover -s tests -v
```

Expected: no whitespace errors, compile errors, or test failures.

### Task 6: Install, launch, and perform browser QA

**Files:**

- Verify all files from Tasks 1–5.

- [ ] **Step 1: Install project dependencies**

Run from `starter_v0`:

```powershell
python -m pip install -r requirements.txt
```

Expected: Streamlit and existing provider/tool dependencies install without a
broken requirement.

- [ ] **Step 2: Launch Streamlit**

Run:

```powershell
streamlit run app.py
```

Expected: Streamlit reports a healthy local URL at `http://localhost:8501`.

- [ ] **Step 3: Test desktop empty and error states**

In the browser verify:

- header metadata and Ready status;
- dynamic tool list;
- empty chat and sample prompts;
- empty evidence message;
- no API key or `.env` content;
- sending without credentials creates a real provider-error turn without
  crashing or clearing history;
- transcript metadata and download control appear;
- `New session` resets the transcript identity.

- [ ] **Step 4: Test `360px` responsive behavior**

Set viewport width to `360px` and verify:

- one-column layout;
- collapsed/mobile settings access;
- full-width chat input;
- trace below the chat or in evidence tabs;
- no page-level horizontal overflow;
- JSON is internally scrollable and does not widen the page.

- [ ] **Step 5: Test live-provider behavior only when credentials exist**

Without reading or displaying `.env`, submit:

1. a normal research query;
2. a request that triggers a tool;
3. a request that requires clarification.

Verify real assistant output, tool name/args/result, waiting history continuity,
and transcript updates. If credentials are unavailable, record these checks as
not executable and do not mock them.

- [ ] **Step 6: Final scope and secret audit**

Run:

```powershell
git status --short
git diff --check
git diff --name-only
rg -n "API_KEY|Bearer |sk-|AIza" starter_v0/app.py starter_v0/ui starter_v0/tests starter_v0/UI_DESIGN.md
python -m py_compile app.py ui\workbench.py
python -m unittest discover -s tests -v
```

Expected:

- only approved UI/config/test/dependency/design/plan files changed;
- source contains only intentional redaction patterns or safe environment
  variable names;
- no eval, prompt, tool declaration, provider, or agent-loop file changed;
- compilation and tests pass.

No commit or push is performed.
