import json
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.bots.chrome import QAFinding, QAReport, QATestCase
from parrot.bots.chrome_runner import build_parser, load_test_cases, main, run_qa


def test_build_parser_requires_test_file():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_minimal():
    parser = build_parser()
    args = parser.parse_args(["--test-file", "tests.json"])
    assert args.test_file == "tests.json"
    assert args.headless is False
    assert args.url is None
    assert args.tags is None
    assert args.junit_output is None


def test_build_parser_full():
    parser = build_parser()
    args = parser.parse_args([
        "--test-file", "tests.json",
        "--url", "http://localhost:3000",
        "--headless",
        "--tags", "smoke,critical",
        "--junit-output", "results.xml",
        "--screenshot-dir", "./screenshots",
        "--default-timeout", "30000",
        "--port", "9333",
        "--viewport", "1920x1080",
    ])
    assert args.headless is True
    assert args.tags == "smoke,critical"
    assert args.default_timeout == 30000
    assert args.port == 9333
    assert args.junit_output == "results.xml"
    assert args.screenshot_dir == "./screenshots"
    assert args.viewport == "1920x1080"


def test_load_test_cases_json(tmp_path):
    f = tmp_path / "tests.json"
    f.write_text(json.dumps([{
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
    }]))
    cases = load_test_cases(str(f))
    assert len(cases) == 1
    assert cases[0].name == "t1"
    assert isinstance(cases[0], QATestCase)


def test_load_test_cases_single_object(tmp_path):
    """A single object (not wrapped in array) should also work."""
    f = tmp_path / "tests.json"
    f.write_text(json.dumps({
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
    }))
    cases = load_test_cases(str(f))
    assert len(cases) == 1


def test_load_test_cases_with_new_fields(tmp_path):
    f = tmp_path / "tests.json"
    f.write_text(json.dumps([{
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
        "max_retries": 2, "timeout_ms": 15000, "tags": ["smoke"],
    }]))
    cases = load_test_cases(str(f))
    assert cases[0].max_retries == 2
    assert cases[0].timeout_ms == 15000
    assert cases[0].tags == ["smoke"]


def test_load_test_cases_missing_file_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        load_test_cases("/nonexistent/path/tests.json")
    assert exc_info.value.code == 2


def test_load_test_cases_invalid_json_exits_2(tmp_path):
    f = tmp_path / "tests.json"
    f.write_text("{not valid json")
    with pytest.raises(SystemExit) as exc_info:
        load_test_cases(str(f))
    assert exc_info.value.code == 2


def test_load_test_cases_yaml_missing_pyyaml_exits_2(tmp_path):
    f = tmp_path / "tests.yaml"
    f.write_text("- name: t1\n  url: /\n  steps: [s]\n  expected: e\n")
    with patch.dict("sys.modules", {"yaml": None}), pytest.raises(SystemExit) as exc_info:
        load_test_cases(str(f))
    assert exc_info.value.code == 2


def _mock_agent_ctx(report: QAReport):
    """Patch WebAgent so run_qa() drives a scripted QAReport without Chrome."""
    mock_agent = MagicMock()
    mock_agent.configure = AsyncMock()
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=False)
    mock_msg = MagicMock()
    mock_msg.output = report
    mock_agent.run_tests = AsyncMock(return_value=mock_msg)
    return mock_agent


@pytest.mark.asyncio
async def test_run_qa_all_pass_exit_code_0(tmp_path):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))

    report = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    mock_agent = _mock_agent_ctx(report)

    with patch("parrot.bots.chrome_runner.WebAgent", return_value=mock_agent):
        exit_code = await run_qa(test_file=str(test_file), headless=True)

    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_qa_with_failure_exit_code_1(tmp_path):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))

    report = QAReport(
        summary="0/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="fail", detail="nok")],
        total=1, failed=1,
    )
    mock_agent = _mock_agent_ctx(report)

    with patch("parrot.bots.chrome_runner.WebAgent", return_value=mock_agent):
        exit_code = await run_qa(test_file=str(test_file), headless=True)

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_qa_tags_forwarded_to_run_tests(tmp_path):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e", "tags": ["smoke"]},
    ]))

    report = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    mock_agent = _mock_agent_ctx(report)

    with patch("parrot.bots.chrome_runner.WebAgent", return_value=mock_agent):
        await run_qa(test_file=str(test_file), headless=True, tags=["smoke"])

    call_kwargs = mock_agent.run_tests.call_args.kwargs
    assert call_kwargs.get("tags") == ["smoke"]


@pytest.mark.asyncio
async def test_run_qa_writes_junit_output(tmp_path):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    junit_path = tmp_path / "results.xml"

    report = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    mock_agent = _mock_agent_ctx(report)

    with patch("parrot.bots.chrome_runner.WebAgent", return_value=mock_agent):
        await run_qa(
            test_file=str(test_file), headless=True, junit_output=str(junit_path),
        )

    assert junit_path.is_file()
    root = ET.fromstring(junit_path.read_text(encoding="utf-8"))
    assert root.tag == "testsuites"


@pytest.mark.asyncio
async def test_run_qa_creates_screenshot_dir(tmp_path):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    screenshot_dir = tmp_path / "shots"

    report = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    mock_agent = _mock_agent_ctx(report)

    with patch("parrot.bots.chrome_runner.WebAgent", return_value=mock_agent):
        await run_qa(
            test_file=str(test_file), headless=True,
            screenshot_dir=str(screenshot_dir),
        )

    assert screenshot_dir.is_dir()


def test_main_chrome_headless_env_var(tmp_path, monkeypatch):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    monkeypatch.setenv("CHROME_HEADLESS", "1")
    monkeypatch.setattr("sys.argv", ["chrome_runner", "--test-file", str(test_file)])

    with patch("parrot.bots.chrome_runner.run_qa", new_callable=AsyncMock) as mock_run_qa:
        mock_run_qa.return_value = 0
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 0
    assert mock_run_qa.call_args.kwargs["headless"] is True


def test_main_target_url_env_var(tmp_path, monkeypatch):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    monkeypatch.setenv("TARGET_URL", "http://app:3000")
    monkeypatch.setattr("sys.argv", ["chrome_runner", "--test-file", str(test_file)])

    with patch("parrot.bots.chrome_runner.run_qa", new_callable=AsyncMock) as mock_run_qa:
        mock_run_qa.return_value = 0
        with pytest.raises(SystemExit):
            main()

    assert mock_run_qa.call_args.kwargs["url"] == "http://app:3000"


def test_main_qa_tags_env_var(tmp_path, monkeypatch):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    monkeypatch.setenv("QA_TAGS", "smoke,critical")
    monkeypatch.setattr("sys.argv", ["chrome_runner", "--test-file", str(test_file)])

    with patch("parrot.bots.chrome_runner.run_qa", new_callable=AsyncMock) as mock_run_qa:
        mock_run_qa.return_value = 0
        with pytest.raises(SystemExit):
            main()

    assert mock_run_qa.call_args.kwargs["tags"] == ["smoke", "critical"]


def test_main_cli_flags_override_env_vars(tmp_path, monkeypatch):
    """CLI flags take precedence over env vars."""
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    monkeypatch.setenv("TARGET_URL", "http://env-url:3000")
    monkeypatch.setattr(
        "sys.argv",
        ["chrome_runner", "--test-file", str(test_file), "--url", "http://cli-url:3000"],
    )

    with patch("parrot.bots.chrome_runner.run_qa", new_callable=AsyncMock) as mock_run_qa:
        mock_run_qa.return_value = 0
        with pytest.raises(SystemExit):
            main()

    assert mock_run_qa.call_args.kwargs["url"] == "http://cli-url:3000"


def test_main_exit_code_propagates(tmp_path, monkeypatch):
    test_file = tmp_path / "tests.json"
    test_file.write_text(json.dumps([
        {"name": "t1", "url": "http://localhost", "steps": ["s"], "expected": "e"},
    ]))
    monkeypatch.setattr("sys.argv", ["chrome_runner", "--test-file", str(test_file)])

    with patch("parrot.bots.chrome_runner.run_qa", new_callable=AsyncMock) as mock_run_qa:
        mock_run_qa.return_value = 1
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
