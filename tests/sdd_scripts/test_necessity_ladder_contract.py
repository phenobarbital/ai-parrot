"""FEAT-908 contract: the Necessity Ladder in the spec template, the SDD commands and review."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC_TWINS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md")
SPEC_SKILL = ".agents/skills/sdd-spec/SKILL.md"
SPEC_USAGE = (
    "/sdd-spec [<feature-slug>] [--type feature] [--base-branch <branch>] [--interview | --no-interview] "
    "[--resume [<staging-dir>]] [--research full|light|none] [--no-gate] [--budget tight|default|loose] "
    "[-- <notes>]"
)
L7_SCAN = "grep -niE 'future|later|extensib|pluggable|generic|just in case'"
REVIEWER_COPIES = (
    ".claude/agents/code-reviewer.md",
    "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md",
    ".agents/agents/code-reviewer/agent.md",
)
CONVENTIONS_COPIES = (
    ".claude/rules/codebase-conventions.md",
    ".agent/rules/codebase-conventions.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
)
REUSE_PACKAGES = ("asyncdb", "navconfig", "navigator-auth", "navigator-eventbus")

PROPOSAL_TWINS = (".claude/commands/sdd-proposal.md", ".agent/workflows/sdd-proposal.md")
BRAINSTORM_TWINS = (".claude/commands/sdd-brainstorm.md", ".agent/workflows/sdd-brainstorm.md")
TASK_TWINS = (".claude/commands/sdd-task.md", ".agent/workflows/sdd-task.md")


def _read(rel: str) -> str:
    """Return the text of a tracked file under the repository root."""
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _body(text: str) -> str:
    """Drop a leading YAML frontmatter block, if present."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text if end == -1 else text[end + len("\n---\n") :].lstrip("\n")


def _section(text: str, heading: str) -> str:
    """Return the body under ``heading`` up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading) + len(heading)
    ends = [text.find(f"\n{'#' * n} ", start) for n in range(1, len(level) + 1)]
    ends = [e for e in ends if e != -1]
    return text[start : min(ends)] if ends else text[start:]


def _assert_contains(text: str, markers: tuple[str, ...], where: str) -> None:
    """Assert that every marker occurs in ``text``, naming the file and marker on failure."""
    for marker in markers:
        assert marker in text, f"{where}: missing {marker!r}"


def _assert_order(text: str, markers: tuple[str, ...], where: str) -> None:
    """Assert that the markers occur in ``text`` in the given order."""
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions), f"{where}: expected order {markers!r}"


class TestNecessityLadderContract:
    """Text contracts FEAT-908 adds to the shipped SDD commands, templates and review agents."""

    def test_spec_template_has_ladder_sections(self) -> None:
        """Template carries the ladder table, Totals line, Deferred line, Known Shortcuts and the §5 criterion."""
        where = "sdd/templates/spec.md"
        text = _read(where)
        _assert_order(text, ("#### Necessity Ladder", "#### Delegation-eligible modules"), where)
        _assert_contains(
            text,
            (
                "| Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |",
                "Totals: <M> modules — reuse <a>",
                "- [ ] No public symbol, file or dependency beyond §3 Interface Skeletons, §6 Edit Sites",
            ),
            where,
        )
        non_goals = _section(text, "### Non-Goals (explicitly out of scope)")
        assert (
            "- Deferred: <thing not built> — <what would justify building it>" in non_goals
        ), f"{where}: Non-Goals lacks the Deferred line"
        _assert_order(text, ("### External Dependencies", "### Known Shortcuts", "## Decisions"), where)

    def test_sdd_spec_twins_carry_the_gate(self) -> None:
        """Both full twins carry the guardrail, §4c, §5a and the `Ladder:` line and stay identical; the codex skill names them."""
        claude_path, google_path = SPEC_TWINS
        claude = _read(claude_path)
        google = _read(google_path)
        assert _body(claude).strip() == _body(google).strip(), f"{google_path}: body differs from {claude_path}"
        _assert_contains(
            claude,
            (
                "**Least new code**",
                "### 4c. Necessity Ladder (least-new-code gate)",
                "### 5a. Lean Review (checks the Necessity Ladder — never asks)",
                "   Ladder: reuse <a> · stdlib/platform <b>",
                "| Deferred Capabilities | §1 Non-Goals (`Deferred:` lines, verbatim) |",
                "`sdd/CONVENTIONS.md`\n   § Reuse first",
                SPEC_USAGE,
            ),
            claude_path,
        )
        _assert_order(
            claude,
            ("### 4b. Retrieve Governing Decisions", "### 4c. Necessity Ladder", "### 5. Scaffold the Spec"),
            claude_path,
        )
        _assert_order(claude, ("### 5a. Lean Review", "### 5b. Consequence Gate"), claude_path)
        _assert_contains(
            _read(SPEC_SKILL),
            ("Least new code", "Necessity Ladder", "Lean Review", "`Ladder:` line"),
            SPEC_SKILL,
        )

    def test_l7_scan_is_not_table_escaped(self) -> None:
        """No sdd-spec twin carries the `\\|`-escaped scan; the plain alternation sits in a fenced block."""
        for rel in (*SPEC_TWINS, SPEC_SKILL):
            assert "future\\|later" not in _read(rel), f"{rel}: carries the table-escaped L7 scan"
        for rel in SPEC_TWINS:
            text = _read(rel)
            assert "```bash\n# L7 — speculation scan" in text, f"{rel}: L7 scan is not in a fenced bash block"
            scan_lines = [line for line in text.splitlines() if L7_SCAN in line]
            assert scan_lines, f"{rel}: missing the L7 scan command"
            for line in scan_lines:
                assert not line.lstrip().startswith("|"), f"{rel}: L7 scan sits in a table row: {line!r}"

    def test_proposal_states_if_not_built(self) -> None:
        """Synthesis prompt, both exploration templates and their command twins carry the clause and the deferred list."""
        _assert_contains(
            _read("sdd/templates/synthesis.prompt.md"),
            ("`if_not_built`", "- what is DEFERRED"),
            "sdd/templates/synthesis.prompt.md",
        )
        _assert_contains(
            _read("sdd/templates/proposal.md"),
            ("*If not built*: <requirement left unmet>", "- Deferred: <capability considered and not proposed>"),
            "sdd/templates/proposal.md",
        )
        for rel in PROPOSAL_TWINS:
            _assert_contains(
                _read(rel),
                (
                    "6. In enrichment mode, every NEW item has a non-empty `if_not_built`",
                    "| §3 What's Untouched — `Deferred:` lines | Spec §1 Non-Goals",
                ),
                rel,
            )
        _assert_contains(
            _read(".agents/skills/sdd-proposal/SKILL.md"),
            ("listed as `Deferred:` under Non-Goals",),
            ".agents/skills/sdd-proposal/SKILL.md",
        )
        _assert_contains(
            _read("sdd/templates/brainstorm.md"),
            ("*If not built*: <requirement left unmet>", "### Deferred Capabilities"),
            "sdd/templates/brainstorm.md",
        )
        for rel in BRAINSTORM_TWINS:
            _assert_contains(
                _read(rel),
                (
                    'goes under "Deferred Capabilities" instead',
                    "- **Deferred Capabilities** → Spec Section 1 (Non-Goals, `Deferred:` lines)",
                ),
                rel,
            )
        _assert_contains(
            _read(".agents/skills/sdd-brainstorm/SKILL.md"),
            ('"Deferred Capabilities", not proposed',),
            ".agents/skills/sdd-brainstorm/SKILL.md",
        )

    def test_task_and_reviewer_bind_the_ladder(self) -> None:
        """sdd-task twins and the task template carry the `**Ladder**:` line; the reviewer copies carry the red flags."""
        for rel in TASK_TWINS:
            _assert_contains(
                _read(rel),
                (
                    "**Necessity Ladder is binding (FEAT-908).**",
                    "`**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`",
                ),
                rel,
            )
        _assert_contains(
            _read(".agents/skills/sdd-task/SKILL.md"),
            ("`**Ladder**:` line",),
            ".agents/skills/sdd-task/SKILL.md",
        )
        scope = _section(_read("sdd/templates/task.md"), "## Scope")
        assert (
            "**Ladder**: <rung> · reuses <evidence> · est. <n> LOC" in scope
        ), "sdd/templates/task.md: ## Scope lacks the **Ladder** line"
        for rel in REVIEWER_COPIES:
            _assert_contains(
                _section(_read(rel), "## Universal Red Flags"),
                (
                    "spec's Necessity Ladder does not declare",
                    "around twice the task's `**Ladder**` estimate",
                    "`# shortcut:` comment without a Known Shortcuts row",
                ),
                f"{rel} (## Universal Red Flags)",
            )
        assert _read(REVIEWER_COPIES[0]) == _read(
            REVIEWER_COPIES[1]
        ), f"{REVIEWER_COPIES[1]}: differs from {REVIEWER_COPIES[0]}"

    def test_conventions_name_reuse_first(self) -> None:
        """The seed's Reuse first section names no package; the three conventions copies are identical and name four."""
        seed = _section(_read("sdd/CONVENTIONS.md"), "## Reuse first")
        assert "Necessity Ladder" in seed, "sdd/CONVENTIONS.md: ## Reuse first does not name the Necessity Ladder"
        for package in REUSE_PACKAGES:
            assert package not in seed, f"sdd/CONVENTIONS.md: ## Reuse first names {package!r}"
        first, *others = (_read(rel) for rel in CONVENTIONS_COPIES)
        for rel, text in zip(CONVENTIONS_COPIES[1:], others, strict=True):
            assert text == first, f"{rel}: differs from {CONVENTIONS_COPIES[0]}"
        reuse = _section(first, "## Reuse first — check these before writing new code")
        for package in REUSE_PACKAGES:
            assert f"`{package}`" in reuse, f"{CONVENTIONS_COPIES[0]}: ## Reuse first lacks `{package}`"
        _assert_order(first, ("## Reuse first", "## Repository layout"), CONVENTIONS_COPIES[0])
