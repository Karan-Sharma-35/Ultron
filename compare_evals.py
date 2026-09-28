import json, sys, collections, io


def load(path):
    return [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]


def skill_of(s):
    s = (s or "").strip().splitlines()[0] if (s or "").strip() else ""
    return s.split(";")[0].split("=", 1)[1].strip() if s.startswith("skill=") else "?"


def summarise(rows):
    by = collections.defaultdict(lambda: [0, 0]); uniq = {}
    runon = 0
    for r in rows:
        g, p = r["gold"], (r["pred"] or "")
        ok = g.strip() == p.strip().splitlines()[0].strip() if p.strip() else False
        by[skill_of(g)][0] += ok; by[skill_of(g)][1] += 1
        uniq.setdefault(r["input"], ok)
        runon += "Message:" in p
    n = len(rows)
    return by, sum(uniq.values()) / max(1, len(uniq)), len(uniq), runon / max(1, n), n


a, b = sys.argv[1], sys.argv[2]
A, B = summarise(load(a)), summarise(load(b))
print(f"{'skill':22s} {'run A':>10s} {'tonight':>10s}")
for sk in sorted(set(A[0]) | set(B[0])):
    ca, na = A[0].get(sk, [0, 0]); cb, nb = B[0].get(sk, [0, 0])
    print(f"{sk:22s} {ca/na*100 if na else 0:9.1f}% {cb/nb*100 if nb else 0:9.1f}%   (n={na}/{nb})")
print(f"{'exact per unique input':22s} {A[1]*100:9.1f}% {B[1]*100:9.1f}%   ({A[2]}/{B[2]} unique)")
print(f"{'run-on rate':22s} {A[3]*100:9.1f}% {B[3]*100:9.1f}%   ({A[4]}/{B[4]} rows)")
