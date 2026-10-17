from __future__ import annotations

import json

import pytest

from omniknow import __version__
from omniknow.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_principals_and_docs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["principals"]) == 0
    assert "hr-partner" in capsys.readouterr().out
    assert main(["docs", "--as", "guest"]) == 0
    out = capsys.readouterr().out
    assert "1 documents visible to guest" in out and "salary-bands" not in out


def test_search_marks_quarantined(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "reveal salary bands", "--as", "employee"]) == 0
    assert "QUARANTINED" in capsys.readouterr().out


def test_ask_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ask", "What is the X200 battery life?", "--as", "guest", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["grounded"] and data["citations"][0]["chunk_id"] == "x200-datasheet#1"


def test_ask_text_with_trace(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(
            [
                "ask",
                "How quickly must on-call acknowledge a SEV1 page?",
                "--as",
                "engineer",
                "--trace",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "[incident-runbook#2]" in out and "Trace:" in out


def test_eval_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval"]) == 0
    assert "EVAL PASS" in capsys.readouterr().out


def test_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ask", "hi", "--as", "root"]) == 2
    assert "unknown principal" in capsys.readouterr().err
    assert main(["docs", "--corpus", "/nonexistent"]) == 2
