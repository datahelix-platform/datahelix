"""read_lock.py hard-codes no image path: manual runs take it from an argument or the lock."""
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "read_lock.py"
spec = importlib.util.spec_from_file_location("read_lock", SCRIPT)
read_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(read_lock)

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64


def _run(capsys, monkeypatch, *argv):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert read_lock.main(list(argv)) == 0
    return dict(l.split("=", 1) for l in capsys.readouterr().out.splitlines())


def _lock(tmp_path):
    p = tmp_path / "lock.json"
    p.write_text(json.dumps({"components": {
        "mosaic": {"version": "1", "digest": D1, "image": "ghcr.io/org/mosaic"},
        "aperture": {"version": "2", "digest": D2, "image": "ghcr.io/org/aperture"},
    }}))
    return str(p)


MANUAL = ["--mosaic-version", "1", "--mosaic-digest", D1,
          "--aperture-version", "2", "--aperture-digest", D2]


def test_manual_dispatch_defaults_to_lock_images(capsys, monkeypatch, tmp_path):
    out = _run(capsys, monkeypatch, *MANUAL, "--lock-file", _lock(tmp_path))
    assert out["mosaic_ref"] == f"ghcr.io/org/mosaic@{D1}"
    assert out["aperture_ref"] == f"ghcr.io/org/aperture@{D2}"


def test_manual_dispatch_image_args_override(capsys, monkeypatch, tmp_path):
    out = _run(capsys, monkeypatch, *MANUAL, "--lock-file", _lock(tmp_path),
               "--mosaic-image", "ghcr.io/x/mosaic")
    assert out["mosaic_ref"] == f"ghcr.io/x/mosaic@{D1}"
    assert out["aperture_ref"] == f"ghcr.io/org/aperture@{D2}"


def test_lock_path_unchanged(capsys, monkeypatch, tmp_path):
    out = _run(capsys, monkeypatch, _lock(tmp_path))
    assert out["mosaic_image"] == "ghcr.io/org/mosaic"
