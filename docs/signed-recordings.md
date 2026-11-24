# Signed recordings

`car-use record --sign` makes a recording that can be checked later. Anyone holding the folder can run `car-use verify` and find out whether any file changed after it was recorded, and if one did, exactly which file and which part of it.

```bash
pip install 'car-use[sign]'          # or: uv tool install 'car-use[sign]'
car-use record --j1939 --decode j1939 --sign --asset CRANE-07 --minutes 60
car-use verify ~/.car-use/recordings/20261123T101500Z
car-use key                          # this computer's public key, to share with whoever verifies
```

Try it on the virtual crane: `car-use record --sim crane-j1939 --decode j1939 --sign --seconds 10`.

## What it proves, and what it doesn't

It proves that the files in the folder are the ones the key signed, and that they haven't changed since. Every chunk was hashed within about a second of being written, so editing a file afterwards breaks the chain.

It does not prove the data was true. A tampered adapter, a wrong clock or a machine sending bad values would all be signed faithfully. It also only proves which **key** signed, not which person or machine.

**This is a software key.** It is a file on this computer (`~/.car-use/keys/device_ed25519.key`, permissions 0600). Anything that can read that file can sign as this device: another program running as you, a backup, a stolen laptop. car-use refuses to use the key if other users can read it, but that is the extent of the protection. Keeping the key in a secure element on a car-use device, where it can't be copied out, is future work. Until then, treat a signature as "this recording came from this install of car-use and hasn't been edited since", not as evidence that would stand up against a determined forger.

## What's in the folder

| file | what it is |
| --- | --- |
| `can.csv`, `obd.csv`, `signals.csv`, `faults.csv` | the recording, as usual ([recording.md](recording.md)) |
| `meta.json` | as usual, plus a `signed` section |
| `chain.jsonl` | one line per chunk: which file, byte offset and length, the chunk's SHA-256, the time, the previous chunk's hash, and this entry's hash |
| `manifest.json` | the SHA-256 and size of every file, the chain head and number of chunks, start and end time (UTC), the VIN or asset id if known, the device's Ed25519 public key and its short fingerprint |
| `manifest.sig` | the Ed25519 signature of `manifest.json`, base64 |

How it works:

1. Each install gets its own Ed25519 key the first time it signs.
2. During the recording, about once a second, the bytes newly appended to each CSV become a chunk. A chunk's hash covers its file name, offset, length, the SHA-256 of its bytes, its time, and the previous chunk's hash. Changing, removing or reordering any chunk breaks every hash after it.
3. When the recording ends, the manifest is written and signed. The audit log (`car-use audit`) also records the chain head and the manifest's hash.

`--asset` adds your own id for the machine, such as a fleet or serial number. If car-use read the VIN (not in listen-only mode), the manifest includes the full VIN, unlike `meta.json`. Treat a signed folder as private.

## Verifying

```
$ car-use verify ./rec
intact: ./rec
  signed by device ef5753afd01b5e17 (this computer's key), Ed25519 software key
  2026-11-24T01:13:51+00:00 to 2026-11-24T01:13:54+00:00, 7 chunks
  asset: asset_id CRANE-07
```

After one character in `can.csv` was changed:

```
tampered: ./rec
  ...
  - can.csv: changed (SHA-256 differs; 19636 bytes now, 19636 when signed)
  - can.csv chunk 4 (bytes 7136-14236, t_since_start 2.224 s): contents changed
```

`verify` checks:

- that the signature matches `manifest.json`;
- that every listed file exists and has the hash the manifest says;
- that every chunk in `chain.jsonl` links to the one before and still matches the bytes at its offset;
- that the chain ends where the manifest says;
- that nothing was appended after the last chunk.

Files the manifest doesn't list are reported as notes, not as tampering. The exit code is 0 when intact and 1 when not. `--json` gives the full result.

The public key is inside the manifest, so a valid signature only means "signed by whoever holds this key". To check it was **your** device, compare the fingerprint with `car-use key` on that device, or pass it: `car-use verify ./rec --key ef5753afd01b5e17`.

## Requirements

Ed25519 comes from the [`cryptography`](https://cryptography.io) package, an optional extra so the rest of car-use keeps zero dependencies. Without it, `record --sign` and `verify` stop with an install hint before recording anything.
