from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ui.workbench import (
    build_initial_state,
    build_transcript,
    extract_safe_links,
    is_safe_external_url,
    json_for_display,
    load_version_evidence,
    make_transcript_identity,
    queue_submission,
    sanitize_error,
    transcript_download_bytes,
    tool_event_error,
    tool_event_status,
)


class WorkbenchStateTests(unittest.TestCase):
    def test_initial_state_contains_required_contract_keys(self) -> None:
        state = build_initial_state()

        required = {
            "messages",
            "history",
            "turns",
            "transcript",
            "transcript_path",
            "transcript_id",
            "provider_name",
            "model_name",
            "version_label",
            "artifact_version",
            "selected_turn_index",
            "last_result",
            "is_running",
            "pending_submission",
        }
        self.assertLessEqual(required, set(state))

    def test_initial_state_returns_fresh_mutable_containers(self) -> None:
        first = build_initial_state()
        second = build_initial_state()

        first["messages"].append({"role": "user", "content": "hello"})

        self.assertEqual(second["messages"], [])

    def test_transcript_identity_is_unique_for_same_timestamp(self) -> None:
        timestamp = datetime(2026, 7, 29, 9, 0, 0)

        first = make_transcript_identity("v3", "openrouter", now=timestamp)
        second = make_transcript_identity("v3", "openrouter", now=timestamp)

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("v3_openrouter_20260729T090000000000_"))

    def test_build_transcript_matches_chat_contract(self) -> None:
        transcript = build_transcript(
            transcript_id="session-id",
            artifact={
                "version": "v3",
                "artifact_version": "v3+pabc+tdef",
                "prompt_hash": "abc",
                "tools_hash": "def",
            },
            provider="openrouter",
            model="openai/gpt-4o-mini",
            system_prompt_path=Path("artifacts/system_prompt.md"),
            tools_path=Path("artifacts/tools.yaml"),
            history_window=5,
            max_tool_rounds=4,
            created_at="2026-07-29T09:00:00",
        )

        self.assertEqual(transcript["transcript_id"], "session-id")
        self.assertEqual(transcript["version"], "v3")
        self.assertEqual(transcript["artifact_version"], "v3+pabc+tdef")
        self.assertEqual(transcript["provider"], "openrouter")
        self.assertEqual(transcript["model"], "openai/gpt-4o-mini")
        self.assertEqual(transcript["turns"], [])
        self.assertEqual(transcript["created_at"], transcript["updated_at"])

    def test_queue_submission_sets_running_state_once(self) -> None:
        state = build_initial_state()

        queued = queue_submission(state, "  research AI agents  ")
        duplicate = queue_submission(state, "second request")

        self.assertTrue(queued)
        self.assertFalse(duplicate)
        self.assertEqual(state["pending_submission"], "research AI agents")
        self.assertTrue(state["is_running"])
        self.assertTrue(state["session_started"])
        self.assertEqual(state["status"], "Running")


class WorkbenchSecurityTests(unittest.TestCase):
    def test_external_url_allows_only_http_and_https(self) -> None:
        self.assertTrue(is_safe_external_url("https://example.com/source"))
        self.assertTrue(is_safe_external_url("http://example.com/source"))
        self.assertFalse(is_safe_external_url("javascript:alert(1)"))
        self.assertFalse(is_safe_external_url("file:///C:/secret"))
        self.assertFalse(is_safe_external_url("https:///missing-host"))

    def test_error_sanitizer_redacts_bearer_and_provider_keys(self) -> None:
        raw = (
            "Authorization: Bearer secret-token-value "
            "openai=sk-proj-abcdefghijklmnop "
            "google=AIza1234567890abcdefghijklmnop"
        )

        safe = sanitize_error(raw)

        self.assertNotIn("secret-token-value", safe)
        self.assertNotIn("sk-proj-abcdefghijklmnop", safe)
        self.assertNotIn("AIza1234567890abcdefghijklmnop", safe)
        self.assertIn("[REDACTED]", safe)

    def test_error_sanitizer_keeps_safe_env_variable_name(self) -> None:
        safe = sanitize_error("Missing API key env var: OPENAI_API_KEY")

        self.assertIn("OPENAI_API_KEY", safe)

    def test_error_sanitizer_redacts_credential_query_parameters(self) -> None:
        safe = sanitize_error(
            "Request failed: https://example.com?q=ok&api_key=topsecret&token=alsosecret"
        )

        self.assertNotIn("topsecret", safe)
        self.assertNotIn("alsosecret", safe)

    def test_structured_tool_event_status_and_error(self) -> None:
        waiting = {"result": {"awaiting_user": True}}
        failed = {"result": {"error": "TimeoutError", "message": "timed out"}}
        successful = {"result": {"items": []}}

        self.assertEqual(tool_event_status(waiting), "waiting")
        self.assertEqual(tool_event_status(failed), "error")
        self.assertEqual(tool_event_status(successful), "success")
        self.assertEqual(tool_event_error(failed), "TimeoutError: timed out")
        self.assertIsNone(tool_event_error(successful))

    def test_json_for_display_is_utf8_and_bounded(self) -> None:
        rendered = json_for_display({"message": "xin chào", "payload": "x" * 9000})

        self.assertIn("xin chào", rendered)
        self.assertLessEqual(len(rendered), 8200)
        self.assertTrue(rendered.endswith("...<truncated>"))

    def test_safe_links_are_extracted_from_structured_results_only(self) -> None:
        links = extract_safe_links({
            "items": [
                {"title": "Nguồn A", "url": "https://example.com/a"},
                {"source": "Nguồn B", "url": "http://example.com/b"},
                {"title": "Unsafe", "url": "javascript:alert(1)"},
                {"title": "Duplicate", "url": "https://example.com/a"},
            ]
        })

        self.assertEqual(links, [
            {"label": "Nguồn A", "url": "https://example.com/a"},
            {"label": "Nguồn B", "url": "http://example.com/b"},
        ])

    def test_transcript_download_is_utf8_json(self) -> None:
        payload = transcript_download_bytes({"assistant_text": "xin chào"})

        self.assertEqual(
            json.loads(payload.decode("utf-8")),
            {"assistant_text": "xin chào"},
        )
        self.assertIn("xin chào".encode("utf-8"), payload)


class WorkbenchEvidenceTests(unittest.TestCase):
    def test_header_only_version_log_has_no_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "version_log.csv").write_text(
                "version,metric_name,metric_before,metric_after,run_file\n",
                encoding="utf-8",
            )

            evidence = load_version_evidence(root)

        self.assertFalse(evidence["has_evidence"])
        self.assertEqual(evidence["version_rows"], [])
        self.assertEqual(evidence["runs"], [])

    def test_reads_only_real_version_log_and_direct_run_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = root / "artifacts"
            runs = root / "runs"
            samples = root / "samples" / "runs"
            artifacts.mkdir()
            runs.mkdir()
            samples.mkdir(parents=True)
            (artifacts / "version_log.csv").write_text(
                "version,metric_name,metric_before,metric_after,run_file\n"
                "v1,case_accuracy,0.4,0.7,runs/v1-base.json\n",
                encoding="utf-8",
            )
            (runs / "v1-base.json").write_text(
                json.dumps({
                    "version": "v1",
                    "artifact_version": "v1+pabc+tdef",
                    "summary": {"case_accuracy": 0.7},
                }),
                encoding="utf-8",
            )
            (samples / "mock.json").write_text(
                json.dumps({"version": "mock", "summary": {"case_accuracy": 1}}),
                encoding="utf-8",
            )

            evidence = load_version_evidence(root)

        self.assertTrue(evidence["has_evidence"])
        self.assertEqual([row["version"] for row in evidence["version_rows"]], ["v1"])
        self.assertEqual([run["filename"] for run in evidence["runs"]], ["v1-base.json"])
        self.assertEqual(evidence["runs"][0]["summary"], {"case_accuracy": 0.7})

    def test_malformed_run_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs = root / "runs"
            runs.mkdir()
            (runs / "broken.json").write_text("{not-json", encoding="utf-8")

            evidence = load_version_evidence(root)

        self.assertFalse(evidence["has_evidence"])
        self.assertEqual(evidence["runs"], [])
        self.assertEqual(len(evidence["errors"]), 1)
        self.assertIn("broken.json", evidence["errors"][0])


class AppContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app_path = Path(__file__).resolve().parents[1] / "app.py"

    def test_app_reuses_every_required_contract_function(self) -> None:
        self.assertTrue(self.app_path.is_file(), "app.py must exist")
        source = self.app_path.read_text(encoding="utf-8")

        required = {
            "run_model_tool_loop",
            "write_transcript",
            "trim_history",
            "build_artifact_version",
            "artifact_version_dict",
            "load_tool_declarations",
            "to_openai_tools",
            "make_provider",
        }
        for name in required:
            with self.subTest(name=name):
                self.assertIn(name, source)

    def test_app_does_not_define_a_second_agent_loop(self) -> None:
        self.assertTrue(self.app_path.is_file(), "app.py must exist")
        tree = ast.parse(self.app_path.read_text(encoding="utf-8"))
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "run_model_tool_loop"
        ]

        self.assertEqual(definitions, [])


class RootEntrypointContractTests(unittest.TestCase):
    def test_root_entrypoint_delegates_to_existing_workbench(self) -> None:
        entrypoint = Path(__file__).resolve().parents[2] / "src" / "app.py"

        self.assertTrue(entrypoint.is_file(), "src/app.py must exist")
        source = entrypoint.read_text(encoding="utf-8")
        tree = ast.parse(source)

        self.assertIn("starter_v0", source)
        self.assertIn("runpy.run_path", source)
        self.assertFalse(any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "run_model_tool_loop"
            for node in ast.walk(tree)
        ))


if __name__ == "__main__":
    unittest.main()
