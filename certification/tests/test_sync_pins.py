"""sync_pins.py applies the lock's pin to every recipe that pins the component (#139)."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "certification" / "scripts" / "sync_pins.py"
spec = importlib.util.spec_from_file_location("sync_pins", SCRIPT)
sync_pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_pins)

D_NEW = "sha256:" + "c" * 64
IMG = "ghcr.io/datahelix-platform/mosaic"


@pytest.fixture
def repo(tmp_path):
    """A copy of the real lock and recipes, with mosaic bumped in the lock only."""
    lock = json.loads((ROOT / "certification" / "composition.lock.json").read_text())
    lock["components"]["mosaic"].update(version="9.9.9", digest=D_NEW, image=IMG)
    lock_path = tmp_path / "composition.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    shutil.copytree(ROOT / "deploy" / "recipes", tmp_path / "recipes")
    return tmp_path, lock_path, lock


def test_real_recipes_follow_the_lock(repo):
    tmp, lock_path, lock = repo
    aperture_before = {
        p: p.read_text().count(lock["components"]["aperture"]["digest"])
        for p in (tmp / "recipes").glob("*/Dockerfile")
    }
    changed = sync_pins.sync("mosaic", lock, tmp / "recipes")
    names = {p.parent.name + "/" + p.name for p in changed}
    assert {"demo/Dockerfile", "demo-reel/Dockerfile", "solo/Dockerfile",
            "ide/docker-compose.yml"} <= names

    for recipe in ("demo", "demo-reel", "solo"):
        text = (tmp / "recipes" / recipe / "Dockerfile").read_text()
        assert f"ARG MOSAIC_IMAGE={IMG}@{D_NEW}\n" in text
    ide = (tmp / "recipes" / "ide" / "docker-compose.yml").read_text()
    assert "${MOSAIC_VERSION:-9.9.9}" in ide
    # The other component's pins are untouched.
    for p, n in aperture_before.items():
        assert p.read_text().count(lock["components"]["aperture"]["digest"]) == n
    assert "${APERTURE_VERSION:-" + lock["components"]["aperture"]["version"] + "}" in ide


def test_gated_check_pins_pass_after_sync(repo):
    tmp, lock_path, lock = repo
    sync_pins.sync("mosaic", lock, tmp / "recipes")
    for recipe in ("demo", "demo-reel", "solo"):
        d = tmp / "recipes" / recipe
        args = [sys.executable, str(d / "check_pins.py"), str(d / "Dockerfile")]
        if recipe == "demo-reel":
            args.append(str(d / "docker-compose.yml"))
        args.append(str(lock_path))
        r = subprocess.run(args, capture_output=True, text=True)
        assert r.returncode == 0, f"{recipe}: {r.stdout}{r.stderr}"


def test_idempotent(repo):
    tmp, _, lock = repo
    sync_pins.sync("mosaic", lock, tmp / "recipes")
    assert sync_pins.sync("mosaic", lock, tmp / "recipes") == []


def test_unknown_component_refused(repo):
    tmp, _, lock = repo
    with pytest.raises(KeyError):
        sync_pins.sync("bogus", lock, tmp / "recipes")


def test_only_the_named_arg_moves():
    entry = {"image": IMG, "digest": D_NEW, "version": "1.2.3"}
    text = "ARG MOSAIC_IMAGE=old@sha256:x\nARG MOSAIC_IMAGE_EXTRA=keep\nARG APERTURE_IMAGE=keep\n"
    out = sync_pins.sync_text(text, "Dockerfile", "mosaic", entry)
    assert out.splitlines() == [f"ARG MOSAIC_IMAGE={IMG}@{D_NEW}",
                                "ARG MOSAIC_IMAGE_EXTRA=keep", "ARG APERTURE_IMAGE=keep"]
