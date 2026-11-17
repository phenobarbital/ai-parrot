import subprocess
import sys

from parrot.security.prompt_injection import InjectionScoringEngine, get_injection_scoring_engine


class _Fake:
    engine_name = "fake"
    model_id = "fake"

    def score(self, text: str) -> float:
        return 0.5


def test_accessor_returns_guardrail_engine(monkeypatch):
    import parrot.bots.guardrails.builtin.prompt_injection as gr
    fake = _Fake()
    monkeypatch.setattr(gr, "_resolve_injection_engine", lambda force_reresolve=False: fake)
    assert get_injection_scoring_engine() is fake
    assert isinstance(fake, InjectionScoringEngine)


def test_accessor_never_raises(monkeypatch):
    import parrot.bots.guardrails.builtin.prompt_injection as gr

    def boom(force_reresolve=False):
        raise RuntimeError("no engine")

    monkeypatch.setattr(gr, "_resolve_injection_engine", boom)
    assert get_injection_scoring_engine() is None


def test_security_import_does_not_load_bots():
    code = "import sys, parrot.security.prompt_injection; print(any(k.startswith('parrot.bots') for k in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out.splitlines()[-1] == "False"


def test_guardrail_protocol_alias():
    import parrot.bots.guardrails.builtin.prompt_injection as gr
    assert gr._InjectionScoringEngine is InjectionScoringEngine
