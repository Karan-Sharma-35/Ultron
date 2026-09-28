"""The two brains on one base model: load it once (4-bit), switch LoRA adapters per call.

  FRIDAY  message -> conversation | pa_domain | code_domain | research_needed
  EDITH   assistant message -> "skill=<name>; <field>=<value>; ..."
  (none)  adapters off -> the base model chats
"""
from __future__ import annotations

import sys
from pathlib import Path

from eval_lora import parse_skill_call
from train_lora import EDITH_PROMPT_TEMPLATE, PROMPT_TEMPLATE, TRIAGE_CATEGORIES

from paths import APP_DIR

HERE = APP_DIR
BASE = HERE / "base_model"
ADAPTERS = {"friday": HERE / "adapters" / "friday" / "adapter", "edith": HERE / "adapters" / "edith" / "adapter"}


# Without it, the base model introduces itself as the vendor's model (measured on the packaged app).
CHAT_SYSTEM = ("You are Ultron, a personal assistant that runs locally on this computer. If you introduce yourself, "
               "you are Ultron. Answer in one to three sentences, friendly and direct, then stop.")


class Brains:
    def __init__(self, base: Path = BASE, adapters: dict | None = None):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        import model_safety
        adapters = adapters or ADAPTERS
        ok, problems = model_safety.verify_model_directory(str(base))
        if not ok:
            raise RuntimeError("The base model is missing or failed the safety check: " + "; ".join(problems)
                               + ". Put base_model/ beside the app (1_download_base.bat).")
        for name, path in adapters.items():
            if not Path(path).exists():
                raise RuntimeError(f"No {name.upper()} adapter at {path}. Train it first "
                                   f"({'3_train_friday' if name == 'friday' else '4_train_edith'}.bat) and put adapters/ beside the app.")
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(str(base))
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        if torch.cuda.is_available():
            bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                     bnb_4bit_compute_dtype=torch.bfloat16)
            model = AutoModelForCausalLM.from_pretrained(str(base), quantization_config=bnb, device_map={"": 0})
        else:
            print("(no CUDA — running on the CPU; expect slow replies)")
            model = AutoModelForCausalLM.from_pretrained(str(base), torch_dtype=torch.float32)
        self.model = PeftModel.from_pretrained(model, str(adapters["friday"]), adapter_name="friday")
        self.model.load_adapter(str(adapters["edith"]), adapter_name="edith")
        self.model.eval()

    def generate(self, prompt: str, max_new_tokens: int, adapter: str | None, no_repeat_ngram_size: int = 0) -> str:
        enc = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            if adapter is None:
                with self.model.disable_adapter():
                    out = self.model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                              no_repeat_ngram_size=no_repeat_ngram_size,
                                              pad_token_id=self.tok.pad_token_id)
            else:
                self.model.set_adapter(adapter)
                out = self.model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                          pad_token_id=self.tok.pad_token_id)
        return self.tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    def friday(self, text: str) -> str:
        raw = self.generate(PROMPT_TEMPLATE.format(input_text=text), 6, "friday")
        domain = raw.split()[0].strip(".,:;") if raw.split() else ""
        return domain if domain in TRIAGE_CATEGORIES else "conversation"

    def edith(self, text: str, recent: str = "") -> tuple[str, str | None, dict]:
        """EDITH gets the previous action as "[recent: ...]" — the form her training data uses — because a
        follow-up like "move it to 4pm" only means something next to it. (FRIDAY does not: with a calendar
        action always in front of her, a code request was measured going to EDITH.)"""
        call = self.generate(EDITH_PROMPT_TEMPLATE.format(input_text=f"{recent} {text}".strip()), 48, "edith")
        line = call.splitlines()[0] if call else ""
        skill, fields = parse_skill_call(line)
        return line, skill, fields

    def chat(self, text: str) -> str:
        prompt = self.tok.apply_chat_template([{"role": "system", "content": CHAT_SYSTEM},
                                               {"role": "user", "content": text}], tokenize=False,
                                              add_generation_prompt=True)
        # Greedy chat on the base model was measured looping ("octopuses have three hearts" twice in one reply).
        # A repetition PENALTY was tried first and made it worse: it also penalises the end-of-turn token, which
        # already appears twice in every chat prompt, so the model stopped stopping (measured). Blocking repeated
        # 6-token phrases stops the loop without touching single tokens. Chat only — FRIDAY and EDITH are untouched.
        reply = self.generate(prompt, 160, None, no_repeat_ngram_size=6)
        return trim_to_sentence(reply)


def trim_to_sentence(text: str) -> str:
    """A reply that ran into the token cap ends mid-sentence; keep it up to its last complete sentence."""
    text = text.strip()
    if not text or text[-1] in ".!?\"')":
        return text
    cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
    return text[:cut + 1] if cut > 0 else text


def test_a_capped_reply_ends_on_a_whole_sentence():
    assert trim_to_sentence("One. Two! Three and then") == "One. Two!"
    assert trim_to_sentence("Complete.") == "Complete."
    assert trim_to_sentence("no stop at all") == "no stop at all"
