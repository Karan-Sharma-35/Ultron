"""Download the base model both brains are trained on, safetensors only, then run the safety check.

  python download_base.py      -> base_model/
"""
from pathlib import Path

from huggingface_hub import snapshot_download

import model_safety

REPO_ID = "microsoft/Phi-4-mini-instruct"
LOCAL_DIR = Path(__file__).parent / "base_model"

if __name__ == "__main__":
    print(f"Downloading {REPO_ID} to {LOCAL_DIR} (safetensors only)...")
    snapshot_download(repo_id=REPO_ID, local_dir=str(LOCAL_DIR),
                      ignore_patterns=["*.bin", "*.pt", "*.ckpt", "*.h5", "*.msgpack"])
    ok, problems = model_safety.verify_model_directory(str(LOCAL_DIR))
    print("Safety check:", "passed" if ok else "FAILED")
    for p in problems:
        print("  -", p)
