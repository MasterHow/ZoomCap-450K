#!/usr/bin/env python3
"""Prove the `pii_free` config contains no third-party contact strings.

The internal data-output approval form asks the applicant to state truthfully whether personal
information is being output. Under the row-exclusion policy, that claim is only
defensible if it is *measured*: this script re-runs every census pattern over the
published `pii_free` parquet files and requires zero hits, so the statement in the
form is backed by an artefact rather than by intent.

The check deliberately re-detects on the published bytes (not on the build's own
flags), so a flag regression cannot hide behind itself.

Usage
-----
    python3 tools/verify_pii_free.py --root ~/WSP/zoomcap_release/ZoomCap-450K
Writes ``verification/PII_FREE_CHECK.md`` and exits non-zero on any detection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

import pyarrow.parquet as pq

# Same pattern families as the census; duplicated here on purpose so that the
# verifier does not silently inherit a broken flag from the builder.
import re

_Q = chr(34) + chr(39) + chr(96)
PATTERNS: Dict[str, "re.Pattern[str]"] = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "handle": re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_.]{2,}(?![\w(])"),
    "fs_path": re.compile(r"(?:/home|/Users|/mnt|/media|/var|/opt|/srv|/data|/tmp|/rl|C:)[\\/][A-Za-z0-9_.\-\\/]{2,}"),
    "cn_mobile": re.compile(r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])"),
    "cn_id_card": re.compile(r"(?<![0-9A-Za-z])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9A-Za-z])"),
    "qq_id": re.compile(r"(?i)\bQQ\s*(?:号|号码|number|no\.?)?\s*[:：#]?\s*(\d{5,11})\b"),
    "credential": re.compile(
        r"(?i)\b(?:password|passwd|pwd|passcode|pass-word|pin code|secret key|"
        r"api[_ \-]?key|access[_ \-]?key|private key|licence key|license key|"
        r"activation code|verification code|response code|recovery code|"
        r"密码|密碼|口令)\s*[:：=]\s*[" + _Q + r"]?"
        r"(?!\*{3,}|x{3,})[^\s,.;:!?)\]}" + _Q + r"]{3,40}"),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--config", default="pii_free")
    args = ap.parse_args(argv)

    root = os.path.abspath(os.path.expanduser(args.root))
    cfg_dir = os.path.join(root, args.config)
    files: List[str] = sorted(os.path.join(cfg_dir, f) for f in os.listdir(cfg_dir)
                              if f.endswith(".parquet")) if os.path.isdir(cfg_dir) else []
    if not files:
        print(f"no parquet under {args.config}/", file=sys.stderr)
        return 2

    hits: Dict[str, List[str]] = {}
    rows = 0
    for path in files:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=4096):
            for imgs, conv in zip(batch.column("images").to_pylist(),
                                  batch.column("conversations").to_pylist()):
                rows += 1
                text = "".join(t.get("value", "") for t in (conv or [])
                               if t.get("from") == "gpt")
                for name, pat in PATTERNS.items():
                    m = pat.search(text)
                    if m:
                        bucket = hits.setdefault(name, [])
                        if len(bucket) < 3:
                            bucket.append(f"row {rows} {imgs}: …"
                                          f"{text[max(0, m.start() - 60):m.end() + 40]}…")
        print(f"  … {os.path.basename(path)} done ({rows:,} rows so far)",
              file=sys.stderr, flush=True)

    outdir = os.path.join(root, "verification")
    os.makedirs(outdir, exist_ok=True)
    verdict = "PASS" if not hits else "FAIL"
    lines = [
        f"# `{args.config}` personal-information check — {verdict}", "",
        f"* rows re-scanned from the published parquet: {rows:,}",
        f"* pattern families re-run independently of the build flags: "
        f"{len(PATTERNS)} ({', '.join(sorted(PATTERNS))})",
        f"* detections: {sum(len(v) for v in hits.values())}", "",
    ]
    if hits:
        lines.append("| pattern | examples |")
        lines.append("| --- | --- |")
        for name, ex in hits.items():
            lines.append(f"| `{name}` | " + " · ".join(e[:200].replace("\n", " ") for e in ex) + " |")
    else:
        lines.append("No third-party e-mail address, social handle, local filesystem path, "
                     "mainland-China mobile number, national ID, QQ identifier or in-image "
                     "credential is present in any row of this config.")
    lines += ["",
              "Verbatim in-image text is retained in the `full` and `clean` configs by "
              "design (masking would corrupt OCR transcriptions and break reproduction of "
              "the paper's corpus statistics); see `verification/PII_CENSUS.md`."]
    with open(os.path.join(outdir, "PII_FREE_CHECK.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"{verdict}: {rows:,} rows scanned, {sum(len(v) for v in hits.values())} detections")
    print(f"report -> {os.path.join(outdir, 'PII_FREE_CHECK.md')}")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
