"""FEAT-720 Amendment A — fixpoint: derive the minimal __init__.py add/remove set so that derived module identities are unique.
Run from the repo root: python -I sdd/state/FEAT-720/identity_fixpoint.py"""
import os, glob, collections, sys, json, importlib.util
sys.path.insert(0, os.getcwd())  # python -m pytest puts the cwd on sys.path
roots = sorted(glob.glob("packages/*/tests"))
KEEP = "packages/ai-parrot/tests"
inits = set(); size = {}
for root in roots:
    n = 0
    for d, sub, files in os.walk(root):
        if "__init__.py" in files: inits.add(d); n += 1
    size[root] = n
# the 25 top-level ones are deleted by M2
for root in roots: inits.discard(root)
tree_of = lambda d: next(r for r in roots if d == r or d.startswith(r + "/"))
def top_of(d):
    root = tree_of(d); cur = d; ch = []
    while cur != root and cur in inits:
        ch.append(cur); cur = os.path.dirname(cur)
    return ch[::-1]
def real_top_level(name):
    try: return importlib.util.find_spec(name) is not None
    except Exception: return True
files_of = {}
for root in roots:
    for d, sub, files in os.walk(root):
        files_of[d] = [f for f in files if f.endswith(".py")]
added, removed = set(), set()
def names():
    m = collections.defaultdict(lambda: collections.defaultdict(set))  # name -> tree -> {top dirs}
    for d in inits:
        ch = top_of(d); base = ".".join(os.path.basename(x) for x in ch)
        tree = tree_of(d)
        m[base][tree].add(ch[0])
        for f in files_of.get(d, []):
            if f != "__init__.py": m[base + "." + f[:-3]][tree].add(ch[0])
    return m
for it in range(200):
    m = names(); fixed = False
    # R3 shadow
    for name, trees in sorted(m.items()):
        if "." in name: continue
        if real_top_level(name):
            for t, tops in trees.items():
                for top in tops:
                    inits.discard(top); (added.discard(top) or removed.add(top)); fixed = True
            if fixed: break
    if fixed: continue
    # R2 duplicates (any tree, intra or cross)
    for name, trees in sorted(m.items()):
        owners = [(t, top) for t, tops in trees.items() for top in tops]
        if len(owners) < 2: continue
        # prefer: add init to a gap parent for intra-tree
        tops = sorted(owners, key=lambda o: (o[0] != KEEP, -size[o[0]], o[1]))
        keep = tops[0]
        for t, top in tops[1:]:
            par = os.path.dirname(top)
            if par != tree_of(top) and par not in inits and "." in name and False:
                pass
            if t == keep[0] and par != t and par not in inits:
                inits.add(par); added.add(par)
            else:
                inits.discard(top); (added.discard(top) or removed.add(top))
        fixed = True; break
    if not fixed: break
print("iterations", it)
print("ADDED", len(added)); [print("  +", a) for a in sorted(added)]
print("REMOVED", len(removed)); [print("  -", r) for r in sorted(removed)]
json.dump({"added": sorted(added), "removed": sorted(removed)}, open("sdd/state/FEAT-720/identity-plan.json", "w"))
