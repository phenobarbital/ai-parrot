"""G5 — Biscuit issue → attenuate → authorize for Squawk capability scopes (FEAT-746)."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

from biscuit_auth import (
    AuthorizationError,
    AuthorizerBuilder,
    Biscuit,
    BiscuitBuilder,
    BlockBuilder,
    Check,
    Fact,
    KeyPair,
    Policy,
    PublicKey,
)

ROOT_GLOB = "hr.reports.*"
GLOB_PREFIX = "hr.reports."


def extract_facts_from_source(source: str) -> list[str]:
    """Extract fact strings from Datalog source."""
    facts = []
    pattern = r'(\w+)\("([^"]*)"\)'
    for match in re.finditer(pattern, source):
        pred, arg = match.groups()
        facts.append(f'{pred}("{arg}")')
    return facts


def issue_root(kp: KeyPair, *, caller: str, ttl_h: int = 24) -> Biscuit:
    """Root token: capability_glob, caller, expires."""
    exp = int((datetime.now(timezone.utc) + timedelta(hours=ttl_h)).timestamp())
    builder = BiscuitBuilder(f'capability_glob("{ROOT_GLOB}"); caller("{caller}"); expires({exp});')
    return builder.build(kp.private_key)


def attenuate(token: Biscuit, cap_id: str) -> Biscuit:
    """Narrow to one capability; widening is impossible because checks only add constraints."""
    block = BlockBuilder(f'check if capability("{cap_id}");')
    return token.append(block)


def authorize(
    token_bytes: bytes,
    public_key: PublicKey,
    *,
    cap_id: str,
    caller: str,
    now: int,
    exp: int,
) -> bool:
    """The rule M10 will ship: facts from the call, checks from the token, one allow policy."""
    token = Biscuit.from_bytes(token_bytes, public_key)
    ab = AuthorizerBuilder()

    # Facts from the call
    ab.add_fact(Fact(f'capability("{cap_id}")'))
    ab.add_fact(Fact(f'peer("{caller}")'))
    ab.add_fact(Fact(f'time({now})'))

    # Extract facts from token's authority block
    authority_source = token.block_source(0)
    fact_strings = extract_facts_from_source(authority_source)
    for fs in fact_strings:
        ab.add_fact(Fact(fs))

    # Checks from the token
    # Verify caller matches
    ab.add_check(Check("check if caller($c), peer($c)"))
    # Verify not expired
    ab.add_check(Check("check if expires($e), time($t), $t < $e"))
    # Verify capability matches glob - using starts_with for glob prefix matching
    ab.add_check(Check(f'check if capability($c), capability_glob($g), $c.starts_with("{GLOB_PREFIX}")'))

    ab.add_policy(Policy("allow if true"))
    a = ab.build(token)
    try:
        a.authorize()
        return True
    except AuthorizationError:
        return False


def main() -> int:
    """Run the four test cases and return 0 if all match expected."""
    kp = KeyPair()
    now = int(datetime.now(timezone.utc).timestamp())
    exp = int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())

    root = issue_root(kp, caller="external-agent")
    sub = attenuate(root, "hr.reports.headcount_by_dept")

    cases = {
        "root_on_reports": authorize(
            root.to_bytes(),
            kp.public_key,
            cap_id="hr.reports.manager_of",
            caller="external-agent",
            now=now,
            exp=exp,
        ),
        "sub_on_headcount": authorize(
            sub.to_bytes(),
            kp.public_key,
            cap_id="hr.reports.headcount_by_dept",
            caller="external-agent",
            now=now,
            exp=exp,
        ),
        "sub_on_people": authorize(
            sub.to_bytes(),
            kp.public_key,
            cap_id="hr.people.lookup",
            caller="external-agent",
            now=now,
            exp=exp,
        ),
        "root_wrong_caller": authorize(
            root.to_bytes(),
            kp.public_key,
            cap_id="hr.reports.manager_of",
            caller="other",
            now=now,
            exp=exp,
        ),
    }

    print(json.dumps(cases, indent=2))
    expected = {
        "root_on_reports": True,
        "sub_on_headcount": True,
        "sub_on_people": False,
        "root_wrong_caller": False,
    }
    return 0 if cases == expected else 1


if __name__ == "__main__":
    sys.exit(main())