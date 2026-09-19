"""Deterministic fixture trees for the FEAT-580 M5 pilot tasks.

Every builder below returns a :class:`ScenarioFixture`: a small,
self-contained Python source tree, plus -- for the eight change/fix
tasks -- a plausible-but-wrong ``counterexample`` and a correct
``expected_fix`` for its single editable file. Materializing a fixture
never starts a process, spawns Pyright, or reaches a network: it only
writes plain text files under a caller-supplied directory (spec §3 M5,
"Build small deterministic fixture generators ... whose expected outcomes
do not depend on a particular retrieval arm").

Each fixture also ships its own ``check.py`` acceptance script, so a
task's pass/fail check exercises real runtime behavior of the resulting
tree rather than a text match on what an agent claims to have found or
changed (spec §5, "must test outcomes, not count whether LSP was
called"). ``fixtures/acceptance.py`` runs that script; this module never
imports or executes it.

The twelve scenarios below are fixed at four investigation, four change
and four fix tasks (spec §2 Evaluation contract), and together exercise
every retrieval shape the spec calls out by name: aliases
(``inv-alias-reexport``), inherited receivers
(``inv-inherited-receiver``), namespaces (``inv-namespace-import``),
decorators (``chg-decorator-wrapper``), registry strings
(``chg-registry-dispatch``) and the unavailable-server fallback
(``fix-unavailable-server``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

__all__ = (
    "FixtureFile",
    "ScenarioFixture",
    "INVESTIGATION_SCENARIO_IDS",
    "CHANGE_SCENARIO_IDS",
    "FIX_SCENARIO_IDS",
    "SCENARIO_IDS",
    "build_fixture",
)


@dataclass(frozen=True)
class FixtureFile:
    """One file materialized inside a scenario's fixture tree.

    Attributes:
        relative_path: POSIX-style path relative to the fixture root.
        content: Exact file content, including any trailing newline.
    """

    relative_path: str
    content: str


@dataclass(frozen=True)
class ScenarioFixture:
    """A deterministic, self-contained fixture tree for one pilot task.

    Attributes:
        scenario_id: The stable task id this fixture belongs to (matches
            the ``id``/``fixture`` fields in ``tasks.yaml``).
        category: One of ``"investigation"``, ``"change"``, ``"fix"``.
        files: Every file materialized before an attempt begins, used in
            a fixed, sorted order so hashing is reproducible.
        entry_point: The repository-relative path a change/fix task must
            edit. ``None`` for read-only investigation tasks.
        expected_fix: The independently authored, correct replacement
            content for ``entry_point``. ``None`` for investigation
            tasks.
        counterexample: A distinct, plausible-but-still-wrong replacement
            content for ``entry_point``, used to prove the acceptance
            check can fail (fixtures must not be vacuous). ``None`` for
            investigation tasks.
        check_relative_path: Path to the bundled acceptance script,
            always present, run as ``python <check_relative_path>``.
        includes: Free-form coverage tags this fixture demonstrates (for
            example ``"alias"``, ``"namespace"``, ``"decorator"``,
            ``"registry"``).
    """

    scenario_id: str
    category: str
    files: tuple[FixtureFile, ...]
    entry_point: str | None = None
    expected_fix: str | None = None
    counterexample: str | None = None
    check_relative_path: str = "check.py"
    includes: tuple[str, ...] = field(default_factory=tuple)

    def content_sha256(self) -> str:
        """Return a deterministic hash over every fixture file's path/content.

        The hash covers exactly the materialized baseline tree, never the
        ``expected_fix``/``counterexample`` variants (which are reviewed
        separately), so a pinned value in ``tasks.yaml`` catches any
        accidental drift in what an attempt actually starts from.
        """
        digest = hashlib.sha256()
        for entry in sorted(self.files, key=lambda f: f.relative_path):
            digest.update(entry.relative_path.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(entry.content.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def materialize(self, root: Path) -> None:
        """Write every fixture file under ``root``, creating parent directories."""
        for entry in self.files:
            target = root / entry.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(entry.content, encoding="utf-8")

    def apply_variant(self, root: Path, variant: str) -> None:
        """Overwrite ``entry_point`` under ``root`` with a named variant.

        Args:
            root: A directory already materialized via :meth:`materialize`.
            variant: ``"baseline"`` (no-op; the materialized content
                already stands), ``"expected_fix"``, or
                ``"counterexample"``.

        Raises:
            ValueError: If this fixture has no ``entry_point`` (a
                read-only investigation task), ``variant`` is unknown, or
                the requested variant's content is unset.
        """
        if self.entry_point is None:
            raise ValueError(f"{self.scenario_id} has no editable entry_point")
        if variant == "baseline":
            return
        if variant == "expected_fix":
            content = self.expected_fix
        elif variant == "counterexample":
            content = self.counterexample
        else:
            raise ValueError(f"unknown variant: {variant!r}")
        if content is None:
            raise ValueError(f"{self.scenario_id} has no {variant!r} content")
        (root / self.entry_point).write_text(content, encoding="utf-8")


def _fixture(
    scenario_id: str,
    category: str,
    files: Mapping[str, str],
    *,
    entry_point: str | None = None,
    expected_fix: str | None = None,
    counterexample: str | None = None,
    includes: tuple[str, ...] = (),
) -> ScenarioFixture:
    ordered = tuple(FixtureFile(relative_path=path, content=content) for path, content in files.items())
    return ScenarioFixture(
        scenario_id=scenario_id,
        category=category,
        files=ordered,
        entry_point=entry_point,
        expected_fix=expected_fix,
        counterexample=counterexample,
        includes=includes,
    )


# --------------------------------------------------------------------------- #
# Investigation: duplicate names, alias/re-export, namespace-package import,
# inherited receiver. Read-only -- no entry_point/expected_fix/counterexample.
# --------------------------------------------------------------------------- #
def _inv_duplicate_names() -> ScenarioFixture:
    return _fixture(
        "inv-duplicate-names",
        "investigation",
        {
            "pkg/__init__.py": "",
            "pkg/mod_a.py": "def process(x: int) -> int:\n    return x + 1\n",
            "pkg/mod_b.py": "def process(x: int) -> int:\n    return x * 2\n",
            "pkg/caller.py": (
                "from pkg.mod_a import process\n\n\n" "def run(x: int) -> int:\n" "    return process(x)\n"
            ),
            "check.py": (
                "from pkg.caller import run\n\n"
                "assert run(3) == 4, "
                "'expected pkg/mod_a.process (3 + 1 = 4), not pkg/mod_b.process (3 * 2 = 6)'\n"
            ),
        },
        includes=("duplicate_names",),
    )


def _inv_alias_reexport() -> ScenarioFixture:
    return _fixture(
        "inv-alias-reexport",
        "investigation",
        {
            "pkg2/__init__.py": "from pkg2.impl import Widget as ExportedWidget\n",
            "pkg2/impl.py": ("class Widget:\n" "    def label(self) -> str:\n" "        return 'impl-widget'\n"),
            "pkg2/caller.py": (
                "from pkg2 import ExportedWidget\n\n\n"
                "def make_label() -> str:\n"
                "    return ExportedWidget().label()\n"
            ),
            "check.py": (
                "from pkg2.caller import make_label\n\n"
                "assert make_label() == 'impl-widget', "
                "'ExportedWidget must resolve to pkg2.impl.Widget through the pkg2/__init__.py re-export'\n"
            ),
        },
        includes=("alias",),
    )


def _inv_namespace_import() -> ScenarioFixture:
    return _fixture(
        "inv-namespace-import",
        "investigation",
        {
            # Two PEP 420 namespace-package roots (no nsx/__init__.py in
            # either) both contribute to the same top-level `nsx` package.
            "roots/root_a/nsx/tool.py": ("def helper() -> str:\n" "    return 'from-root-a'\n"),
            "roots/root_b/nsx/other.py": "VALUE = 'from-root-b'\n",
            "check.py": (
                "import sys\n"
                "from pathlib import Path\n\n"
                "ROOT = Path(__file__).resolve().parent\n"
                "sys.path.insert(0, str(ROOT / 'roots' / 'root_b'))\n"
                "sys.path.insert(0, str(ROOT / 'roots' / 'root_a'))\n\n"
                "from nsx.tool import helper\n\n"
                "assert helper() == 'from-root-a', "
                "'nsx.tool.helper must resolve to roots/root_a/nsx/tool.py, the only root defining it'\n"
            ),
        },
        includes=("namespace",),
    )


def _inv_inherited_receiver() -> ScenarioFixture:
    return _fixture(
        "inv-inherited-receiver",
        "investigation",
        {
            "pkg3/__init__.py": "",
            "pkg3/base.py": ("class Base:\n" "    def compute(self) -> int:\n" "        return 10\n"),
            "pkg3/derived.py": (
                "from pkg3.base import Base\n\n\n"
                "class Derived(Base):\n"
                "    def extra(self) -> int:\n"
                "        return 5\n"
            ),
            "pkg3/caller.py": (
                "from pkg3.derived import Derived\n\n\n" "def run() -> int:\n" "    return Derived().compute()\n"
            ),
            "check.py": (
                "from pkg3.caller import run\n\n"
                "assert run() == 10, "
                "'Derived does not override compute(); it must resolve to pkg3/base.py Base.compute'\n"
            ),
        },
        includes=("inherited_receiver",),
    )


# --------------------------------------------------------------------------- #
# Change: signature/callers, return-type consumers, decorator wrapper,
# registry-driven dispatch.
# --------------------------------------------------------------------------- #
def _chg_signature_callers() -> ScenarioFixture:
    baseline = (
        "def greet(name: str) -> str:\n"
        "    return f'Hello {name}'\n\n\n"
        "def welcome(name: str) -> str:\n"
        "    return greet(name)\n"
    )
    return _fixture(
        "chg-signature-callers",
        "change",
        {
            "pkg4/__init__.py": "",
            "pkg4/greet.py": baseline,
            "check.py": (
                "from pkg4.greet import welcome\n\n"
                "assert welcome('Ada') == 'Hello Ada'\n"
                "assert welcome('Ada', excited=True) == 'Hello Ada!'\n"
            ),
        },
        entry_point="pkg4/greet.py",
        expected_fix=(
            "def greet(name: str, excited: bool = False) -> str:\n"
            "    suffix = '!' if excited else ''\n"
            "    return f'Hello {name}{suffix}'\n\n\n"
            "def welcome(name: str, excited: bool = False) -> str:\n"
            "    return greet(name, excited=excited)\n"
        ),
        # Plausible-but-wrong: greet() gained the parameter, but welcome()
        # was not updated to accept/forward it -- a partial signature change.
        counterexample=(
            "def greet(name: str, excited: bool = False) -> str:\n"
            "    suffix = '!' if excited else ''\n"
            "    return f'Hello {name}{suffix}'\n\n\n"
            "def welcome(name: str) -> str:\n"
            "    return greet(name)\n"
        ),
        includes=("signature_callers",),
    )


def _chg_return_type_consumers() -> ScenarioFixture:
    baseline = (
        "def bounds(values: list[int]) -> tuple[int, int]:\n"
        "    return min(values), max(values)\n\n\n"
        "def describe(values: list[int]) -> str:\n"
        "    lo, hi = bounds(values)\n"
        "    return f'{lo}..{hi}'\n"
    )
    return _fixture(
        "chg-return-type-consumers",
        "change",
        {
            "pkg5/__init__.py": "",
            "pkg5/stats.py": baseline,
            "check.py": (
                "from pkg5.stats import bounds, describe\n\n"
                "assert describe([3, 1, 2]) == '1..3'\n"
                "result = bounds([3, 1, 2])\n"
                "assert result.minimum == 1\n"
                "assert result.maximum == 3\n"
            ),
        },
        entry_point="pkg5/stats.py",
        expected_fix=(
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            "class Bounds:\n"
            "    minimum: int\n"
            "    maximum: int\n\n\n"
            "def bounds(values: list[int]) -> Bounds:\n"
            "    return Bounds(minimum=min(values), maximum=max(values))\n\n\n"
            "def describe(values: list[int]) -> str:\n"
            "    result = bounds(values)\n"
            "    return f'{result.minimum}..{result.maximum}'\n"
        ),
        # Plausible-but-wrong: the migration to a dataclass was never made,
        # so `bounds()` still returns a bare tuple with no `.minimum`.
        counterexample=baseline,
        includes=("return_type_consumers",),
    )


def _chg_decorator_wrapper() -> ScenarioFixture:
    baseline = "calls = {'count': 0}\n\n\ndef compute(x: int) -> int:\n    return x * x\n"
    return _fixture(
        "chg-decorator-wrapper",
        "change",
        {
            "pkg6/__init__.py": "",
            "pkg6/deco.py": baseline,
            "check.py": (
                "from pkg6 import deco\n\n"
                "assert deco.compute(3) == 9\n"
                "assert deco.compute(4) == 16\n"
                "assert deco.calls['count'] == 2, 'the counted decorator must increment calls[\"count\"] per call'\n"
                "assert deco.compute.__name__ == 'compute', 'functools.wraps must preserve the wrapped __name__'\n"
            ),
        },
        entry_point="pkg6/deco.py",
        expected_fix=(
            "import functools\n\n"
            "calls = {'count': 0}\n\n\n"
            "def counted(func):\n"
            "    @functools.wraps(func)\n"
            "    def wrapper(*args, **kwargs):\n"
            "        calls['count'] += 1\n"
            "        return func(*args, **kwargs)\n\n"
            "    return wrapper\n\n\n"
            "@counted\n"
            "def compute(x: int) -> int:\n"
            "    return x * x\n"
        ),
        # Plausible-but-wrong: the decorator is applied but forgets to
        # increment the counter and drops functools.wraps.
        counterexample=(
            "calls = {'count': 0}\n\n\n"
            "def counted(func):\n"
            "    def wrapper(*args, **kwargs):\n"
            "        return func(*args, **kwargs)\n\n"
            "    return wrapper\n\n\n"
            "@counted\n"
            "def compute(x: int) -> int:\n"
            "    return x * x\n"
        ),
        includes=("decorator",),
    )


def _chg_registry_dispatch() -> ScenarioFixture:
    baseline = (
        "def _double(x: int) -> int:\n"
        "    return x * 2\n\n\n"
        "def _square(x: int) -> int:\n"
        "    return x * x\n\n\n"
        "HANDLERS = {\n"
        "    'double': _double,\n"
        "    'square': _square,\n"
        "}\n\n\n"
        "def dispatch(name: str, x: int) -> int:\n"
        "    return HANDLERS[name](x)\n"
    )
    return _fixture(
        "chg-registry-dispatch",
        "change",
        {
            "pkg7/__init__.py": "",
            "pkg7/registry.py": baseline,
            "check.py": (
                "from pkg7.registry import dispatch\n\n"
                "assert dispatch('double', 4) == 8\n"
                "assert dispatch('square', 4) == 16\n"
                "assert dispatch('triple', 4) == 12, \"a 'triple' handler must be registered and dispatchable\"\n"
            ),
        },
        entry_point="pkg7/registry.py",
        expected_fix=(
            "def _double(x: int) -> int:\n"
            "    return x * 2\n\n\n"
            "def _square(x: int) -> int:\n"
            "    return x * x\n\n\n"
            "def _triple(x: int) -> int:\n"
            "    return x * 3\n\n\n"
            "HANDLERS = {\n"
            "    'double': _double,\n"
            "    'square': _square,\n"
            "    'triple': _triple,\n"
            "}\n\n\n"
            "def dispatch(name: str, x: int) -> int:\n"
            "    return HANDLERS[name](x)\n"
        ),
        # Plausible-but-wrong: the handler function was added but never
        # registered under the 'triple' string key -- a defect only a text
        # search of every HANDLERS registration site would confidently
        # confirm (spec's supplementary-text-search policy).
        counterexample=(
            "def _double(x: int) -> int:\n"
            "    return x * 2\n\n\n"
            "def _square(x: int) -> int:\n"
            "    return x * x\n\n\n"
            "def _triple(x: int) -> int:\n"
            "    return x * 3\n\n\n"
            "HANDLERS = {\n"
            "    'double': _double,\n"
            "    'square': _square,\n"
            "}\n\n\n"
            "def dispatch(name: str, x: int) -> int:\n"
            "    return HANDLERS[name](x)\n"
        ),
        includes=("registry",),
    )


# --------------------------------------------------------------------------- #
# Fix: wrong import, type mismatch, stale saved dependency, unavailable
# server (fallback).
# --------------------------------------------------------------------------- #
def _fix_wrong_import() -> ScenarioFixture:
    baseline = "from pkg8.decoy_source import VALUE\n\n\n" "def get_value() -> int:\n" "    return VALUE\n"
    return _fixture(
        "fix-wrong-import",
        "fix",
        {
            "pkg8/__init__.py": "",
            "pkg8/correct_source.py": "VALUE = 42\n",
            "pkg8/decoy_source.py": "VALUE = -1\n",
            "pkg8/consumer.py": baseline,
            "check.py": (
                "from pkg8.consumer import get_value\n\n"
                "assert get_value() == 42, 'consumer.py must import VALUE from pkg8.correct_source'\n"
            ),
        },
        entry_point="pkg8/consumer.py",
        expected_fix=("from pkg8.correct_source import VALUE\n\n\n" "def get_value() -> int:\n" "    return VALUE\n"),
        # Plausible-but-wrong: fixes the import source but aliases it,
        # leaving the unaliased name referenced below undefined.
        counterexample=(
            "from pkg8.correct_source import VALUE as _V\n\n\n" "def get_value() -> int:\n" "    return VALUE\n"
        ),
        includes=("wrong_import",),
    )


def _fix_type_mismatch() -> ScenarioFixture:
    baseline = (
        "TAX_RATE_CONFIG = '0.1'\n\n\n"
        "def add_tax(amount: int) -> float:\n"
        "    return amount * (1 + TAX_RATE_CONFIG)\n"
    )
    return _fixture(
        "fix-type-mismatch",
        "fix",
        {
            "pkg9/__init__.py": "",
            "pkg9/calc.py": baseline,
            "check.py": (
                "from pkg9.calc import add_tax\n\n"
                "assert abs(add_tax(100) - 110.0) < 1e-9, "
                "'TAX_RATE_CONFIG is a str and must be converted to float before use'\n"
            ),
        },
        entry_point="pkg9/calc.py",
        expected_fix=(
            "TAX_RATE_CONFIG = '0.1'\n\n\n"
            "def add_tax(amount: int) -> float:\n"
            "    return amount * (1 + float(TAX_RATE_CONFIG))\n"
        ),
        # Plausible-but-wrong: converts the wrong operand, leaving the
        # str + int mismatch on TAX_RATE_CONFIG untouched.
        counterexample=(
            "TAX_RATE_CONFIG = '0.1'\n\n\n"
            "def add_tax(amount: int) -> float:\n"
            "    return float(amount) * (1 + TAX_RATE_CONFIG)\n"
        ),
        includes=("type_mismatch",),
    )


def _fix_stale_saved_dependency() -> ScenarioFixture:
    # dependency.py already reflects the *current*, already-changed
    # signature; consumer.py is the stale caller that still expects the
    # old one-argument form.
    baseline = (
        "from pkg10.dependency import compute_price\n\n\n"
        "def total(amount: float) -> float:\n"
        "    return compute_price(amount)\n"
    )
    return _fixture(
        "fix-stale-saved-dependency",
        "fix",
        {
            "pkg10/__init__.py": "",
            "pkg10/dependency.py": (
                "def compute_price(amount: float, discount_pct: float) -> float:\n"
                "    return amount * (1 - discount_pct / 100)\n"
            ),
            "pkg10/consumer.py": baseline,
            "check.py": (
                "from pkg10.consumer import total\n\n"
                "assert total(100.0) == 90.0, "
                "'consumer.py must pass the now-required discount_pct=10.0 to compute_price'\n"
            ),
        },
        entry_point="pkg10/consumer.py",
        expected_fix=(
            "from pkg10.dependency import compute_price\n\n\n"
            "def total(amount: float) -> float:\n"
            "    return compute_price(amount, discount_pct=10.0)\n"
        ),
        # Plausible-but-wrong: passes the new required argument, but with
        # a value that does not match the expected 10% discount.
        counterexample=(
            "from pkg10.dependency import compute_price\n\n\n"
            "def total(amount: float) -> float:\n"
            "    return compute_price(amount, discount_pct=0.0)\n"
        ),
        includes=("stale_saved_dependency",),
    )


def _fix_unavailable_server() -> ScenarioFixture:
    # A deliberately simple, single-file, single-symbol bug: findable and
    # fixable through plain text search alone, standing in for the arm
    # whose semantic server is simulated unavailable for this task (spec:
    # "The unavailable-server arm uses fallback, not automatic exclusion
    # from results").
    baseline = (
        "def clamp(value: int, low: int, high: int) -> int:\n"
        "    if value < low:\n"
        "        return low\n"
        "    if value > high:\n"
        "        return low  # bug: should return high\n"
        "    return value\n"
    )
    return _fixture(
        "fix-unavailable-server",
        "fix",
        {
            "pkg11/__init__.py": "",
            "pkg11/util.py": baseline,
            "check.py": (
                "from pkg11.util import clamp\n\n"
                "assert clamp(15, 0, 10) == 10\n"
                "assert clamp(-5, 0, 10) == 0\n"
                "assert clamp(5, 0, 10) == 5\n"
            ),
        },
        entry_point="pkg11/util.py",
        expected_fix=(
            "def clamp(value: int, low: int, high: int) -> int:\n"
            "    if value < low:\n"
            "        return low\n"
            "    if value > high:\n"
            "        return high\n"
            "    return value\n"
        ),
        # Plausible-but-wrong: fixes a different branch than the actual
        # bug, introducing a new failure instead of curing the reported one.
        counterexample=(
            "def clamp(value: int, low: int, high: int) -> int:\n"
            "    if value < low:\n"
            "        return high  # wrong branch fixed\n"
            "    if value > high:\n"
            "        return low\n"
            "    return value\n"
        ),
        includes=("unavailable_server",),
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
INVESTIGATION_SCENARIO_IDS: tuple[str, ...] = (
    "inv-duplicate-names",
    "inv-alias-reexport",
    "inv-namespace-import",
    "inv-inherited-receiver",
)

CHANGE_SCENARIO_IDS: tuple[str, ...] = (
    "chg-signature-callers",
    "chg-return-type-consumers",
    "chg-decorator-wrapper",
    "chg-registry-dispatch",
)

FIX_SCENARIO_IDS: tuple[str, ...] = (
    "fix-wrong-import",
    "fix-type-mismatch",
    "fix-stale-saved-dependency",
    "fix-unavailable-server",
)

#: The fixed, ordered set of all twelve approved pilot tasks (spec §2:
#: "four investigations ... four changes ... four fixes").
SCENARIO_IDS: tuple[str, ...] = INVESTIGATION_SCENARIO_IDS + CHANGE_SCENARIO_IDS + FIX_SCENARIO_IDS

_SCENARIO_BUILDERS: dict[str, Callable[[], ScenarioFixture]] = {
    "inv-duplicate-names": _inv_duplicate_names,
    "inv-alias-reexport": _inv_alias_reexport,
    "inv-namespace-import": _inv_namespace_import,
    "inv-inherited-receiver": _inv_inherited_receiver,
    "chg-signature-callers": _chg_signature_callers,
    "chg-return-type-consumers": _chg_return_type_consumers,
    "chg-decorator-wrapper": _chg_decorator_wrapper,
    "chg-registry-dispatch": _chg_registry_dispatch,
    "fix-wrong-import": _fix_wrong_import,
    "fix-type-mismatch": _fix_type_mismatch,
    "fix-stale-saved-dependency": _fix_stale_saved_dependency,
    "fix-unavailable-server": _fix_unavailable_server,
}


def build_fixture(scenario_id: str) -> ScenarioFixture:
    """Build the named scenario's fixture tree.

    Args:
        scenario_id: One of :data:`SCENARIO_IDS`.

    Returns:
        A freshly constructed, deterministic :class:`ScenarioFixture`.

    Raises:
        KeyError: If ``scenario_id`` is not one of the twelve approved ids.
    """
    try:
        builder = _SCENARIO_BUILDERS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"unknown pilot scenario id: {scenario_id!r}") from exc
    return builder()
