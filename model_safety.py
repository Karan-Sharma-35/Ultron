"""Refuse model weights that could run code on load: .safetensors is accepted; pickle-based formats
(.bin/.pt/.pth/.ckpt/.pkl) and unknown extensions are refused. Also an allowlist of known sources."""
from __future__ import annotations

import json
from pathlib import Path


_SAFE_MODEL_EXTENSIONS = {".safetensors"}
_UNSAFE_MODEL_EXTENSIONS = {".pt", ".pth", ".bin", ".ckpt", ".pkl"}


VERIFIED_MODEL_SOURCES = {
    "microsoft/Phi-4-mini-instruct",
}


def is_safe_model_file(path: str | Path) -> tuple[bool, str]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in _SAFE_MODEL_EXTENSIONS:
        return True, "safetensors format — safe by design, no code-execution capability"
    if ext in _UNSAFE_MODEL_EXTENSIONS:
        return False, (
            f"REFUSED: '{ext}' is a legacy pickle-based format that can execute arbitrary "
            f"code on load. Only .safetensors is ever accepted, no exceptions."
        )
    return False, f"REFUSED: unrecognized model file extension '{ext}' — not on the safe list."


def is_verified_source(repo_id: str) -> bool:
    return repo_id in VERIFIED_MODEL_SOURCES


def verify_model_directory(model_dir: str | Path) -> tuple[bool, list[str]]:
    model_dir = Path(model_dir)
    problems = []
    if not model_dir.exists():
        return False, [f"Directory does not exist: {model_dir}"]

    found_any_weights = False
    for f in model_dir.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in _SAFE_MODEL_EXTENSIONS:
            found_any_weights = True
        elif ext in _UNSAFE_MODEL_EXTENSIONS:
            found_any_weights = True
            problems.append(f"Unsafe weight file found: {f.name} ({ext})")

    if not found_any_weights:
        problems.append("No weight files found at all — nothing to verify, likely an incomplete download.")

    return len(problems) == 0, problems


def test_safetensors_is_accepted():
    ok, reason = is_safe_model_file("model.safetensors")
    assert ok is True
    assert "safe by design" in reason


def test_legacy_pickle_formats_are_refused():
    for ext in [".pt", ".pth", ".bin", ".ckpt", ".pkl"]:
        ok, reason = is_safe_model_file(f"model{ext}")
        assert ok is False, f"{ext} must be refused, not silently accepted"
        assert "REFUSED" in reason
        assert "arbitrary" in reason or "not on the safe list" in reason


def test_unknown_extension_is_refused_not_assumed_safe():
    ok, reason = is_safe_model_file("model.weird_extension")
    assert ok is False
    assert "REFUSED" in reason


def test_verified_source_allowlist_is_real_and_narrow():
    assert is_verified_source("microsoft/Phi-4-mini-instruct") is True

    assert is_verified_source("some-random-user/totally-legit-model") is False


def test_verify_model_directory_catches_unsafe_files():
    import tempfile
    tmpdir = Path(tempfile.mkdtemp())
    try:
        (tmpdir / "model.safetensors").write_bytes(b"fake safetensors content")
        (tmpdir / "config.json").write_text(json.dumps({"model_type": "test"}))
        ok, problems = verify_model_directory(tmpdir)
        assert ok is True
        assert problems == []

        (tmpdir / "pytorch_model.bin").write_bytes(b"fake pickle content")
        ok2, problems2 = verify_model_directory(tmpdir)
        assert ok2 is False
        assert any("pytorch_model.bin" in p for p in problems2)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_verify_model_directory_flags_missing_weights():
    import tempfile
    tmpdir = Path(tempfile.mkdtemp())
    try:
        (tmpdir / "config.json").write_text(json.dumps({"model_type": "test"}))
        ok, problems = verify_model_directory(tmpdir)
        assert ok is False
        assert any("No weight files found" in p for p in problems)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_verify_model_directory_missing_dir():
    ok, problems = verify_model_directory("/nonexistent/path/at/all")
    assert ok is False
    assert "does not exist" in problems[0]
