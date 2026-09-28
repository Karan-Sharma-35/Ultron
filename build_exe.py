"""Package Ultron as a Windows app: dist/Ultron/Ultron.exe plus its internal folder (Python, PyTorch's GPU
libraries, the code). The base model and the adapters are NOT inside the exe; they're read from next to it
(base_model/, adapters/), so training never means rebuilding.

  python build_exe.py            -> dist/Ultron/   then copy base_model/ and adapters/ in beside Ultron.exe
  python build_exe.py --release  -> the same, with the app's own icon (assets/app.ico) and never the local placeholder

Building needs no trained adapters, and the app says plainly which one is missing when it starts without it.
"""
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).parent
RELEASE = "--release" in sys.argv
# The local placeholder (assets/ultron.ico) is someone else's artwork and is never published; a release build uses the
# app's own icon, drawn from plain shapes (assets/app.ico).
ICON = HERE / "assets" / ("app.ico" if RELEASE else "ultron.ico")

# transformers and friends check each other's installed versions at import time through package metadata,
# which PyInstaller doesn't copy unless told to.
METADATA = ["transformers", "torch", "tokenizers", "safetensors", "accelerate", "peft", "bitsandbytes",
            "huggingface_hub", "numpy", "packaging", "filelock", "tqdm", "regex", "requests", "pyyaml", "psutil"]
# never used at run time; excluding them keeps the folder smaller
EXCLUDE = ["datasets", "matplotlib", "IPython", "tensorflow", "jax", "pandas", "scipy", "sklearn", "torchvision",
           "torchaudio", "tkinter", "pytest",
           # measured in the 26/09 build: pulled in by optional imports, never used by a text-only app (~130 MB)
           "cv2", "av", "pyarrow"]

if RELEASE and not ICON.exists():
    sys.exit("--release needs assets/app.ico")
args = [str(HERE / "ultron.py"), "--name", "Ultron", "--windowed", "--onedir", "--noconfirm", "--clean",
        "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build"), "--specpath", str(HERE / "build"),
        "--collect-binaries", "bitsandbytes", "--collect-submodules", "peft"]
if ICON.exists():
    args += ["--icon", str(ICON)]
else:
    print("(no assets/ultron.ico — building with the default icon)")
for m in METADATA:
    args += ["--copy-metadata", m]
for m in EXCLUDE:
    args += ["--exclude-module", m]

if __name__ == "__main__":
    print(f"Icon: {ICON.name}" + ("  (release)" if RELEASE else ""))
    PyInstaller.__main__.run(args)
    out = HERE / "dist" / "Ultron"
    if RELEASE:
        (out / "RELEASE_BUILD.txt").write_text("Built with --release: the app's own icon (assets/app.ico).\n",
                                               encoding="utf-8", newline="\n")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 2 ** 30
    print(f"\nBuilt {out / 'Ultron.exe'}  ({size:.2f} GB folder)")
    print("Next: copy base_model/ and adapters/ into that folder, beside Ultron.exe, then run it.")
    sys.exit(0)
