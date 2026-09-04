"""TASK-2854: core's ``pyproject.toml`` no longer pins any SDK a satellite
now owns exclusively, and ``llms`` resolves to all 15 satellites.

Post-review hardening (code review of FEAT-523): the original version of
this test only scanned ``project.dependencies`` — it would have missed a
stray SDK pin left inside an ``optional-dependencies`` extras group (which
is exactly how ``google-genai>=2.18.1`` survived, unused, inside the
``mcp`` extra through TASK-2854's own extras rewrite). Now scans every
extras group too, not just the base dependency list.
"""

import pathlib
import re
import tomllib

# .../packages/ai-parrot/tests/unit/clients/test_core_has_no_sdk_pins.py
# parents[3] == .../packages/ai-parrot
_CORE_PYPROJECT = pathlib.Path(__file__).resolve().parents[3] / "pyproject.toml"

_FORBIDDEN_SDKS = (
    "anthropic",
    "google-genai",
    "groq",
    "xai-sdk",
    "zai-sdk",
    "aioboto3",
    "claude-agent-sdk",
)

_DIST_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+")


def _dist_name(spec: str) -> str:
    """Extract the leading distribution name from a requirement spec string.

    ``"anthropic[aiohttp,aws]>=0.109.0,<1.0.0"`` -> ``"anthropic"``,
    ``"ai-parrot-client-anthropic"`` -> ``"ai-parrot-client-anthropic"``.
    A plain substring check (``"anthropic" in spec``) would false-positive
    on the satellite's own package name, which legitimately *contains* the
    SDK name as a suffix — comparing exact leading dist names avoids that.
    """
    m = _DIST_NAME_RE.match(spec.strip())
    return (m.group(0) if m else spec).lower()


def test_core_pins():
    py = tomllib.loads(_CORE_PYPROJECT.read_text())
    deps = " ".join(py["project"]["dependencies"])
    for sdk in _FORBIDDEN_SDKS:
        assert sdk not in deps
    assert "openai" in deps and "tiktoken" in deps
    assert len(py["project"]["optional-dependencies"]["llms"]) == 15


def test_core_optional_dependencies_have_no_sdk_pins():
    """No extras group may pin an SDK a satellite now owns exclusively.

    A satellite's own extra (e.g. ``anthropic = ["ai-parrot-client-anthropic"]``)
    is expected and excluded — those reference the *satellite package*, not
    the raw provider SDK string.
    """
    py = tomllib.loads(_CORE_PYPROJECT.read_text())
    for extra_name, specs in py["project"]["optional-dependencies"].items():
        names = {_dist_name(s) for s in specs}
        for sdk in _FORBIDDEN_SDKS:
            assert sdk not in names, (
                f"extras group '{extra_name}' pins '{sdk}' directly — "
                "that SDK is now owned exclusively by its ai-parrot-client-* "
                "satellite; depend on the satellite package instead."
            )
