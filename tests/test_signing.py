"""Signed recordings: device key, chunk chain, manifest signature, verify."""
import json
import os
import stat
from pathlib import Path

import pytest

from car_use import signing
from car_use.kernel.policy import Audit
from car_use.record import Recorder, RecordError
from car_use.run import main

pytest.importorskip("cryptography")


@pytest.fixture
def signed(sim, tmp_path):
    v = sim("crane-j1939")
    out = tmp_path / "rec"
    meta = Recorder(v, out_dir=out, decode="j1939", sign=True, asset_id="CRANE-07").run(seconds=2.5)
    return out, meta


def test_device_key_is_private_and_stable():
    k1 = signing.device_key()
    p = signing.key_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert signing.public_hex(signing.device_key()) == signing.public_hex(k1)
    os.chmod(p, 0o644)
    with pytest.raises(signing.DeviceKeyError):
        signing.device_key()
    os.chmod(p, 0o600)
    p.write_text("not a key\n")
    with pytest.raises(signing.DeviceKeyError):
        signing.device_key()


def test_no_key_yet():
    with pytest.raises(signing.DeviceKeyError):
        signing.device_key(create=False)


def test_signed_recording_verifies(signed):
    out, meta = signed
    assert meta["signed"]["chunks"] >= 2
    m = json.loads((out / "manifest.json").read_text())
    assert m["asset"]["asset_id"] == "CRANE-07" and m["algorithm"] == "Ed25519"
    assert {"can.csv", "signals.csv", "faults.csv", "meta.json", "chain.jsonl"} <= set(m["files"])
    assert "not a secure element" in m["key_storage"]
    r = signing.verify(out)
    assert r["status"] == "intact" and r["problems"] == [] and r["signed_by_this_device"]
    assert r["chunks"] == m["chain"]["chunks"]
    assert signing.verify(out, expect_key=m["device"])["status"] == "intact"
    entries = [e for e in map(json.loads, Audit().path.read_text().splitlines())
               if e["kind"] == "recording_signed"]
    assert entries and entries[-1]["chain_head"] == m["chain"]["head"]


def _flip(path, at):
    b = bytearray(path.read_bytes())
    b[at] = ord("0") if b[at] != ord("0") else ord("1")
    path.write_bytes(bytes(b))


def test_changed_byte_names_the_file_and_chunk(signed):
    out, _ = signed
    chain = [json.loads(x) for x in (out / "chain.jsonl").read_text().splitlines()]
    target = [e for e in chain if e["file"] == "can.csv"][-1]
    _flip(out / "can.csv", target["offset"] + target["length"] // 2)
    r = signing.verify(out)
    assert r["status"] == "tampered"
    assert any(p.startswith("can.csv: changed") for p in r["problems"])
    assert any(p.startswith(f"can.csv chunk {target['seq']} ") and "contents changed" in p
               for p in r["problems"])
    assert "tampered" in signing.render(r)


def test_appended_deleted_and_extra_files(signed):
    out, _ = signed
    with (out / "signals.csv").open("a") as f:
        f.write("1,2,3\n")
    (out / "faults.csv").unlink()
    (out / "notes.txt").write_text("hi")
    r = signing.verify(out)
    assert any("signals.csv" in p and "after the last signed chunk" in p for p in r["problems"])
    assert "faults.csv: missing" in r["problems"]
    assert any(n.startswith("notes.txt") for n in r["notes"])


def test_edited_manifest_or_signature_or_chain(signed, tmp_path):
    import shutil
    out, _ = signed
    for case in ("manifest", "sig", "chain", "wrongkey", "unsigned"):
        d = tmp_path / case
        shutil.copytree(out, d)
        if case == "manifest":
            m = json.loads((d / "manifest.json").read_text())
            m["asset"]["asset_id"] = "SOMETHING-ELSE"
            (d / "manifest.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
        elif case == "sig":
            (d / "manifest.sig").write_text("AAAA" + (d / "manifest.sig").read_text()[4:])
        elif case == "chain":
            lines = (d / "chain.jsonl").read_text().splitlines()
            e = json.loads(lines[0])
            e["t_unix"] += 60
            lines[0] = json.dumps(e, sort_keys=True)
            (d / "chain.jsonl").write_text("\n".join(lines) + "\n")
        elif case == "wrongkey":
            r = signing.verify(d, expect_key="00" * 32)
            assert r["status"] == "tampered" and "not the expected key" in r["problems"][0]
            continue
        else:
            (d / "manifest.sig").unlink()
            assert signing.verify(d)["status"] == "unsigned"
            continue
        r = signing.verify(d)
        assert r["status"] == "tampered", case
        if case in ("manifest", "sig"):
            assert "signature does not match" in r["problems"][0]
        else:
            assert any("chain.jsonl: entry 1 broken" in p for p in r["problems"])
            assert any(p.startswith("chain.jsonl: changed") for p in r["problems"])


def test_missing_library_gives_a_clear_error(monkeypatch, sim, tmp_path):
    def gone():
        raise signing.SigningUnavailable(signing.INSTALL_HINT)
    monkeypatch.setattr(signing, "_ed25519", gone)
    assert not signing.available()
    with pytest.raises(RecordError, match=r"car-use\[sign\]"):
        Recorder(sim("open-bus"), out_dir=tmp_path / "x", can=True, sign=True)
    assert main(["verify", str(tmp_path)]) == 2
    assert main(["record", "--sim", "open-bus", "--can", "--sign", "--seconds", "0.3"]) == 2


def test_cli_sign_verify_key(tmp_path, capsys):
    assert main(["key"]) == 1                              # no key yet
    capsys.readouterr()
    out = tmp_path / "r"
    assert main(["record", "--sim", "open-bus", "--can", "--seconds", "1", "--sign",
                 "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["signed"]["chunks"] >= 1
    assert main(["verify", str(out)]) == 0
    assert capsys.readouterr().out.startswith("intact")
    assert main(["key"]) == 0
    assert "software key" in capsys.readouterr().out
    _flip(out / "can.csv", 60)
    assert main(["verify", str(out), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "tampered"


def test_malformed_chain_entries_are_reported_not_crashed(signed):
    from car_use import signing
    folder = signed[0] if isinstance(signed, tuple) else signed
    folder = Path(folder)
    chain = folder / signing.CHAIN_FILE
    lines = chain.read_text().splitlines()
    lines[0] = json.dumps({"seq": 0, "file": "/etc/passwd"})
    lines.insert(1, "[1, 2, 3]")
    chain.write_text("\n".join(lines) + "\n")
    result = signing.verify(folder)
    assert result["status"] == "tampered"
    assert any("unreadable" in p for p in result["problems"])


def test_decoding_a_signed_folder_is_refused(signed):
    from car_use.record import decode_folder, RecordError
    folder = Path(signed[0] if isinstance(signed, tuple) else signed)
    with pytest.raises(RecordError, match="signed"):
        decode_folder(folder, "j1939")
