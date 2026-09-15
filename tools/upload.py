# SPDX-License-Identifier: Apache-2.0
"""Upload a calibration bitstream to a Tiny Tapeout FPGA emulation board and
enable it, through the fpgas.online Pi daemon.

    uv run --no-project python tools/upload.py http://127.0.0.1:18733 \
        bitstreams/tt_um_vgacal_bars.bin --enable

The daemon (`fpgas-online-tt`) accepts a multipart POST on /bitstream with
`name` and `file`, rejects anything over 256 KiB, anything without the iCE40
preamble in its first 64 bytes, and names outside `[a-z0-9_]{1,40}`. It keeps
at most 16 uploads, evicting the oldest. `POST /designs/<name>/enable` then
loads the bitstream into the iCE40 and, with `clock_hz`, sets the project
clock.

Reach a Welland board by tunnelling its daemon first, for example
`ssh -N -L 18733:10.21.2.33:8765 tweed.welland.mithis.com`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.request
import uuid

ICE40_PREAMBLE = bytes((0x7E, 0xAA, 0x99, 0x7E))


def multipart(fields: dict[str, str], name: str, filename: str, payload: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body; the daemon wants `name` and `file`."""
    boundary = uuid.uuid4().hex
    out = bytearray()
    for key, value in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
    out += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode()
    out += payload + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def post(url: str, body: bytes, content_type: str, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{url}: HTTP {e.code}: {e.read().decode()[:400]}") from None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("daemon", help="base URL of the Pi daemon, e.g. http://127.0.0.1:18733")
    ap.add_argument("bitstream", type=pathlib.Path)
    ap.add_argument("--name", help="design name on the board (default: the file stem)")
    ap.add_argument("--enable", action="store_true", help="enable the design after uploading")
    ap.add_argument("--clock-hz", type=int, help="project clock to set when enabling")
    a = ap.parse_args()

    payload = a.bitstream.read_bytes()
    if ICE40_PREAMBLE not in payload[:64]:
        raise SystemExit(f"{a.bitstream}: no iCE40 preamble in the first 64 bytes")
    if len(payload) > 256 * 1024:
        raise SystemExit(f"{a.bitstream}: {len(payload)} bytes, over the daemon's 256 KiB limit")
    name = a.name or a.bitstream.stem

    body, content_type = multipart({"name": name}, "file", a.bitstream.name, payload)
    print(f"uploading {a.bitstream} ({len(payload)} bytes) as {name!r}")
    print("upload:", post(f"{a.daemon}/bitstream", body, content_type))

    if a.enable:
        enable_body = json.dumps({"clock_hz": a.clock_hz} if a.clock_hz else {}).encode()
        print("enable:", post(f"{a.daemon}/designs/{name}/enable", enable_body, "application/json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
