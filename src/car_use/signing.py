"""Signed recordings: `car-use record --sign` and `car-use verify FOLDER`.

Each install of car-use has its own Ed25519 key (the "device key"), kept in
~/.car-use/keys/ with 0600 permissions. While a signed recording runs, every
second or so the bytes newly appended to each CSV are hashed into a chunk,
and each chunk's entry includes the hash of the one before it (chain.jsonl).
At the end, manifest.json lists every file's SHA-256, the chain head, the
start and end time, the VIN or asset id, and the device's public key, and
manifest.sig holds the Ed25519 signature over manifest.json.

`verify` checks the signature, every file hash and every chunk, and says
which file or chunk changed. It shows that the files are the ones this key
signed, unchanged since. It cannot show the data was true when captured.

This is a software key: anything that can read ~/.car-use/keys can sign as
this device. Keeping the key in a secure element on a car-use dongle is
future work.

Needs the `cryptography` package: pip install 'car-use[sign]'.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, paths

KEY_FILE = "device_ed25519.key"
CHAIN_FILE = "chain.jsonl"
MANIFEST_FILE = "manifest.json"
SIG_FILE = "manifest.sig"
GENESIS = "0" * 64
INSTALL_HINT = ("Signing needs the 'cryptography' package. Install it with: "
                "pip install 'car-use[sign]'  (or: uv tool install 'car-use[sign]')")


class SigningUnavailable(RuntimeError):
    pass


class DeviceKeyError(RuntimeError):
    pass


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise SigningUnavailable(INSTALL_HINT) from None
    return ed25519, InvalidSignature


def available() -> bool:
    try:
        _ed25519()
        return True
    except SigningUnavailable:
        return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# -- the device key --------------------------------------------------------------------

def key_path() -> Path:
    return paths.home() / "keys" / KEY_FILE


def device_key(create: bool = True):
    """This install's Ed25519 private key, created on first use (0600, in a 0700 folder)."""
    ed25519, _ = _ed25519()
    p = key_path()
    if not p.exists():
        if not create:
            raise DeviceKeyError(f"No device key yet at {p}. car-use record --sign makes one.")
        p.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        seed = ed25519.Ed25519PrivateKey.generate().private_bytes_raw()
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(seed.hex() + "\n")
    mode = stat.S_IMODE(p.stat().st_mode)
    # Windows reports every file as 0o666 (no POSIX modes), so the check cannot
    # pass there; the user profile's ACL is what protects the key.
    if os.name != "nt" and mode & 0o077:
        raise DeviceKeyError(f"{p} is readable by other users (mode {mode:o}). Anyone who can read "
                        f"it can sign as this device. Fix it with: chmod 600 {p}")
    try:
        seed = bytes.fromhex(p.read_text().strip())
        return ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    except ValueError:
        raise DeviceKeyError(f"{p} is not a car-use device key.") from None


def public_hex(private_key) -> str:
    return private_key.public_key().public_bytes_raw().hex()


def fingerprint(public_key_hex: str) -> str:
    """Short, readable id for a public key: the first 16 hex digits of its SHA-256."""
    return _sha256(bytes.fromhex(public_key_hex))[:16]


# -- chunk chain while recording --------------------------------------------------------

def _plain_name(name) -> bool:
    """A bare file name in the recording folder: no directories, no absolute path."""
    return isinstance(name, str) and bool(name) and name not in (".", "..") and \
        "/" not in name and "\\" not in name and Path(name).name == name


def chunk_hash(prev: str, entry: dict) -> str:
    body = {k: entry[k] for k in ("seq", "file", "offset", "length", "sha256", "t_unix",
                                  "t_since_start")}
    return _sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode())


class Signer:
    """Hash-chains what a recording appends to its files, then signs a manifest."""

    def __init__(self, folder: Path, files: list[str], asset: dict | None = None):
        self.key = device_key()            # fails early, before anything is recorded
        self.folder = Path(folder)
        self.files = list(files)
        self.asset = asset or {}
        self.offsets = {f: 0 for f in self.files}
        self.head = GENESIS
        self.seq = 0
        self.t0 = time.monotonic()
        self.started = time.time()
        self._last = 0.0
        self._chain = (self.folder / CHAIN_FILE).open("w", encoding="utf-8")

    def checkpoint(self, force: bool = False, every: float = 1.0) -> None:
        """Chain whatever was appended since the last chunk (at most once per `every` s)."""
        now = time.monotonic()
        if not force and now - self._last < every:
            return
        self._last = now
        for name in self.files:
            p = self.folder / name
            if not p.exists():
                continue
            size = p.stat().st_size
            start = self.offsets[name]
            if size <= start:
                continue
            with p.open("rb") as f:
                f.seek(start)
                data = f.read(size - start)
            self.seq += 1
            entry = {"seq": self.seq, "file": name, "offset": start, "length": len(data),
                     "sha256": _sha256(data), "t_unix": round(time.time(), 3),
                     "t_since_start": round(now - self.t0, 3), "prev": self.head}
            entry["hash"] = chunk_hash(self.head, entry)
            self.head = entry["hash"]
            self.offsets[name] = size
            self._chain.write(json.dumps(entry, sort_keys=True) + "\n")
        self._chain.flush()

    def finish(self, extra_files: list[str] = ()) -> dict:
        """Last chunk, then manifest.json and manifest.sig. Returns the manifest."""
        self.checkpoint(force=True)
        self._chain.close()
        names = sorted({*self.files, *extra_files, CHAIN_FILE})
        files = {n: {"sha256": _file_sha256(self.folder / n),
                     "bytes": (self.folder / n).stat().st_size}
                 for n in names if (self.folder / n).exists()}
        pub = public_hex(self.key)
        manifest = {
            "schema": 1,
            "source": "car-use record --sign",
            "car_use_version": __version__,
            "algorithm": "Ed25519",
            "public_key": pub,
            "device": fingerprint(pub),
            "key_storage": "software (file on this computer); not a secure element",
            "started_utc": datetime.fromtimestamp(self.started, timezone.utc).isoformat(),
            "ended_utc": datetime.now(timezone.utc).isoformat(),
            "asset": self.asset,
            "files": files,
            "chain": {"file": CHAIN_FILE, "chunks": self.seq, "head": self.head,
                      "chunked_files": self.files},
        }
        body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        (self.folder / MANIFEST_FILE).write_bytes(body)
        sig = self.key.sign(body)
        (self.folder / SIG_FILE).write_text(base64.b64encode(sig).decode() + "\n")
        return manifest


# -- verify -------------------------------------------------------------------------------

def verify(folder: Path | str, expect_key: str | None = None) -> dict:
    """Check a signed recording. Returns {"status": "intact"|"tampered"|"unsigned",
    "problems": [...], ...}, naming the file or chunk for every problem."""
    ed25519, InvalidSignature = _ed25519()
    folder = Path(folder)
    out: dict = {"folder": str(folder), "problems": [], "notes": []}
    problems, notes = out["problems"], out["notes"]
    mp, sp = folder / MANIFEST_FILE, folder / SIG_FILE
    if not mp.exists() or not sp.exists():
        out["status"] = "unsigned"
        problems.append(f"no {MANIFEST_FILE} / {SIG_FILE}: this recording was not signed "
                        "(record with --sign), or they were deleted")
        return out
    body = mp.read_bytes()
    try:
        manifest = json.loads(body)
        pub = bytes.fromhex(manifest["public_key"])
        key = ed25519.Ed25519PublicKey.from_public_bytes(pub)
        key.verify(base64.b64decode(sp.read_text().strip()), body)
    except InvalidSignature:
        out["status"] = "tampered"
        problems.append(f"{MANIFEST_FILE}: the signature does not match; the manifest or "
                        f"{SIG_FILE} was changed after signing")
        return out
    except (ValueError, KeyError, TypeError) as e:
        out["status"] = "tampered"
        problems.append(f"{MANIFEST_FILE} or {SIG_FILE} is unreadable: {e}")
        return out
    out.update(device=manifest.get("device"), public_key=manifest["public_key"],
               started_utc=manifest.get("started_utc"), ended_utc=manifest.get("ended_utc"),
               asset=manifest.get("asset"))
    if expect_key and expect_key.lower() not in (manifest["public_key"], manifest.get("device")):
        problems.append(f"signed by device {manifest.get('device')}, not the expected key "
                        f"{expect_key}")
    try:
        mine = public_hex(device_key(create=False))
        out["signed_by_this_device"] = mine == manifest["public_key"]
    except (DeviceKeyError, SigningUnavailable):
        out["signed_by_this_device"] = None
    # every file
    for name, want in sorted(manifest.get("files", {}).items()):
        if not _plain_name(name):
            problems.append(f"manifest names {name!r}, which is not a file in this folder")
            continue
        p = folder / name
        if not p.exists():
            problems.append(f"{name}: missing")
        elif _file_sha256(p) != want["sha256"]:
            size = p.stat().st_size
            problems.append(f"{name}: changed (SHA-256 differs; {size} bytes now, "
                            f"{want['bytes']} when signed)")
    signed = set(manifest.get("files", {})) | {MANIFEST_FILE, SIG_FILE}
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name not in signed:
            notes.append(f"{p.name}: not covered by the signature (added after signing?)")
    # every chunk
    chain = manifest.get("chain") or {}
    cp = folder / CHAIN_FILE
    prev, n = GENESIS, 0
    ends: dict[str, int] = {}
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                problems.append(f"{CHAIN_FILE}: line {n + 1} is not valid JSON")
                break
            n += 1
            try:
                if not isinstance(e, dict) or not _plain_name(e["file"]):
                    raise ValueError
                offset, length = int(e["offset"]), int(e["length"])
                if offset < 0 or length < 0:
                    raise ValueError
                where = (f"{e['file']} chunk {e.get('seq')} (bytes {offset}-{offset + length}, "
                         f"t_since_start {e.get('t_since_start')} s)")
                if e.get("prev") != prev or chunk_hash(prev, e) != e.get("hash"):
                    problems.append(f"{CHAIN_FILE}: entry {n} broken ({where})")
            except (KeyError, TypeError, ValueError, AttributeError):
                problems.append(f"{CHAIN_FILE}: entry {n} unreadable")
                prev = ""
                continue
            prev = e.get("hash", "")
            p = folder / e["file"]
            if p.exists():
                with p.open("rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                if len(data) != length or _sha256(data) != e.get("sha256"):
                    problems.append(f"{where}: contents changed")
            ends[e["file"]] = offset + length
    if n != chain.get("chunks") or prev != chain.get("head"):
        problems.append(f"{CHAIN_FILE}: {n} chunks ending in {prev[:12]}, but the manifest "
                        f"signed {chain.get('chunks')} ending in {str(chain.get('head'))[:12]}")
    for name in chain.get("chunked_files", []):
        p = folder / name
        if p.exists() and p.stat().st_size > ends.get(name, 0):
            problems.append(f"{name}: {p.stat().st_size - ends.get(name, 0)} bytes after the "
                            "last signed chunk (appended after signing)")
    out["chunks"] = n
    out["status"] = "tampered" if problems else "intact"
    return out


def render(result: dict) -> str:
    lines = [f"{result['status']}: {result['folder']}"]
    if result.get("device"):
        who = {True: " (this computer's key)", False: " (another device's key)"}.get(
            result.get("signed_by_this_device"), "")
        lines.append(f"  signed by device {result['device']}{who}, Ed25519 software key")
        lines.append(f"  {result.get('started_utc')} to {result.get('ended_utc')}, "
                     f"{result.get('chunks', 0)} chunks")
        asset = {k: v for k, v in (result.get("asset") or {}).items() if v}
        if asset:
            lines.append("  asset: " + ", ".join(f"{k} {v}" for k, v in asset.items()))
    for p in result["problems"]:
        lines.append(f"  - {p}")
    for n in result.get("notes", []):
        lines.append(f"  note: {n}")
    return "\n".join(lines) + "\n"
