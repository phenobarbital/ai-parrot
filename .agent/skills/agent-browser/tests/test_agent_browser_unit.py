"""Unit tests for the agent-browser driver — pure logic, no browser needed.

Covers selector/ref resolution, on-disk state helpers, and argument parsing
(the CLI contract). These run fast and have no external dependencies.
"""
import pytest


# --------------------------------------------------------------------------- #
# Selector / ref resolution
# --------------------------------------------------------------------------- #
def test_resolve_selector_ref(ab_mod):
    refs = {"e1": '[data-ab-ref="e1"]'}
    assert ab_mod._resolve_selector("@e1", refs) == '[data-ab-ref="e1"]'


def test_resolve_selector_css_passthrough(ab_mod):
    # A raw CSS selector is returned unchanged.
    assert ab_mod._resolve_selector("button.primary", {}) == "button.primary"
    assert ab_mod._resolve_selector("#sel", {"e1": "x"}) == "#sel"


def test_resolve_selector_unknown_ref_exits(ab_mod):
    with pytest.raises(SystemExit):
        ab_mod._resolve_selector("@e99", {"e1": "x"})


# --------------------------------------------------------------------------- #
# On-disk state helpers (isolated_state fixture points STATE_ROOT at tmp)
# --------------------------------------------------------------------------- #
def test_routes_roundtrip(ab_mod):
    assert ab_mod._read_routes("s1") == []
    rules = [{"url": "*.png", "action": "abort"}]
    ab_mod._write_routes("s1", rules)
    assert ab_mod._read_routes("s1") == rules


def test_refs_roundtrip(ab_mod):
    assert ab_mod._read_refs("s2") == {}
    refs = {"e1": '[data-ab-ref="e1"]'}
    ab_mod._write_refs("s2", refs)
    assert ab_mod._read_refs("s2") == refs


def test_read_state_missing_exits(ab_mod):
    with pytest.raises(SystemExit):
        ab_mod._read_state("never-started")


def test_session_dir_is_created(ab_mod):
    d = ab_mod._session_dir("freshsess")
    assert d.exists() and d.is_dir()


def test_free_port_returns_int(ab_mod):
    port = ab_mod._free_port()
    assert isinstance(port, int) and 1024 <= port <= 65535


# --------------------------------------------------------------------------- #
# Argument parsing — the CLI contract
# --------------------------------------------------------------------------- #
def test_parser_session_is_global(ab_mod):
    args = ab_mod.build_parser().parse_args(["--session", "x", "open", "http://u"])
    assert args.session == "x"
    assert args.url == "http://u"
    assert args.func is ab_mod.cmd_open


def test_parser_default_session(ab_mod):
    args = ab_mod.build_parser().parse_args(["open", "http://u"])
    assert args.session == "default"


def test_parser_snapshot_interactive_json(ab_mod):
    args = ab_mod.build_parser().parse_args(["snapshot", "-i", "--json"])
    assert args.interactive is True and args.json is True
    assert args.func is ab_mod.cmd_snapshot


def test_parser_hover(ab_mod):
    args = ab_mod.build_parser().parse_args(["hover", "@e1"])
    assert args.ref == "@e1" and args.func is ab_mod.cmd_hover


def test_parser_select_multi_value(ab_mod):
    args = ab_mod.build_parser().parse_args(["select", "@e1", "a", "b"])
    assert args.ref == "@e1" and args.values == ["a", "b"]
    assert args.func is ab_mod.cmd_select


def test_parser_get_attr(ab_mod):
    args = ab_mod.build_parser().parse_args(["get", "attr", "@e1", "href"])
    assert args.what == "attr" and args.target == "@e1" and args.extra == "href"
    assert args.func is ab_mod.cmd_get


def test_parser_get_rejects_bad_choice(ab_mod):
    with pytest.raises(SystemExit):
        ab_mod.build_parser().parse_args(["get", "bogus"])


def test_parser_network_route_abort(ab_mod):
    args = ab_mod.build_parser().parse_args(["network", "route", "*.png", "--abort"])
    assert args.action == "route" and args.url == "*.png" and args.abort is True
    assert args.func is ab_mod.cmd_network


def test_parser_network_route_mock(ab_mod):
    args = ab_mod.build_parser().parse_args(
        ["network", "route", "**/cfg.json", "--body", "{}", "--status", "201"]
    )
    assert args.body == "{}" and args.status == 201


def test_parser_network_unroute_optional_url(ab_mod):
    args = ab_mod.build_parser().parse_args(["network", "unroute"])
    assert args.url is None
    args2 = ab_mod.build_parser().parse_args(["network", "unroute", "*.png"])
    assert args2.url == "*.png"


def test_parser_requires_subcommand(ab_mod):
    with pytest.raises(SystemExit):
        ab_mod.build_parser().parse_args([])


# --------------------------------------------------------------------------- #
# Network command logic, exercised without a browser
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cmd_network_route_then_unroute(ab_mod):
    parser = ab_mod.build_parser()

    add = parser.parse_args(["--session", "n1", "network", "route", "*.css", "--abort"])
    await ab_mod.cmd_network(add)
    assert ab_mod._read_routes("n1") == [{"url": "*.css", "action": "abort"}]

    mock = parser.parse_args(
        ["--session", "n1", "network", "route", "**/api", "--body", "{}"]
    )
    await ab_mod.cmd_network(mock)
    assert len(ab_mod._read_routes("n1")) == 2

    rm = parser.parse_args(["--session", "n1", "network", "unroute", "*.css"])
    await ab_mod.cmd_network(rm)
    assert ab_mod._read_routes("n1") == [
        {"url": "**/api", "action": "mock", "body": "{}", "status": 200}
    ]

    clear = parser.parse_args(["--session", "n1", "network", "unroute"])
    await ab_mod.cmd_network(clear)
    assert ab_mod._read_routes("n1") == []
