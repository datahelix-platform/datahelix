"""Tests for certification/scripts/read_lock.py pin resolution (#127).

Image paths come from the lock, never from code: the explicit-pin form
(workflow_dispatch backfill) defaults each image to the lock's ``image`` and
accepts an override, so a registry move is a lock edit only.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "read_lock.py"
_spec = importlib.util.spec_from_file_location("read_lock", _SCRIPT)
read_lock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(read_lock)

D_MO = "sha256:" + "b" * 64
D_AP = "sha256:" + "a" * 64


def _lock(tmp_path: Path, mosaic_key: str = "mosaic") -> Path:
    doc = {
        "line": "frontier",
        "fixture_version": "9.9.9",
        "components": {
            mosaic_key: {"version": "1.0.0", "digest": D_MO, "image": "ghcr.io/example-org/mosaic"},
            "aperture": {"version": "2.0.0", "digest": D_AP, "image": "ghcr.io/example-org/aperture"},
        },
    }
    p = tmp_path / "composition.lock.json"
    p.write_text(json.dumps(doc))
    return p


def _run(argv: list[str], capsys, monkeypatch) -> dict[str, str]:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert read_lock.main(argv) == 0
    out = capsys.readouterr().out
    return dict(line.split("=", 1) for line in out.splitlines())


def _explicit(*extra: str) -> list[str]:
    return [
        "--mosaic-version", "3.0.0", "--mosaic-digest", D_MO,
        "--aperture-version", "4.0.0", "--aperture-digest", D_AP,
        *extra,
    ]


@pytest.mark.parametrize("mosaic_key", ["mosaic", "hippo"])
def test_lock_form_reads_images_from_lock(tmp_path, capsys, monkeypatch, mosaic_key):
    pins = _run([str(_lock(tmp_path, mosaic_key))], capsys, monkeypatch)
    assert pins["mosaic_ref"] == f"ghcr.io/example-org/mosaic@{D_MO}"
    assert pins["aperture_ref"] == f"ghcr.io/example-org/aperture@{D_AP}"
    assert pins["published"] == "true"


def test_explicit_form_derives_images_from_lock(tmp_path, capsys, monkeypatch):
    pins = _run(_explicit("--image-lock", str(_lock(tmp_path))), capsys, monkeypatch)
    assert pins["mosaic_image"] == "ghcr.io/example-org/mosaic"
    assert pins["aperture_image"] == "ghcr.io/example-org/aperture"
    # versions/digests still come from the explicit pins, not the lock
    assert pins["mosaic_version"] == "3.0.0"
    assert pins["mosaic_ref"] == f"ghcr.io/example-org/mosaic@{D_MO}"


def test_explicit_form_image_override(tmp_path, capsys, monkeypatch):
    pins = _run(
        _explicit("--image-lock", str(_lock(tmp_path)), "--mosaic-image", "ghcr.io/other/mosaic"),
        capsys, monkeypatch,
    )
    assert pins["mosaic_image"] == "ghcr.io/other/mosaic"
    assert pins["aperture_image"] == "ghcr.io/example-org/aperture"


def test_explicit_form_defaults_to_repo_lock(capsys, monkeypatch):
    repo_lock = read_lock.lock_images(read_lock.DEFAULT_LOCK)
    assert repo_lock["mosaic"] and repo_lock["aperture"]
    pins = _run(_explicit(), capsys, monkeypatch)
    assert pins["mosaic_image"] == repo_lock["mosaic"]
    assert pins["aperture_image"] == repo_lock["aperture"]


def test_script_hard_codes_no_image_path():
    assert "ghcr.io" not in _SCRIPT.read_text()
