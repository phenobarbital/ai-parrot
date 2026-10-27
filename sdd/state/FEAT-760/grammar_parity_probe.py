import re

OLD_WIKI = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
NEW_WIKI = re.compile(r"\b(?:([A-Za-z][A-Za-z0-9]*)-)?ADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
OLD_GI = re.compile(r"\b(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
NEW_GI = re.compile(r"\b(?:([A-Za-z][A-Za-z0-9]*)-)?(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)

CORPUS = [
    "ADR-42", "ADR/042", "ADR 42", "adr42",
    "FS-ADR-3", "parrot-ADR-7", "PARROT-adr/007",
    "ADR_42", "ADR--42", "ADR - 42",
    "see-ADR-3 for why", "RFC 4180", "FS-RFC-2119",
    'x = "see ADR-42"', "# ADR-1: why", "ADR-99999", "ADR-123456",
]

def norm(m, known):
    """Mirror the spec's normalize_adr_alias."""
    pre, num = m.group(1), m.group(2)
    if pre and known and pre.upper() in known:
        return f"{pre.upper()}-ADR-{int(num)}"
    return f"ADR-{int(num)}"

print(f"{'text':22} {'old':10} {'new(none)':10} {'new({FS,PARROT,SEE?})':14} spans old/new")
print("-" * 92)
regress = []
for t in CORPUS:
    om = OLD_WIKI.search(t)
    nm = NEW_WIKI.search(t)
    old = f"ADR-{int(om.group(1))}" if om else "None"
    new_bare = norm(nm, None) if nm else "None"
    new_known = norm(nm, {"FS", "PARROT"}) if nm else "None"
    ospan = om.span() if om else None
    nspan = nm.span() if nm else None
    flag = "" if old == new_bare else "  <-- BACK-COMPAT CHANGE"
    if old != new_bare:
        regress.append((t, old, new_bare))
    print(f"{t!r:22} {old:10} {new_bare:10} {new_known:14} {ospan}/{nspan}{flag}")

print()
print("=== cross-plane parity: spans + (prefix, number) on ADR hits ===")
mismatch = []
for t in CORPUS:
    w = list(NEW_WIKI.finditer(t))
    g = [m for m in NEW_GI.finditer(t) if m.group(2).upper() == "ADR"]
    wt = [(m.span(), (m.group(1) or "").upper(), int(m.group(2))) for m in w]
    gt = [(m.span(), (m.group(1) or "").upper(), int(m.group(3))) for m in g]
    if wt != gt:
        mismatch.append((t, wt, gt))
        print(f"  MISMATCH {t!r}: wiki={wt} gi={gt}")
print("  all ADR spans+triples agree" if not mismatch else f"  {len(mismatch)} mismatches")

print()
print("=== GraphIndex RFC + unprefixed-corpus node-id stability ===")
for t in ["RFC 4180", "FS-RFC-2119", "ADR-42"]:
    o = OLD_GI.search(t); n = NEW_GI.search(t)
    onorm = f"{o.group(1).upper()}-{int(o.group(2))}" if o else "None"
    npre = (n.group(1) or "").upper() if n else ""
    nnorm = (f"{npre}-" if npre else "") + f"{n.group(2).upper()}-{int(n.group(3))}" if n else "None"
    print(f"  {t!r:16} old={onorm:14} new={nnorm:16} span {o.span() if o else None}/{n.span() if n else None}")

print()
print("=== AC14/AC15: label parity between planes under one allowlist ===")
KNOWN = {"FS", "PARROT"}

def gi_label(m, known):
    """Mirror the resolved _register rule: allowlist applies, RFC never prefixed."""
    pre, kind, num = m.group(1), m.group(2).upper(), m.group(3)
    if pre and known and pre.upper() in known and kind == "ADR":
        return f"{pre.upper()}-{kind}-{int(num)}"
    return f"{kind}-{int(num)}"

bad = []
for t in CORPUS:
    wm = NEW_WIKI.search(t)
    gm = NEW_GI.search(t)
    wiki = norm(wm, KNOWN) if wm else None
    gi = gi_label(gm, KNOWN) if gm else None
    gi_unconf = gi_label(gm, None) if gm else None
    old_gi_m = OLD_GI.search(t)
    old_gi = f"{old_gi_m.group(1).upper()}-{int(old_gi_m.group(2))}" if old_gi_m else None
    is_adr = bool(gm) and gm.group(2).upper() == "ADR"
    # AC14: ADR labels must match the wiki alias under the same allowlist
    if is_adr and wiki != gi:
        bad.append(("AC14", t, wiki, gi))
    # AC15: RFC is never prefixed
    if gm and gm.group(2).upper() == "RFC" and gi.count("-") > 1:
        bad.append(("AC15", t, None, gi))
    # AC11: unconfigured GraphIndex is byte-identical to today
    if gi_unconf != old_gi:
        bad.append(("AC11", t, old_gi, gi_unconf))
    print(f"  {t!r:22} wiki={str(wiki):14} gi={str(gi):14} gi(unconf)={str(gi_unconf):12} old_gi={old_gi}")

print()
print("VIOLATIONS:", bad or "none — AC11, AC14 and AC15 hold on this corpus")
print("REGRESSIONS vs today (unconfigured repo, wiki plane):", regress or "none")
