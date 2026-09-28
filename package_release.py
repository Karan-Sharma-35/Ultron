"""Turn the built app into files for a GitHub release.

GitHub's limits (docs.github.com, read 28/09/2026): each file attached to a release must be under 2 GiB, a release may
have up to 1000 files, and there is no limit on a release's total size or its bandwidth. The repository itself blocks
files over 100 MiB, so the app never goes into git: it goes into a release.

The app folder is about 3 GB (PyTorch's GPU libraries alone are ~2.6 GB), so it ships as several zips. Each zip holds at
most 1.9 GiB of UNCOMPRESSED data, so no zip can pass the limit whatever the compression does. Extract every part into
the same folder and they rebuild one Ultron/ folder.

  python build_exe.py --release
  python package_release.py        -> release/Ultron-windows-x64.part1ofN.zip ... , adapters.zip (once trained), SHA256SUMS.txt

The base model is not packaged: it's Microsoft's, several GB, and downloaded from Hugging Face (1_download_base.bat).
"""
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
APP = HERE / "dist" / "Ultron"
OUT = HERE / "release"
PART_LIMIT = int(1.9 * 2 ** 30)
# left behind by running the app, never part of it
RUNTIME = {"hud.log", "ultron.log", "hud_state.json", "hud_display.json", "hud_shutdown.json"}
RUNTIME_DIRS = {"hud_input_queue", ".hud_browser_profile", "base_model", "adapters"}


def app_files() -> list[Path]:
    out = []
    for f in APP.rglob("*"):
        rel = f.relative_to(APP)
        if not f.is_file() or f.name in RUNTIME or rel.parts[0] in RUNTIME_DIRS or rel.parts[0].endswith(".WebView2"):
            continue
        out.append(f)
    return out


def split(files: list[Path]) -> list[list[Path]]:
    """First-fit, biggest files first, each part at most PART_LIMIT bytes before compression."""
    parts: list[tuple[int, list[Path]]] = []
    for f in sorted(files, key=lambda p: p.stat().st_size, reverse=True):
        size = f.stat().st_size
        if size > PART_LIMIT:
            sys.exit(f"{f} alone is {size / 2 ** 30:.2f} GiB, over the part limit")
        for i, (used, group) in enumerate(parts):
            if used + size <= PART_LIMIT:
                parts[i] = (used + size, group + [f])
                break
        else:
            parts.append((size, [f]))
    return [group for _, group in parts]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    if not (APP / "Ultron.exe").exists():
        sys.exit("No dist/Ultron/Ultron.exe: run  python build_exe.py --release  first")
    if not (APP / "RELEASE_BUILD.txt").exists():
        sys.exit("dist/Ultron wasn't built with --release (it may carry the local placeholder icon): "
                 "run  python build_exe.py --release  first")
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    groups = split(app_files())
    made = []
    for i, group in enumerate(groups, 1):
        z = OUT / f"Ultron-windows-x64.part{i}of{len(groups)}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in group:
                zf.write(f, Path("Ultron") / f.relative_to(APP))
        made.append(z)
        print(f"{z.name}: {len(group)} files, {z.stat().st_size / 2 ** 30:.2f} GiB")
    adapters = [p for name in ("friday", "edith") for p in (HERE / "adapters" / name / "adapter").glob("*") if p.is_file()]
    if adapters:
        z = OUT / "adapters.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in adapters:
                zf.write(f, Path("Ultron") / f.relative_to(HERE))
        made.append(z)
        print(f"{z.name}: {len(adapters)} files, {z.stat().st_size / 2 ** 20:.1f} MiB")
    else:
        print("No trained adapters yet (adapters/friday/adapter, adapters/edith/adapter): adapters.zip skipped")
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{sha256(z)}  {z.name}\n" for z in made), encoding="utf-8", newline="\n")
    too_big = [z.name for z in made if z.stat().st_size >= 2 ** 31]
    if too_big:
        sys.exit(f"over GitHub's 2 GiB per file: {too_big}")
    print(f"Done: {len(made)} files in {OUT}, every one under 2 GiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
