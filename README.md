# Ultron

A small two-brain personal assistant with its own animated HUD, running on a single 8 GB laptop GPU. One base
language model is loaded once, and two LoRA adapters trained for this project are switched in per message:

- **FRIDAY** (triage) decides which of four domains a message belongs to.
- **EDITH** (assistant) turns an assistant request into one structured skill call.

```
                     ┌── conversation     → base model replies (adapters off)
you ──> FRIDAY ──────┼── pa_domain        → EDITH → "skill=reminder; task=call the bank; day=monday; time=10:00"
   (triage adapter)  │                               → local skill (calendar, reminders, calculator, weather*)
                     ├── code_domain      → recognised, not handled
                     └── research_needed  → recognised, not handled (it would need the web)
```

This is a **portfolio and demonstration project**. The point is the engineering behind the assistant (data
generation, parameter-efficient fine-tuning, evaluation, runtime adapter switching), not state-of-the-art
accuracy. All training data is **fully synthetic**; no real user conversations were used.

## What it demonstrates

| Area | What's here |
|---|---|
| **Synthetic data design** | Template generators with fixed seeds (`data_gen.py`, `friday_data_gen.py`, `code_request_gen.py`). They include "clarify" rows, so EDITH asks instead of inventing a missing time, date or title. Context-dependent follow-ups (`[recent: …] move it to 4pm`) only make sense with the previous turn. The four triage classes are exactly balanced. |
| **QLoRA fine-tuning** | `train_lora.py`: 4-bit NF4 base, LoRA r=16 on the attention projections, seeded so runs are comparable. A `--dry_run` validates every row, the prompt, the tokenizer and the GPU before anything loads. |
| **A real training bug, found and fixed** | With `pad_token == eos_token`, the standard language-modelling collator masks *every* EOS token out of the loss, so the model is never taught to stop and answers run on. Labels here are built from the attention mask instead, so the EOS is a training target, and the trainer prints a check that it is. |
| **Honest evaluation** | `eval_lora.py` scores only rows held out *before* training, split by unique sentence so nothing is on both sides. It reports exact match per unique input (a duplicated sentence can't vote twice), field recall, invented fields, and "cross-skill field bleed" (a field learned from a sibling skill, which a headline score can hide). The scorer has its own self-test. |
| **Runtime adapter switching** | `brains.py` keeps one base model in memory and switches adapters with PEFT (`set_adapter` / `disable_adapter`). |
| **A two-process app** | `ultron.py` (the assistant) and `hud.py` (an animated HUD shown in a native window via pywebview and WebView2, with a core, a skill panel, a status bar and a text box) never import each other. They share small files written atomically (write, then rename), so neither can read the other's half-written state: status one way, panels one way, typed messages the other through a queue folder, and a shutdown signal the page acts on by closing its own window. |
| **Measured, not assumed** | Every fix in the app came from a run. For example, the previous turn is passed as `[recent: …]` context to EDITH only, and for one turn only. Passing it to FRIDAY sent a code request to the assistant brain, and letting it linger made an unrelated message move an old event. |
| **Model supply-chain safety** | `model_safety.py` accepts only `.safetensors` weights (pickle formats can execute code on load) from an allowlisted source, and every script refuses to load a folder that fails it. |
| **Safe execution** | The calculator evaluates arithmetic by walking the syntax tree, never `eval()`. |

## How it was built

The architecture, the brains' roles and the project's direction are the author's. Development was assisted by
Claude (Anthropic), an AI assistant that helped test and document the code. Every result in this README
comes from a run, not from the assistant's say-so.

## Quick start (Windows)

Requires an NVIDIA GPU with about 8 GB of memory and Python 3.11+. The HUD opens in its own native window,
drawn by Windows' built-in WebView2; without pywebview it falls back to a Chrome/Edge window. Install PyTorch for your CUDA version first (see pytorch.org), then
`pip install -r requirements.txt`.

| Step | Run | What it does |
|---|---|---|
| 1 | `1_download_base.bat` | Downloads the base model (safetensors only) into `base_model/` and runs the safety check |
| 2 | `2_generate_data.bat` | Writes `data/edith_train.jsonl` (10,875 rows) and `data/friday_train.jsonl` (8,000 rows) |
| 3 | `3_train_friday.bat` | Dry run, then trains FRIDAY → `adapters/friday/` (5% of unique inputs held out) |
| 4 | `4_train_edith.bat` | Dry run, then trains EDITH → `adapters/edith/` (5% held out) |
| 5 | `5_evaluate.bat` | Scorer self-test, then scores both adapters on their held-out rows |
| 6 | `6_run_ultron.bat` | Starts Ultron and opens the HUD. Type in the HUD or the terminal; say "power down" to close both (`--no-hud` for terminal only) |

Each training run is one-time. Everything is deterministic for a given seed.

## The Windows app

`python build_exe.py --release` packages Ultron with PyInstaller into `dist/Ultron/`: a folder holding
`Ultron.exe` (with its own icon) and an internal folder with Python, PyTorch's GPU libraries and the code. Put
`base_model/` and `adapters/` beside `Ultron.exe` and it runs like any desktop app: the HUD opens as its own window,
and closing that window powers the assistant down. `Ultron.exe --minimized` starts it minimized without taking focus.

### Downloading the app from Releases

The app folder is about 3 GB, mostly PyTorch's GPU libraries, and GitHub allows at most 2 GiB per release file.
`python package_release.py` therefore splits the app into parts (each holding at most 1.9 GiB before compression)
and writes a `SHA256SUMS.txt`:

1. Download every `Ultron-windows-x64.partXofN.zip`, plus `adapters.zip`, from the release.
2. Extract all of them into the same folder. Together they rebuild one `Ultron/` folder.
3. Download the base model into `Ultron/base_model/`. It is Microsoft's Phi-4-mini-instruct (MIT licensed, several
   GB) and is not redistributed here: `1_download_base.bat` does it, and needs Python with `huggingface_hub`.
4. Run `Ultron/Ultron.exe`.

The brains are deliberately **not** inside the exe. They're files next to it, so retraining an adapter never means
rebuilding the app. Other details that only show up once code is packaged:

- **No console.** Output goes to `ultron.log` beside the exe.
- **No Python to launch the HUD with.** The exe restarts itself as the HUD (`Ultron.exe --hud`).
- **Closing the window.** The window belongs to the app, so closing it powers the assistant down at once and
  nothing keeps holding the GPU invisibly. (In the browser fallback, where the app can't see the window close,
  it powers down 15 s after the page stops polling.)
- **How it was launched.** Windows applies a hidden or minimised launch to the first window a child process shows,
  so the HUD is always started with an explicit "show normally" (or "show minimized, don't activate" with `--minimized`).
- **Missing files.** A missing model or adapter is explained in the HUD, followed by a clean shutdown.

## Results

*To be filled in from `5_evaluate.bat` after training. Numbers here will only be ones that were measured.*

| Brain | Held-out rows | Metric | Score |
|---|---|---|---|
| FRIDAY | — | accuracy (4 classes) | — |
| EDITH | — | exact match per unique input | — |
| EDITH | — | field recall | — |

## Layout

```
data_gen.py           EDITH's synthetic data
friday_data_gen.py    FRIDAY's synthetic data (reuses EDITH's sentences, relabelled)
code_request_gen.py   code-request sentences for FRIDAY's code_domain class
train_lora.py         QLoRA training for either brain
eval_lora.py          held-out evaluation for either brain
compare_evals.py      compare two saved evaluations, per skill
ultron.py             the assistant: HUD + terminal input, FRIDAY -> EDITH -> skills, clean power-down
brains.py             one base model, two adapters, switched per call
skills.py             session calendar and reminders, calculator, weather (shown, not fetched)
hud.py                the HUD: local server + animated page, shown in a native window (pywebview / WebView2)
hud_display.py        the panel ultron.py asks the HUD to show
paths.py              where files live: beside the code from source, beside Ultron.exe when packaged
build_exe.py          packages the app (PyInstaller)
model_safety.py       weight-format and source checks
download_base.py      fetches the base model
```

## Limits, stated plainly

- The two adapters are trained once and stay as they are.
- The data is synthetic, so the brains are only as good as the templates. Real phrasing will find gaps.
- The calendar and reminders live in memory for one session. Weather shows the call it would make and
  isn't connected to a service.
- Code and research requests are recognised by FRIDAY but not handled.

## Credits

- Designed and built by **Karan Sharma**.
- Base model: [microsoft/Phi-4-mini-instruct](https://huggingface.co/microsoft/Phi-4-mini-instruct), released
  under the MIT License per its model card (checked 2026-09-25). Its weights aren't included in this repository.
- Libraries: PyTorch, Hugging Face Transformers, PEFT, Datasets, Accelerate, bitsandbytes.

## License

Copyright © 2026 Karan Sharma. **All rights reserved.** This code is published for viewing and evaluation only.
No license is granted to copy, modify, distribute or use it; see [LICENSE](LICENSE). The base model is a separate
work under its own MIT license, and it isn't distributed here.
