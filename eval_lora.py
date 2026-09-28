"""Score a trained adapter on the rows held out of its training (never seen during training).

  python eval_lora.py --task friday            # category accuracy, per class, confusions
  python eval_lora.py --task edith             # skill + field extraction, per skill
  python eval_lora.py --self_test              # check the scorer itself — no model, no GPU
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from train_lora import (
    EDITH_PROMPT_TEMPLATE, EDITH_FIELDS, EDITH_SKILLS,
    PROMPT_TEMPLATE, TRIAGE_CATEGORIES,
)


DEFAULT_MAX_NEW_TOKENS = 48


def build_skill_field_map(corpus_path) -> "dict[str, set]":
    m: dict = {}
    try:
        with open(corpus_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out = json.loads(line).get("output", "")
                skill, fields = parse_skill_call(out)
                if skill:
                    m.setdefault(skill, set()).update(fields)
    except Exception:
        return {}
    return m


def parse_skill_call(text: str) -> "tuple[str | None, dict]":
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    parts = [p.strip() for p in line.split(";") if p.strip()]
    if not parts or not parts[0].startswith("skill="):
        return None, {}
    skill = parts[0].split("=", 1)[1].strip()
    fields = {}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip()] = v.strip()
    return (skill or None), fields


EVAL_TASKS = {
    "edith": {"prompt": EDITH_PROMPT_TEMPLATE, "fields": EDITH_FIELDS, "skills": EDITH_SKILLS,
              "adapter_dir": Path("adapters") / "edith", "corpus": Path("data") / "edith_train.jsonl"},
    "friday": {"prompt": PROMPT_TEMPLATE, "categories": TRIAGE_CATEGORIES, "fields": [],
               "adapter_dir": Path("adapters") / "friday", "corpus": Path("data") / "friday_train.jsonl"},
}


def score_category(pred_text: str, gold: str) -> dict:
    """FRIDAY answers with one word. The first word of the reply is the prediction; anything else
    (an unknown word, prose) counts as wrong and as degenerate."""
    words = (pred_text or "").strip().split()
    pred = words[0].strip(".,:;") if words else ""
    return {"gold": gold, "pred": pred, "right": pred == gold, "degenerate": pred not in TRIAGE_CATEGORIES}


def print_category_report(rows: "list[dict]") -> None:
    n = len(rows)
    print(f"\n=== FRIDAY holdout eval — {n} rows ===")
    print(f"  accuracy    : {sum(r['right'] for r in rows) / n:.1%}")
    print(f"  degenerate  : {sum(r['degenerate'] for r in rows) / n:.1%}   (not one of the four categories)")
    print("\n  per category (n / right):")
    for c in TRIAGE_CATEGORIES:
        sub = [r for r in rows if r["gold"] == c]
        if sub:
            print(f"    {c:<16} {len(sub):>4}   {sum(r['right'] for r in sub) / len(sub):>6.1%}")
    confusions: dict = {}
    for r in rows:
        if not r["right"]:
            key = (r["gold"], r["pred"] or "(empty)")
            confusions[key] = confusions.get(key, 0) + 1
    if confusions:
        print("\n  most common confusions (gold -> predicted):")
        for (g, p), c in sorted(confusions.items(), key=lambda kv: -kv[1])[:8]:
            print(f"    {g:<16} -> {p:<16} {c:>4}")
_ACTIVE_FIELDS: list = EDITH_FIELDS


def score_one(pred_text: str, gold_text: str, skill_fields: "dict | None" = None) -> dict:
    p_skill, p_fields = parse_skill_call(pred_text)
    g_skill, g_fields = parse_skill_call(gold_text)
    correct = sum(1 for k, v in g_fields.items() if p_fields.get(k) == v)
    extra = [k for k in p_fields if k not in g_fields]

    illegal = sorted(k for k in extra if k not in set(_ACTIVE_FIELDS))
    bleed = []
    if skill_fields and g_skill in skill_fields:
        legal_here = skill_fields[g_skill]
        bleed = sorted(k for k in extra if k not in illegal and k not in legal_here)
    return {
        "illegal_fields": illegal,
        "bleed_fields": bleed,
        "degenerate": p_skill is None,
        "skill_ok": p_skill is not None and p_skill == g_skill,
        "fields_expected": len(g_fields),
        "fields_correct": correct,
        "fields_spurious": sum(1 for k in p_fields if k not in g_fields),
        "exact": (p_skill == g_skill and p_fields == g_fields and p_skill is not None),
        "only_extra_disambiguators": bool(
            p_skill is not None and p_skill == g_skill
            and all(p_fields.get(k) == v for k, v in g_fields.items())
            and {k for k in p_fields if k not in g_fields}
            and {k for k in p_fields if k not in g_fields} <= set(_DISAMBIGUATING_EXTRAS)),
        "gold_skill": g_skill,
    }


_DISAMBIGUATING_EXTRAS = ("day", "time")


def aggregate(rows: "list[dict]") -> dict:
    n = len(rows)

    by_input: dict = {}
    for r in rows:
        key = r.get("input")
        if key is None:
            by_input = {}
            break
        by_input.setdefault(key, r)
    uniq = list(by_input.values())
    exp = sum(r["fields_expected"] for r in rows)
    cor = sum(r["fields_correct"] for r in rows)
    spu = sum(r["fields_spurious"] for r in rows)
    per_skill: dict = {}
    for r in rows:
        d = per_skill.setdefault(r["gold_skill"], {"n": 0, "exact": 0, "skill_ok": 0})
        d["n"] += 1
        d["exact"] += int(r["exact"])
        d["skill_ok"] += int(r["skill_ok"])
    tolerant = 0
    for r in rows:
        if r["exact"]:
            tolerant += 1
        elif r.get("only_extra_disambiguators"):
            tolerant += 1
    per_skill_uniq: dict = {}
    for r in uniq:
        d = per_skill_uniq.setdefault(r["gold_skill"], {"n": 0, "exact": 0, "skill_ok": 0})
        d["n"] += 1
        d["exact"] += int(r["exact"])
        d["skill_ok"] += int(r["skill_ok"])
    bleed: dict = {}
    for r in rows:
        for f in r.get("bleed_fields") or []:
            bleed.setdefault(r["gold_skill"], {}).setdefault(f, 0)
            bleed[r["gold_skill"]][f] += 1
    illegal: dict = {}
    for r in rows:
        for f in r.get("illegal_fields") or []:
            illegal[f] = illegal.get(f, 0) + 1
    return {
        "n": n,
        "n_unique": len(uniq),
        "exact_match_by_input": (sum(r["exact"] for r in uniq) / len(uniq)) if uniq else None,
        "per_skill_by_input": per_skill_uniq,
        "bleed": bleed,
        "illegal": illegal,
        "exact_if_disambiguators_forgiven": tolerant / n if n else 0.0,
        "exact_match": sum(r["exact"] for r in rows) / n if n else 0.0,
        "skill_accuracy": sum(r["skill_ok"] for r in rows) / n if n else 0.0,
        "field_recall": cor / exp if exp else 0.0,
        "spurious_per_row": spu / n if n else 0.0,
        "degenerate_rate": sum(r["degenerate"] for r in rows) / n if n else 0.0,
        "per_skill": per_skill,
    }


def print_report(agg: dict) -> None:
    print(f"\n=== EDITH holdout eval — {agg['n']} rows ===")
    print(f"  exact match      : {agg['exact_match']:.1%}   (skill AND every field)")
    print(f"  skill accuracy   : {agg['skill_accuracy']:.1%}   (routing only)")
    print(f"  field recall     : {agg['field_recall']:.1%}   (expected fields recovered)")
    print(f"  spurious fields  : {agg['spurious_per_row']:.2f} per row  "
          f"(invented — lower is better)")
    print(f"  degenerate       : {agg['degenerate_rate']:.1%}   (no parseable skill= at all)")
    print(f"  ── corpus question, NOT a better score ──")
    print(f"  exact if an extra day=/time= is forgiven: "
          f"{agg['exact_if_disambiguators_forgiven']:.1%}")
    print("    (the model may add a day/time from the [recent: ...] context that the gold omits;")
    print("     on an ambiguous delete or update that extra field may be the right call.)")
    if agg.get("bleed"):
        print("\n  \u26d4 CROSS-SKILL FIELD BLEED \u2014 a field this skill NEVER carries in the corpus:")
        for skill in sorted(agg["bleed"], key=lambda k: -sum(agg["bleed"][k].values())):
            hit = agg["bleed"][skill]
            tot = agg["per_skill"].get(skill, {}).get("n", 0)
            for f, c in sorted(hit.items(), key=lambda kv: -kv[1]):
                print(f"    {skill:<18} {f + '=':<12} {c:>4} of {tot}  "
                      f"({c / tot:.0%} of that skill's rows)" if tot else
                      f"    {skill:<18} {f + '=':<12} {c:>4}")
        print("    (learned from a SIBLING skill — a headline score can hide this completely.)")
    else:
        print("\n  cross-skill field bleed: none")
    if agg.get("illegal"):
        print("\n  \u26d4 INVENTED FIELD NAMES \u2014 not among the eight the prompt lists:")
        for f, c in sorted(agg["illegal"].items(), key=lambda kv: -kv[1]):
            print(f"    {f + '=':<16} {c:>4} rows")
        print("    (a made-up field NAME is a different failure from a legal field")
        print("     filled wrongly, and it does not share a fix.)")

    if agg.get("exact_match_by_input") is not None and agg.get("n_unique"):
        print(f"\n  \u2500\u2500 PER UNIQUE INPUT ({agg['n_unique']} of {agg['n']} rows) \u2500\u2500")
        print(f"  exact match      : {agg['exact_match_by_input']:.1%}   "
              f"(one vote per sentence, not per row)")
        if agg["n_unique"] < agg["n"]:
            print(f"    The row-weighted headline above lets a duplicated sentence vote "
                  f"{agg['n'] / agg['n_unique']:.1f}x on average.")
            print(f"    Where the two disagree, THIS is the honest one and the other is")
            print(f"    the one to quote against history. Neither is 'the' score yet.")

    print("\n  per skill (n / exact / skill-only):")
    for skill, d in sorted(agg["per_skill"].items(), key=lambda kv: -kv[1]["n"]):
        print(f"    {skill:<18} {d['n']:>4}   {d['exact'] / d['n']:>6.1%}   "
              f"{d['skill_ok'] / d['n']:>6.1%}")
    print("\n  ⚠ Read exact-match WITH field recall. A high skill accuracy and a low")
    print("    field recall means routing works and extraction does not — a different")
    print("    problem from a model that is simply wrong, and a different fix.")
    pu = agg.get("per_skill_by_input") or {}
    if pu and pu != agg["per_skill"]:
        print("\n  per skill, PER UNIQUE INPUT (n / exact / skill-only):")
        for skill, d in sorted(pu.items(), key=lambda kv: -kv[1]["n"]):
            flag = "  <- thin" if d["n"] < 10 else ""
            print(f"    {skill:<18} {d['n']:>4}   {d['exact'] / d['n']:>6.1%}   "
                  f"{d['skill_ok'] / d['n']:>6.1%}{flag}")
    small = [s for s, d in agg["per_skill"].items() if d["n"] < 20]
    if small:
        print(f"  ⚠ Thin classes, do not read their percentages as stable: {', '.join(sorted(small))}")


def self_test() -> int:
    gold = "skill=calendar_add; title=lunch; day=monday; time=13:00"
    cases = [
        (gold, dict(exact=True, skill_ok=True, fields_correct=3, degenerate=False), "identical"),
        ("skill=calendar_add; title=lunch; day=monday; time=14:00",
         dict(exact=False, skill_ok=True, fields_correct=2, degenerate=False), "one field wrong"),
        ("skill=reminder; title=lunch; day=monday; time=13:00",
         dict(exact=False, skill_ok=False, fields_correct=3, degenerate=False), "wrong skill, right fields"),
        ("I think you want to add lunch on Monday.",
         dict(exact=False, skill_ok=False, fields_correct=0, degenerate=True), "prose, not a skill call"),
        (gold + "\nAnd shall I also remind you?",
         dict(exact=True, skill_ok=True, fields_correct=3, degenerate=False), "correct + chatter on line 2"),
    ]
    failures = 0
    for pred, want, label in cases:
        got = score_one(pred, gold)
        for k, v in want.items():
            if got[k] != v:
                print(f"  FAIL [{label}] {k}: expected {v}, got {got[k]}")
                failures += 1
    spur = score_one("skill=calendar_add; title=lunch; day=monday; time=13:00; location=cafe", gold)
    if spur["fields_spurious"] != 1:
        print(f"  FAIL [invented field] expected 1 spurious, got {spur['fields_spurious']}")
        failures += 1

    fake = {"calendar_add": {"title", "day", "time"}, "reminder": {"task", "day", "time"}}

    bleed = score_one(gold + "; task=call", gold, fake)
    if bleed["bleed_fields"] != ["task"] or bleed["illegal_fields"]:
        print(f"  FAIL [bleed] expected bleed=['task'] illegal=[], got "
              f"{bleed['bleed_fields']} / {bleed['illegal_fields']}")
        failures += 1

    made_up = score_one(gold + "; specificity=high", gold, fake)
    if made_up["illegal_fields"] != ["specificity"] or made_up["bleed_fields"]:
        print(f"  FAIL [illegal] expected illegal=['specificity'] bleed=[], got "
              f"{made_up['illegal_fields']} / {made_up['bleed_fields']}")
        failures += 1

    short_gold = "skill=calendar_add; title=lunch; day=monday"
    dis = score_one(short_gold + "; time=13:00", short_gold, fake)
    if dis["bleed_fields"] or dis["illegal_fields"] or not dis["only_extra_disambiguators"]:
        print(f"  FAIL [disambiguator] should be neither bleed nor illegal, got "
              f"{dis['bleed_fields']} / {dis['illegal_fields']} / "
              f"{dis['only_extra_disambiguators']}")
        failures += 1

    nomap = score_one(gold + "; task=call", gold)
    if nomap["bleed_fields"]:
        print(f"  FAIL [no map] expected no bleed claim, got {nomap['bleed_fields']}")
        failures += 1

    dup = [dict(input="same", gold_skill="calendar_add", exact=True, skill_ok=True,
                degenerate=False, fields_expected=1, fields_correct=1,
                fields_spurious=0, only_extra_disambiguators=False)] * 4
    other = dict(input="other", gold_skill="calendar_add", exact=False, skill_ok=True,
                 degenerate=False, fields_expected=1, fields_correct=0,
                 fields_spurious=0, only_extra_disambiguators=False)
    agg = aggregate(dup + [other])
    if agg["n"] != 5 or agg["n_unique"] != 2 or abs(agg["exact_match_by_input"] - 0.5) > 1e-9:
        print(f"  FAIL [dedupe] expected n=5 unique=2 by_input=50%, got "
              f"{agg['n']} / {agg['n_unique']} / {agg['exact_match_by_input']}")
        failures += 1
    if abs(agg["exact_match"] - 0.8) > 1e-9:
        print(f"  FAIL [dedupe] row-weighted must STILL be 80%, got {agg['exact_match']}")
        failures += 1

    for pred, gold, right in (("pa_domain", "pa_domain", True), ("pa_domain.\nThat is", "pa_domain", True),
                              ("research_needed", "conversation", False), ("I think it is chat", "conversation", False)):
        if score_category(pred, gold)["right"] != right:
            print(f"  FAIL [category] {pred!r} vs {gold!r}: expected right={right}")
            failures += 1

    print("Scorer self-test:", "PASSED" if not failures else f"{failures} FAILURE(S)")
    return failures


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="edith", choices=sorted(EVAL_TASKS),
                    help="Which brain's adapter, prompt and field list to score (default edith).")
    ap.add_argument("--adapter", default=None, help="defaults to adapters/<task>/adapter")
    ap.add_argument("--model_dir", default=str(Path(__file__).parent / "base_model"))
    ap.add_argument("--holdout", default=None, help="defaults to adapters/<task>/holdout.jsonl")
    ap.add_argument("--limit", type=int, default=0,
                    help="Score only the first N rows. Use 25 for a one-minute signal before "
                         "committing to the full set.")
    ap.add_argument("--max_new_tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS)
    ap.add_argument("--corpus", default=None,
                    help="Corpus the per-skill legal-field map is derived from, for the "
                         "cross-skill-bleed metric. Missing/unreadable = that metric is "
                         "skipped, never an error: an expensive eval must not die for a diagnostic.")
    ap.add_argument("--save", default=None, help="Write per-row predictions to this .jsonl")
    ap.add_argument("--self_test", action="store_true",
                    help="Check the SCORER only — no model, no GPU, no adapter. Seconds.")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(1 if self_test() else 0)

    global _ACTIVE_FIELDS
    _task = EVAL_TASKS[args.task]
    _ACTIVE_FIELDS = _task["fields"]
    _here = Path(__file__).parent
    if args.adapter is None:
        args.adapter = str(_here / _task["adapter_dir"] / "adapter")
    if args.holdout is None:
        args.holdout = str(_here / _task["adapter_dir"] / "holdout.jsonl")
    if args.corpus is None:
        args.corpus = str(_here / _task["corpus"])
    print(f"Task: {args.task}")

    for label, path in (("adapter", args.adapter), ("base model", args.model_dir),
                        ("holdout set", args.holdout)):
        if not Path(path).exists():
            print(f"FATAL: {label} not found at {path}")
            if label == "holdout set":
                print("  The holdout is written when training starts — train the adapter first.")
            sys.exit(1)

    try:
        from train_lora import _keep_awake
        _keep_awake()
    except Exception:
        pass

    rows = [json.loads(l) for l in open(args.holdout, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    print(f"Scoring {len(rows)} held-out rows...")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(args.model_dir)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    if torch.cuda.is_available():
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        base = AutoModelForCausalLM.from_pretrained(
            args.model_dir, device_map={"": 0}, quantization_config=bnb)
    else:
        print("No CUDA — loading on CPU. This will be slow but honest.")
        base = AutoModelForCausalLM.from_pretrained(
            args.model_dir, torch_dtype=torch.float32)
    model = PeftModel.from_pretrained(base, args.adapter)
    model.eval()

    if args.task == "friday":
        results = []
        for i, ex in enumerate(rows, 1):
            enc = tok(_task["prompt"].format(input_text=ex["input"]), return_tensors="pt").to(model.device)
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=6, do_sample=False, pad_token_id=tok.pad_token_id)
            pred = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            results.append({"input": ex["input"], **score_category(pred, ex["output"])})
            if i % 50 == 0:
                print(f"  {i}/{len(rows)}...")
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r) + "\n")
        print_category_report(results)
        return

    skill_fields = build_skill_field_map(args.corpus)
    if skill_fields:
        print(f"  legal-field map: {len(skill_fields)} skills from {Path(args.corpus).name}")
    else:
        print(f"  legal-field map: UNAVAILABLE ({args.corpus}) "
              f"- cross-skill bleed will not be reported")
    scored, records = [], []
    for i, ex in enumerate(rows, 1):
        prompt = _task["prompt"].format(input_text=ex["input"])
        enc = tok(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=args.max_new_tokens,
                                 do_sample=False, pad_token_id=tok.pad_token_id)
        pred = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        s = score_one(pred, ex["output"], skill_fields)
        scored.append({**s, "input": ex["input"]})
        records.append({"input": ex["input"], "gold": ex["output"], "pred": pred, **s})
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}...")

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        print(f"Per-row predictions -> {args.save}  ({len(records)} rows)")

    try:
        print_report(aggregate(scored))
    except Exception as e:
        print(f"(report formatting failed: {type(e).__name__}: {e})")
        print(json.dumps(aggregate(scored), indent=2))
    if args.save:
        print("\n  Read the wrong rows. An aggregate says how much is broken; "
              "only the rows say what is broken.")


if __name__ == "__main__":
    main()
