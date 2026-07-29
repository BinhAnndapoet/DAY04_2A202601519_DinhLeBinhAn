# Streamlit Entrypoint Integration Design

## Goal

Make the existing Research Agent Workbench runnable from the repository root
with:

```powershell
streamlit run src/app.py
```

The integration must preserve the existing UI, agent loop, provider behavior,
tool registry, transcript format, and evaluation data.

## Existing ownership

| Contributor | Existing work retained |
|---|---|
| BinhAnndapoet | Multi-step agent/chat support, result summarization, `think` tool, prompt and tool declarations |
| chaubaokhanh12 | Ten group evaluation cases and the recorded v3 group run |
| ninhhh1011 | Streamlit Workbench, UI helpers, styling, transcript/evidence views, and UI contract tests |

## Architecture

`src/app.py` is a compatibility composition entry point. It resolves paths from
its own location with `pathlib.Path`, places `starter_v0` on the Python import
path, and executes the existing `starter_v0/app.py` in the current Streamlit
process.

The existing application remains the single owner of session state, rendering,
provider creation, transcript persistence, and calls to
`chat.run_model_tool_loop`.

```text
src/app.py
  -> starter_v0/app.py
     -> chat.run_model_tool_loop
        -> provider.complete
        -> TOOL_FUNCTIONS
     -> write_transcript
     -> load_version_evidence
```

## Interface adapter

The adapter uses `Path(__file__).resolve()` to derive the repository and
`starter_v0` paths. It does not contain UI markup, business logic, tool logic,
provider logic, or a second agent loop.

`runpy.run_path` executes the existing application with its original file path,
so `starter_v0/app.py` continues resolving `artifacts/`, `runs/`, `transcripts/`,
and `ui/styles.css` relative to `starter_v0`.

## Error handling

The entry point fails clearly if `starter_v0/app.py` is missing. Runtime
provider, tool, transcript, and configuration errors remain handled by the
existing Workbench. No mock or fallback response is introduced.

## Tests

Add a contract test that verifies:

- `src/app.py` exists;
- it targets `starter_v0/app.py`;
- it uses `pathlib.Path`;
- it does not define `run_model_tool_loop`.

Run the existing `unittest` suite and Python compilation checks. Finally start
Streamlit from the repository root using `src/app.py` and verify its health
endpoint.

## Scope

Only the new entry point and its contract test are changed. Existing evaluation
cases, generated transcripts, provider modules, tool implementations, UI
layout, and application logic are not modified.
