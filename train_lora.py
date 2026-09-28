"""Train one of Ultron's two brains as a LoRA adapter on the base model.

  python train_lora.py --task friday --dry_run   # validate data + environment, load nothing
  python train_lora.py --task friday             # FRIDAY: which of four domains a message belongs to
  python train_lora.py --task edith              # EDITH: which assistant skill, with which fields

Both brains share one frozen base model (loaded in 4-bit, QLoRA) and differ only in a small adapter,
so the app can keep one model in memory and switch adapters per turn.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import model_safety

HERE = Path(__file__).parent

TRIAGE_CATEGORIES = ["conversation", "pa_domain", "code_domain", "research_needed"]

PROMPT_TEMPLATE = (
    "Classify the following message into exactly one category: "
    "conversation, pa_domain, code_domain, or research_needed.\n\n"
    "pa_domain = calendar, reminders, weather, calculator, or any other "
    "personal-assistant task.\n"
    "code_domain = anything about writing, testing, or explaining code.\n"
    "research_needed = requires current, real-world information Ultron "
    "doesn't already know.\n"
    "conversation = general chat, nothing above applies.\n\n"
    "Message: {input_text}\n\n"
    "Category:"
)


def _validate_triage(output: str) -> "str | None":
    if output not in TRIAGE_CATEGORIES:
        return f"not one of {TRIAGE_CATEGORIES}"
    return None


EDITH_SKILLS = [
    "calendar_add", "calendar_delete", "calendar_update", "reminder",
    "calculator", "weather", "conversation", "clarify", "research_needed",
]
EDITH_FIELDS = ["day", "title", "time", "question", "task", "expression",
                "new_time", "location"]

EDITH_PROMPT_TEMPLATE = (
    "You are Ultron's personal-assistant brain. Convert the message into "
    "exactly one skill call.\n\n"
    "Reply with a single line:\n"
    "skill=<name>; <field>=<value>; <field>=<value>\n\n"
    "skill is one of: " + ", ".join(EDITH_SKILLS) + ".\n"
    "field is one of: " + ", ".join(EDITH_FIELDS) + ".\n"
    "Use only what the message actually says. Do not invent a time, a date, "
    "a title or a location that is not there — if something needed is "
    "missing, use skill=clarify.\n\n"
    "Message: {input_text}\n\n"
    "Skill:"
)


def _validate_edith(output: str) -> "str | None":
    parts = [p.strip() for p in output.split(";") if p.strip()]
    if not parts:
        return "is empty"
    head = parts[0]
    if not head.startswith("skill="):
        return "must start with 'skill='"
    name = head.split("=", 1)[1].strip()
    if name not in EDITH_SKILLS:
        return f"has unknown skill {name!r} (known: {', '.join(EDITH_SKILLS)})"
    for part in parts[1:]:
        if "=" not in part:
            return f"has a fragment that is not key=value: {part!r}"
        key = part.split("=", 1)[0].strip()
        if key not in EDITH_FIELDS:
            return f"has unknown field {key!r} (known: {', '.join(EDITH_FIELDS)})"
    return None


TASKS = {
    "friday": {
        "prompt_template": PROMPT_TEMPLATE,
        "validate": _validate_triage,
        "data": HERE / "data" / "friday_train.jsonl",
        "output_dir": HERE / "adapters" / "friday",
        "what": "FRIDAY — routes a message to one of four domains",
        "holdout": 0.05,
    },
    "edith": {
        "prompt_template": EDITH_PROMPT_TEMPLATE,
        "validate": _validate_edith,
        "data": HERE / "data" / "edith_train.jsonl",
        "output_dir": HERE / "adapters" / "edith",
        "what": "EDITH — turns a message into one personal-assistant skill call",
        "holdout": 0.05,
    },
}


def split_holdout(examples: list[dict], fraction: float, seed: int = 20260828):
    """Hold out a fraction of UNIQUE inputs, so no sentence is on both sides of the split."""
    if fraction <= 0:
        return examples, []
    by_input: dict[str, list[dict]] = {}
    for ex in examples:
        by_input.setdefault(ex["input"], []).append(ex)
    keys = sorted(by_input)
    random.Random(seed).shuffle(keys)
    n_hold = max(1, int(len(keys) * fraction))
    hold_keys = set(keys[:n_hold])
    train = [ex for k in keys if k not in hold_keys for ex in by_input[k]]
    hold = [ex for k in keys if k in hold_keys for ex in by_input[k]]
    return train, hold


def task_prompt_text(example: dict, task: dict) -> str:
    return task["prompt_template"].format(input_text=example["input"])


def build_task_training_text(example: dict, task: dict, eos: str = "") -> str:
    return f"{task_prompt_text(example, task)} {example['output']}{eos}"


def load_task_dataset(path: Path, task: dict) -> list[dict]:
    """Every row must parse and pass the task's output validator — a bad row stops the run before
    the model loads, never silently trains."""
    examples, problems = [], []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ex = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"  line {lineno}: not valid JSON ({e})")
                continue
            if "input" not in ex or "output" not in ex:
                problems.append(f"  line {lineno}: needs both 'input' and 'output' keys")
                continue
            why = task["validate"](ex["output"])
            if why:
                problems.append(f"  line {lineno}: output {ex['output'][:60]!r} {why}")
                continue
            examples.append(ex)
    if problems:
        shown = problems[:10]
        more = f"\n  ... and {len(problems) - 10} more" if len(problems) > 10 else ""
        raise ValueError(f"{len(problems)} unusable row(s) in {path}:\n" + "\n".join(shown) + more)
    if not examples:
        raise ValueError(f"{path} produced ZERO usable rows — nothing to train on.")
    return examples


def _keep_awake() -> None:
    """Windows: stop idle sleep from ending a long run (the display may still turn off)."""
    if sys.platform != "win32":
        return
    try:
        import atexit
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        if ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) == 0:
            print("  (could not request stay-awake; check the power plan yourself)")
            return
        atexit.register(lambda: ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS))
        print("  stay-awake: on (idle sleep blocked; the display may still turn off)")
    except Exception as e:
        print(f"  (stay-awake unavailable: {type(e).__name__} — the run continues)")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="friday", choices=sorted(TASKS))
    parser.add_argument("--model_dir", default=str(HERE / "base_model"))
    parser.add_argument("--data", default=None, help="defaults to the task's own dataset")
    parser.add_argument("--output_dir", default=None, help="defaults to the task's own adapter dir")
    parser.add_argument("--holdout", type=float, default=None,
                        help="Fraction of UNIQUE INPUTS held out of training and written to "
                             "<output_dir>/holdout.jsonl. Pass 0 to train on everything.")
    parser.add_argument("--dry_run", action="store_true",
                        help="Validate the dataset, the prompt and the environment, print one rendered "
                             "training example, and exit BEFORE loading the model.")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--grad_accum", type=int, default=1)
    parser.add_argument("--max_length", type=int, default=256)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument("--lora_r", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=32)
    parser.add_argument("--resume_from_checkpoint", default=None,
                        help="A checkpoint dir to resume from, or 'auto' for the newest under "
                             "<output_dir>/checkpoints.")
    parser.add_argument("--load_in_4bit", action="store_true", default=True,
                        help="QLoRA (default). On an 8 GB card, full precision offloads layers and breaks "
                             "gradient flow.")
    parser.add_argument("--no_load_in_4bit", dest="load_in_4bit", action="store_false")
    parser.add_argument("--seed", type=int, default=20260901,
                        help="Seeds LoRA init, dropout and the shuffle, so two runs on the same data are "
                             "comparable and a data change can be told apart from run-to-run variance.")
    args = parser.parse_args()
    task = TASKS[args.task]
    args.data = args.data or str(task["data"])
    args.output_dir = args.output_dir or str(task["output_dir"])
    if args.holdout is None:
        args.holdout = task.get("holdout", 0.0)
    print(f"Task: {args.task} — {task['what']}")

    if args.dry_run:
        examples = load_task_dataset(Path(args.data), task)
        print(f"  data:       {args.data}")
        _tr, _ho = split_holdout(examples, args.holdout)
        print(f"  rows:       {len(examples)} usable ({len(set(e['input'] for e in examples))} unique inputs)")
        print(f"  split:      {len(_tr)} train / {len(_ho)} holdout" if _ho else "  split:      no holdout")
        print(f"  output_dir: {args.output_dir}")
        outs = {}
        for ex in examples:
            head = ex["output"].split(";")[0].strip()
            outs[head] = outs.get(head, 0) + 1
        print(f"  classes:    {sorted(outs.items(), key=lambda kv: -kv[1])[:9]}")
        print("\n--- one fully rendered training example ---")
        print(build_task_training_text(examples[0], task))
        print("--- end ---\n")
        missing = []
        for name in ("torch", "transformers", "peft", "datasets", "bitsandbytes", "accelerate"):
            try:
                __import__(name)
            except Exception as e:
                missing.append(f"{name} ({type(e).__name__})")
        if missing:
            print("  ⛔ MISSING: " + ", ".join(missing) + "  — pip install -r requirements.txt")
            sys.exit(1)
        import torch as _t
        print(f"  torch:      {_t.__version__}")
        try:
            from transformers import AutoTokenizer as _AT
            if _AT.from_pretrained(args.model_dir).eos_token:
                print("  eos_token:  present — answers will be taught to STOP")
            else:
                print("  ⛔ no eos_token on this tokenizer — the model would never learn to stop.")
                sys.exit(1)
        except SystemExit:
            raise
        except Exception as _e:
            print(f"  ⚠ could not check eos_token ({type(_e).__name__}) — is the base model downloaded?")
        if not _t.cuda.is_available():
            print("  ⛔ CUDA not available — training would fall back to CPU and never finish.")
            sys.exit(1)
        free, total = _t.cuda.mem_get_info()
        print(f"  gpu:        {_t.cuda.get_device_name(0)}  {free / 1024**3:.1f} GB free of {total / 1024**3:.1f} GB")
        if free / 1024**3 < 5.0:
            print("  ⚠ under 5 GB free — close other GPU apps first.")
        print("\nDry run OK. Nothing was trained, nothing was written.")
        return

    _keep_awake()

    # Refuse a base-model folder that fails the safety check (pickle weights, remote code, …).
    is_safe, problems = model_safety.verify_model_directory(args.model_dir)
    if not is_safe:
        print(f"FATAL: model safety check failed for {args.model_dir}:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"model safety check passed for {args.model_dir}")

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer,
                              TrainingArguments, default_data_collator)
    from transformers import set_seed

    set_seed(args.seed)
    print(f"  seed:       {args.seed}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if args.load_in_4bit and torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
        model = AutoModelForCausalLM.from_pretrained(args.model_dir, quantization_config=bnb_config,
                                                     device_map={"": 0})
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir, torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None)

    model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha,
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
                                             lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    examples = load_task_dataset(Path(args.data), task)
    examples, holdout = split_holdout(examples, args.holdout)
    if holdout:
        hold_path = Path(args.output_dir) / "holdout.jsonl"
        hold_path.parent.mkdir(parents=True, exist_ok=True)
        with open(hold_path, "w", encoding="utf-8") as f:
            for ex in holdout:
                f.write(json.dumps(ex) + "\n")
        print(f"Held out {len(holdout)} rows -> {hold_path} (never trained on)")
    print(f"Training on {len(examples)} examples.")

    # The EOS token is appended AND kept as a training target. With pad == eos, the usual LM collator
    # masks every EOS out of the loss, and the model never learns to stop generating — so labels are
    # built from the attention mask instead: every real token (EOS included) is a target, padding isn't.
    eos = tokenizer.eos_token or ""
    texts = [build_task_training_text(ex, task, eos) for ex in examples]
    lens = [len(tokenizer(t)["input_ids"]) for t in texts]
    keep = [i for i, n in enumerate(lens) if n <= args.max_length]
    if len(keep) < len(texts):
        print(f"  dropped {len(texts) - len(keep)} rows longer than {args.max_length} tokens — never trained truncated")
    dataset = Dataset.from_dict({"text": [texts[i] for i in keep]})

    def tokenize(batch):
        enc = tokenizer(batch["text"], truncation=True, max_length=args.max_length, padding="max_length")
        enc["labels"] = [[tok if m == 1 else -100 for tok, m in zip(ids, mask)]
                         for ids, mask in zip(enc["input_ids"], enc["attention_mask"])]
        return enc

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])
    row0 = tokenized[0]
    last = max(i for i, m in enumerate(row0["attention_mask"]) if m == 1)
    ok = row0["input_ids"][last] == tokenizer.eos_token_id and row0["labels"][last] == tokenizer.eos_token_id
    print(f"  eos label:  {'the EOS is a training target' if ok else '⛔ the EOS is NOT a target — run-on will recur'}")

    trainer = Trainer(
        model=model,
        args=TrainingArguments(output_dir=str(Path(args.output_dir) / "checkpoints"),
                               num_train_epochs=args.epochs, per_device_train_batch_size=args.batch_size,
                               gradient_accumulation_steps=args.grad_accum, learning_rate=args.learning_rate,
                               logging_steps=10, save_strategy="epoch", bf16=torch.cuda.is_available(),
                               report_to="none"),
        train_dataset=tokenized,
        data_collator=default_data_collator,
    )

    resume = None
    if args.resume_from_checkpoint == "auto":
        found = sorted((Path(args.output_dir) / "checkpoints").glob("checkpoint-*"),
                       key=lambda p: int(p.name.split("-")[-1]) if p.name.split("-")[-1].isdigit() else -1)
        resume = str(found[-1]) if found else None
        print(f"Resuming from {resume}" if resume else "No checkpoint found — starting fresh.")
    elif args.resume_from_checkpoint:
        resume = args.resume_from_checkpoint
    trainer.train(resume_from_checkpoint=resume)

    adapter_path = Path(args.output_dir) / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    print(f"\nDone. Adapter saved to: {adapter_path}")
    print(f"Score it:  python eval_lora.py --task {args.task}")


if __name__ == "__main__":
    main()
