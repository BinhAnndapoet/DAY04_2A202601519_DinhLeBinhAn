# Research Agent Workbench — UI Design

## 1. Product intent

`Research Agent Workbench` is a technical Streamlit application for running the
existing Research Agent, inspecting its real tool activity, and reviewing saved
evidence. It is not a marketing site and does not replace the agent loop.

The primary experience is:

1. Configure a chat session.
2. Send a research request.
3. Read the final assistant response.
4. Inspect the actual rounds, tool calls, arguments, results, and errors.
5. Review and download the session transcript.
6. Compare real version evidence when run files exist.

All displayed chat, trace, transcript, and metric data comes from the current
session or real repository files. Sample and mock artifacts are excluded.

## 2. Existing contract

The UI imports and reuses these functions without copying or replacing their
behavior:

- `chat.run_model_tool_loop`
- `chat.write_transcript`
- `chat.trim_history`
- `versioning.build_artifact_version`
- `versioning.artifact_version_dict`
- `tools.load_tool_declarations`
- `tools.to_openai_tools`
- `providers.make_provider`

The UI reads:

- `artifacts/system_prompt.md`
- `artifacts/tools.yaml`
- `artifacts/version_log.csv`
- `runs/*.json`
- the current session transcript

The UI does not modify the system prompt, tool declarations, tool
implementations, eval cases, or agent routing.

## 3. Architecture

### 3.1 Files

```text
starter_v0/
├── app.py
├── UI_DESIGN.md
├── requirements.txt
├── .streamlit/
│   └── config.toml
├── ui/
│   ├── __init__.py
│   ├── styles.css
│   └── workbench.py
└── tests/
    └── test_ui_workbench.py
```

`app.py` is a thin Streamlit orchestrator. It initializes session state, renders
the workbench, accepts chat input, invokes the existing agent loop, and persists
turns.

`ui/workbench.py` contains pure, testable helpers for:

- initial session values;
- transcript construction;
- display-safe error sanitization;
- structured tool-event status;
- safe external URL validation;
- evidence discovery and parsing;
- transcript JSON serialization;
- small trace and metadata view models.

`ui/styles.css` contains visual tokens, responsive rules, focus states, and
Streamlit-specific presentation overrides.

`tests/test_ui_workbench.py` verifies the pure helpers without calling a model
or creating fake tool results.

### 3.2 Data flow

```text
Sidebar settings
      │
      ▼
st.chat_input ──► lazy make_provider()
      │
      ▼
system prompt + trim_history(history) + user message
      │
      ▼
run_model_tool_loop()
      │
      ├──► final assistant message
      ├──► rounds
      └──► tool_events
      │
      ▼
turn record ──► transcript["turns"].append(...)
      │
      ▼
write_transcript()
```

Provider creation happens only when the user submits a non-empty request.
Changing a widget never calls a provider or model.

## 4. Session model

The UI stores at least:

```python
messages
history
turns
transcript
transcript_path
transcript_id
provider_name
model_name
version_label
artifact_version
selected_turn_index
last_result
is_running
```

Additional internal values may include:

```python
status
session_started
last_error
history_window
max_tool_rounds
tool_declarations
openai_tools
```

One `New session` action resets chat state and creates the next transcript
identity. Normal Streamlit reruns keep the same transcript ID and never append a
duplicate turn.

Provider, model, and version remain editable before the first submitted turn.
After the first turn they are locked to preserve transcript provenance. The
user starts a new session to change them. History window and maximum tool
rounds remain visible session controls and are recorded in transcript metadata.

## 5. Transcript lifecycle

The transcript is initialized once per chat session with the schema used by
`chat.py`:

```text
transcript_id
version
artifact_version
prompt_hash
tools_hash
provider
model
system_prompt
tools
history_window
max_tool_rounds
created_at
updated_at
turns
```

Every submitted request creates one turn:

```text
turn_index
started_at
ended_at
user
status
assistant_text
rounds
tool_events
error, when applicable
```

The turn is appended exactly once. `write_transcript` updates `updated_at` and
writes UTF-8 JSON after every completed, waiting, max-round, or failed turn.
API keys and `.env` contents are never copied into session state or transcript
records.

## 6. Agent statuses

The header and response area use explicit text in addition to color:

| Agent result | UI state | Treatment |
|---|---|---|
| No active request | Ready | Neutral badge |
| Request submitted | Running | Progress indicator and status text |
| `answered` | Ready | Assistant Markdown response |
| `waiting_for_user` | Waiting for input | Assistant clarification and warning badge |
| `max_tool_rounds` | Maximum tool rounds reached | Warning panel pointing to Tool Trace |
| Provider exception | Error | Sanitized error panel; history remains intact |

Provider errors create a real `provider_error` turn. The UI never fabricates a
successful answer.

## 7. Tool Trace contract

The trace uses only:

```python
result["rounds"]
result["tool_events"]
```

Each round displays:

- round number;
- intermediate assistant text, if present;
- tool-call count;
- the round's structured tool results.

Each tool displays:

- tool-name pill;
- text status;
- arguments in a collapsed expander;
- result in a separate collapsed expander;
- error message when the structured result contains an error.

The source objects currently have this shape:

```text
round:
  round
  assistant_text
  tool_calls[]: {name, args}
  tool_results[]: {tool, args, result}

tool_event:
  tool
  args
  result
```

The display status is normalized only from structured result fields:

- `result.awaiting_user == true` → `Waiting`
- a non-empty `result.error` → `Error`
- otherwise → `Success`

This normalization is a view concern; it does not alter stored data. Tool
rounds are never inferred from assistant prose.

## 8. Information architecture

### 8.1 Header

A compact deep-slate header contains:

- `Research Agent Workbench`;
- provider;
- selected or provider-default model;
- version label;
- artifact-version badge;
- Ready, Running, Waiting for input, or Error status.

### 8.2 Sidebar

The sidebar contains:

- `New session`;
- provider selector: OpenRouter, OpenAI, Anthropic, Gemini;
- optional model input;
- version input;
- history window;
- maximum tool rounds;
- tools loaded dynamically from `tools.yaml`;
- sample queries derived from real tool capabilities;
- current transcript ID, turn count, and path.

No credential field or `.env` content is shown.

### 8.3 Main workspace

Desktop uses two primary columns:

- central chat workspace;
- narrower Tool Trace panel.

Chat uses `st.chat_message` and `st.chat_input`. Assistant content is rendered
as Markdown without enabling arbitrary HTML. Raw tool JSON never interrupts the
main conversation.

The empty chat state is short and includes three to five selectable sample
requests. A clarification is stored and displayed as a normal assistant
message, preserving history for the next user turn.

### 8.4 Evidence tabs

Below the workspace:

- **Current Trace** — a timeline for the selected or latest turn.
- **Transcript** — transcript metadata, path, and JSON download.
- **Version Evidence** — real `version_log.csv` and `runs/*.json` data only.
- **Raw JSON** — selected turn or current transcript in a collapsed expander.

When the repository has no run evidence, Version Evidence says:

`Chưa có run evidence để so sánh. Hãy chạy eval trước.`

The `samples/` directory is not an evidence source.

## 9. Visual system

The design borrows warmth, contrast, restraint, spacing, pill controls, and
input treatment from the provided Viet Heritage reference. It does not copy its
hero, imagery, heritage motifs, navigation, or storytelling sections.

```css
--color-bg: #FFFAF0;
--color-bg-muted: #F8F1E3;
--color-surface: #FFFFFF;
--color-text: #2D2820;
--color-text-muted: #776F62;
--color-deep: #24383C;
--color-accent: #9B7A3A;
--color-accent-soft: #F6D99B;
--color-border: #B8AA8D;
--color-form-border: #E5E7EB;
--color-error: #B94D35;
--color-warning: #C19A4B;
```

Rules:

- Warm cream page background and flat white working surfaces.
- System sans-serif for chat, controls, and trace.
- A restrained serif fallback only for the main workbench title.
- Monospace for JSON.
- `8px` card radius and pill buttons/badges.
- Gold is reserved for focus, selected, and primary states.
- Dividers replace excessive floating cards.
- Shadows remain subtle and warm.
- Body text is at least `14px`; captions are never below `12px`.
- Keyboard focus uses a visible accent outline and light glow.
- Reduced-motion users receive no nonessential animation.

## 10. Responsive behavior

Desktop:

- Streamlit sidebar remains available.
- Chat and Tool Trace render side by side.
- Evidence tabs span the content width.

Tablet:

- The right trace column becomes narrower or moves beneath the chat based on
  available width.
- Controls remain touch-friendly and wrapping is allowed.

Mobile at `360px`:

- One content column.
- Streamlit's collapsed sidebar acts as the settings drawer.
- Tool Trace appears below chat and remains accessible in evidence tabs.
- Chat input is full width.
- Buttons and inputs have at least a `44px` practical touch height.
- JSON containers use wrapping, horizontal scrolling, and bounded height.
- No fixed-width child may create page-level horizontal overflow.

## 11. Security and accessibility

- Never read or render `.env`.
- Never store or display API keys.
- Sanitize provider exceptions before display and transcript persistence.
- Redact credential-like query parameters, bearer tokens, and known provider
  key patterns from errors.
- Structured external links render only when `urlparse(url).scheme` is `http`
  or `https`.
- Do not use arbitrary model-authored HTML.
- Do not auto-run the provider or tools during a rerun.
- Preserve the existing confirmation behavior in the agent loop.
- Status always has a text label; color is supplementary.
- Focus states are visible and contrast remains readable.

## 12. Test strategy

Automated unit tests cover:

- complete initial state shape;
- one stable transcript ID per session;
- transcript metadata compatibility;
- URL allowlist behavior;
- error redaction;
- tool-event status normalization;
- real-evidence discovery excluding `samples/`;
- empty evidence behavior;
- transcript JSON serialization.

Static/runtime checks:

```powershell
python -m py_compile app.py ui\workbench.py
python -m unittest discover -s tests -v
streamlit run app.py
```

Browser checks cover desktop and `360px` mobile widths:

- app startup;
- empty state;
- responsive overflow;
- new-session behavior;
- message submission;
- provider-error survival when credentials are unavailable;
- transcript creation and download;
- trace expanders when a live credential-backed turn is available.

Live provider success, clarification, and real tool execution are tested only
when valid credentials exist. Missing credentials are reported as a limitation,
not replaced by fake provider or tool results.
