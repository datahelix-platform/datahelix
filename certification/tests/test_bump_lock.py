"""bump_lock.py moves one pin and refuses everything ADR-0001 forbids."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bump_lock.py"
spec = importlib.util.spec_from_file_location("bump_lock", SCRIPT)
bump_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump_lock)

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
IMG = "ghcr.io/datahelix-platform/mosaic"


def lock(version="0.14.0", digest=D1, image="ghcr.io/bu-neuromics/mosaic"):
    return {
        "_comment": ["kept"],
        "line": "frontier",
        "fixture_version": "1.2.0",
        "components": {
            "mosaic": {"version": version, "digest": digest, "image": image,
                       "repo": "datahelix-platform/mosaic", "status": "published"},
            "aperture": {"version": "0.7.1", "digest": D2, "image": "ghcr.io/bu-neuromics/aperture",
                         "repo": "datahelix-platform/aperture", "status": "published"},
        },
    }


class TestDelta:
    @pytest.mark.parametrize("prev,new,kind", [
        ("0.14.0", "0.14.1", "patch"), ("0.14.0", "0.15.0", "minor"),
        ("0.14.0", "1.0.0", "major"), ("0.14.0", "0.14.0", "none"),
    ])
    def test_kinds(self, prev, new, kind):
        assert bump_lock.delta(prev, new) == kind

    def test_downgrade_refused(self):
        with pytest.raises(bump_lock.Refusal, match="downgrade"):
            bump_lock.delta("0.15.0", "0.14.2")

    def test_bad_semver_refused(self):
        with pytest.raises(bump_lock.Refusal, match="X.Y.Z"):
            bump_lock.delta("0.14.0", "v0.15.0")


class TestBump:
    def test_moves_one_pin_and_repoints_image(self):
        L = lock()
        out = bump_lock.bump(L, "mosaic", "0.15.0", D2, image=IMG)
        assert out == {"changed": "true", "delta": "minor", "previous": "0.14.0",
                       "version": "0.15.0", "image": IMG}
        assert L["components"]["mosaic"] == {"version": "0.15.0", "digest": D2, "image": IMG,
                                             "repo": "datahelix-platform/mosaic", "status": "published"}
        assert L["components"]["aperture"]["version"] == "0.7.1"  # untouched
        assert list(L) == ["_comment", "line", "fixture_version", "components"]  # order kept

    def test_image_optional_keeps_existing(self):
        L = lock()
        bump_lock.bump(L, "mosaic", "0.14.1", D2)
        assert L["components"]["mosaic"]["image"] == "ghcr.io/bu-neuromics/mosaic"

    def test_same_release_is_a_noop(self):
        L = lock(version="0.15.0", digest=D2, image=IMG)
        out = bump_lock.bump(L, "mosaic", "0.15.0", D2, image=IMG)
        assert out["changed"] == "false" and out["delta"] == "none"

    def test_recut_refused(self):
        with pytest.raises(bump_lock.Refusal, match="re-cut"):
            bump_lock.bump(lock(version="0.15.0", digest=D1), "mosaic", "0.15.0", D2)

    def test_unknown_component_refused(self):
        with pytest.raises(bump_lock.Refusal, match="unknown component 'reel'"):
            bump_lock.bump(lock(), "reel", "0.2.0", D2)

    def test_bad_digest_refused(self):
        with pytest.raises(bump_lock.Refusal, match="sha256"):
            bump_lock.bump(lock(), "mosaic", "0.15.0", "sha256:short")

    def test_foreign_image_refused(self):
        with pytest.raises(bump_lock.Refusal, match="outside ghcr.io/datahelix-platform/"):
            bump_lock.bump(lock(), "mosaic", "0.15.0", D2, image="ghcr.io/someone-else/mosaic")


class TestMain:
    def test_writes_file_and_outputs(self, tmp_path, monkeypatch):
        path = tmp_path / "lock.json"
        path.write_text(json.dumps(lock(), indent=2) + "\n")
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        assert bump_lock.main(["mosaic", "0.15.0", D2, "--image", IMG, "--lock", str(path)]) == 0
        text = path.read_text()
        assert text.endswith("}\n") and '"version": "0.15.0"' in text
        assert json.loads(text)["components"]["mosaic"]["digest"] == D2
        assert "changed=true\ndelta=minor\n" in out.read_text()

    def test_noop_exit_zero_changed_false(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "lock.json"
        path.write_text(json.dumps(lock(), indent=2) + "\n")
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        assert bump_lock.main(["mosaic", "0.14.0", D1, "--lock", str(path)]) == 0
        assert "nothing to do" in capsys.readouterr().out
        assert "changed=false" in out.read_text()

    def test_refusal_exit_two_leaves_file(self, tmp_path, capsys):
        path = tmp_path / "lock.json"
        before = json.dumps(lock(), indent=2) + "\n"
        path.write_text(before)
        assert bump_lock.main(["mosaic", "0.13.0", D2, "--lock", str(path)]) == 2
        assert path.read_text() == before
        assert "refused: version 0.13.0 is a downgrade" in capsys.readouterr().err

    def test_real_lock_roundtrips_byte_for_byte(self, tmp_path):
        # The serialization matches the hand-written file, so a bump diff is the pin only.
        real = Path(__file__).resolve().parents[1] / "composition.lock.json"
        data = json.loads(real.read_text())
        assert json.dumps(data, indent=2) + "\n" == real.read_text()
