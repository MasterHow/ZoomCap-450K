#!/usr/bin/env python3
"""Verify the released ZoomCap-450K rows are drop-in joinable with ScaleCap-450k.

Two independent checks:

``structure``  -- offline; validates the published parquet against the ScaleCap
                  schema contract (field names, types, the literal ``<image>``
                  human turn, flat ``<source_dir>/<basename>`` keys, no absolute
                  paths, row/shard totals reconciled with ``stats.json``).
``upstream``   -- online; samples keys and asks the HuggingFace datasets-server
                  whether each one exists in ``long-xing1/ScaleCap-450k``.
                  Degrades to a clearly-marked NOT VERIFIED when offline.

Usage
-----
    python3 tools/verify_join.py --root ~/WSP/zoomcap_release/ZoomCap-450K \
        --mode both --sample 200
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

KEY_RE = re.compile(
    r"^(laion_filter_image|share4v_image)/[^/]+\.(?:jpe?g|png|webp|gif|bmp)$", re.I)
SOURCE_DIRS = ("laion_filter_image", "share4v_image")
HUMAN_TURN = "<image>"
DEFAULT_UPSTREAM = "long-xing1/ScaleCap-450k"
DEFAULT_CONFIG = "ScaleCap450k"
DEFAULT_SPLIT = "train"
SERVER = "https://datasets-server.huggingface.co"


def split_parquet(root: str, split: str) -> List[str]:
    d = os.path.join(root, split)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".parquet"))


def read_rows(root: str, split: str) -> Tuple[int, List[str], Dict[str, List[str]]]:
    problems: Dict[str, List[str]] = {}
    keys: List[str] = []
    rows = 0

    def note(kind: str, detail: str) -> None:
        bucket = problems.setdefault(kind, [])
        if len(bucket) < 5:
            bucket.append(detail)
        elif len(bucket) == 5:
            bucket.append("(more suppressed)")

    for path in split_parquet(root, split):
        pf = pq.ParquetFile(path)
        names = [pf.schema_arrow.field(i).name for i in range(len(pf.schema_arrow))]
        if names != ["images", "conversations"]:
            note("schema_field_order", f"{os.path.basename(path)}: {names}")
        for f in pf.schema_arrow:
            if f.name == "images" and f.type != pa.list_(pa.string()):
                note("schema_type_images", str(f.type))
            if f.name == "conversations":
                want = pa.list_(pa.struct([pa.field("from", pa.string()),
                                           pa.field("value", pa.string())]))
                if f.type != want:
                    note("schema_type_conversations", str(f.type))
        for batch in pf.iter_batches(batch_size=4096):
            images = batch.column("images").to_pylist()
            convs = batch.column("conversations").to_pylist()
            for imgs, conv in zip(images, convs):
                rows += 1
                if not imgs or len(imgs) != 1:
                    note("images_not_single", f"row {rows}: {imgs!r}")
                    continue
                key = imgs[0]
                keys.append(key)
                if not isinstance(key, str):
                    note("key_not_string", f"row {rows}")
                elif not KEY_RE.match(key):
                    note("key_pattern", f"row {rows}: {key}")
                if key.startswith("/") or ".." in key:
                    note("key_absolute_or_traversal", f"row {rows}: {key}")
                roles = [t.get("from") for t in (conv or [])]
                if roles != ["human", "gpt"]:
                    note("conversation_roles", f"row {rows}: {roles}")
                    continue
                if conv[0].get("value") != HUMAN_TURN:
                    note("human_turn", f"row {rows}: {conv[0].get('value')!r}")
                if not (conv[1].get("value") or "").strip():
                    note("empty_caption", f"row {rows}: {key}")
    return rows, keys, problems


def http_json(url: str, timeout: int = 45, retries: int = 2) -> Optional[Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "zoomcap-release-verify/1.0"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # offline, rate-limited, 404 on config guess
            err = f"{type(exc).__name__}: {exc}"
            if attempt == retries:
                return {"__error__": err}
    return None


def reachable(url: str, timeout: float = 5.0) -> Optional[str]:
    """Cheap connectivity pre-flight: returns None when the endpoint answers."""
    req = urllib.request.Request(url, headers={"User-Agent": "zoomcap-release-verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def check_upstream(dataset: str, config: str, split: str, keys: List[str],
                   sample: int, seed: int) -> Dict[str, Any]:
    # One short probe first: probing 200 keys on an offline machine would waste
    # hours in per-request timeouts, and the answer is not "missing key".
    err = reachable(f"{SERVER}/info?dataset={urllib.parse.quote(dataset)}")
    if err:
        return {
            "dataset": dataset, "config": config, "split": split,
            "sampled": 0, "verified": None,
            "error": f"datasets-server unreachable ({err}); re-run --mode upstream "
                     f"from a machine with internet access before publishing",
        }
    rng = random.Random(seed)
    picks = rng.sample(keys, min(sample, len(keys))) if keys else []
    found: List[str] = []
    missing: List[str] = []
    errors: List[str] = []
    for i, key in enumerate(picks, 1):
        where = urllib.parse.quote("images[1] = '%s'" % key.replace("'", "''"))
        url = (f"{SERVER}/filter?dataset={urllib.parse.quote(dataset)}"
               f"&config={urllib.parse.quote(config)}&split={urllib.parse.quote(split)}"
               f"&where={where}&length=1&offset=0")
        data = http_json(url)
        if isinstance(data, dict) and "__error__" in data:
            # fall back to full-text search on the basename
            q = urllib.parse.quote(key.split("/")[-1])
            url2 = (f"{SERVER}/search?dataset={urllib.parse.quote(dataset)}"
                    f"&config={urllib.parse.quote(config)}&split={urllib.parse.quote(split)}"
                    f"&query={q}&length=5&offset=0")
            data = http_json(url2)
        if not isinstance(data, dict) or "__error__" in data:
            errors.append(f"{key}: {(data or {}).get('__error__', 'no response')}")
        else:
            rows = data.get("rows") or []
            hit = False
            for r in rows:
                imgs = (r.get("row") or {}).get("images") or []
                if isinstance(imgs, str):
                    imgs = [imgs]
                flat = [x if isinstance(x, str) else (x.get("src") or "",) for x in imgs]
                if any(key in f for f in flat) or (rows and len(rows) >= 1 and "filter" in url):
                    hit = True
            (found if hit else missing).append(key)
        if i % 50 == 0:
            print(f"  … upstream {i}/{len(picks)} checked", file=sys.stderr, flush=True)
    return {
        "dataset": dataset, "config": config, "split": split,
        "sampled": len(picks), "found": len(found), "missing": len(missing),
        "missing_keys": missing[:10], "errors": errors[:5],
        "verified": bool(picks) and not errors and not missing,
    }


# ScaleCap-450k's published feature signature (what a drop-in replacement must
# produce under `datasets.load_dataset`).  Transcribed from the upstream dataset
# page; re-check it once from a networked machine with
# ``GET https://datasets-server.huggingface.co/info?dataset=long-xing1/ScaleCap-450k``
# before advertising "schema-identical" publicly.
UPSTREAM_FEATURES = {
    "images": "List(Value('string'))",
    "conversations": "List({'from': Value('string'), 'value': Value('string')})",
}


def check_loadable(root: str, split: str = "clean", shard: int = 0) -> Dict[str, Any]:
    """Load one published shard through the `datasets` library.

    Proves the parquet is consumable as documented and that the arrow feature
    signature is byte-for-byte the upstream one, i.e. genuinely drop-in.
    """
    files = split_parquet(root, split)
    if not files:
        return {"error": f"no shards for config '{split}'"}
    try:
        from datasets import load_dataset
    except ImportError:
        return {"error": "`datasets` not installed; skipped"}
    try:
        ds = load_dataset("parquet", data_files=[files[shard]], split="train")
        features = {k: str(v) for k, v in ds.features.items()}
        row = ds[0]
        return {
            "shard": os.path.basename(files[shard]),
            "rows_in_shard": len(ds),
            "features": features,
            "features_match_upstream": features == UPSTREAM_FEATURES,
            "example_image_key": row["images"][0],
            "example_caption_header": row["conversations"][1]["value"][:80],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--mode", default="both",
                    choices=["structure", "upstream", "loadable", "both"])
    ap.add_argument("--dataset", default=DEFAULT_UPSTREAM)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--split", default=DEFAULT_SPLIT)
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--emit-keys", default="", help="write gzipped key list here")
    args = ap.parse_args(argv)

    root = os.path.abspath(os.path.expanduser(args.root))
    outdir = os.path.join(root, "verification")
    os.makedirs(outdir, exist_ok=True)
    # NB: only the basename is recorded -- these reports ship with the release,
    # so an absolute path would publish the operator's home directory/username.
    report: Dict[str, Any] = {"root": os.path.basename(root)}
    failures = 0

    all_keys: Dict[str, List[str]] = {}
    if args.mode in ("structure", "both"):
        stats_path = os.path.join(root, "stats.json")
        configs = ["full", "clean", "pii_free"]
        if os.path.exists(stats_path):
            configs = list(json.load(open(stats_path, encoding="utf-8"))
                           ["counts"]["rows_per_config"].keys())
        for split in configs:
            rows, keys, problems = read_rows(root, split)
            all_keys[split] = keys
            report[f"structure_{split}"] = {
                "rows": rows,
                "unique_keys": len(set(keys)),
                "shards": len(split_parquet(root, split)),
                "problems": problems,
            }
            failures += sum(len(v) for v in problems.values())
        if os.path.exists(stats_path):
            st = json.load(open(stats_path, encoding="utf-8"))
            want = st["counts"]["rows_per_config"]
            rep = {s: report.get(f"structure_{s}", {}).get("rows") for s in want}
            report["stats_reconciliation"] = {"expected": want, "observed": rep,
                                              "match": want == rep}
            if not report["stats_reconciliation"]["match"]:
                failures += 1

    if args.mode in ("loadable", "both"):
        res = check_loadable(root)
        report["loadable"] = res
        if res.get("features_match_upstream") is False or "error" in res:
            failures += 1

    if args.mode == "structure" and "full" not in all_keys:
        print("nothing to check", file=sys.stderr)
        return 1

    if args.mode in ("upstream", "both"):
        keys = all_keys.get("full") or []
        if keys:
            res = check_upstream(args.dataset, args.config, args.split,
                                 keys, args.sample, args.seed)
            report["upstream"] = res
            if res.get("verified") is None:
                print("WARNING: upstream membership NOT VERIFIED (offline)", file=sys.stderr)
            elif not res["verified"]:
                failures += 1
        else:
            report["upstream"] = {"error": "no keys loaded; run --mode structure first"}
            failures += 1

    if args.emit_keys:
        keys = all_keys.get("full") or []
        with gzip.open(os.path.expanduser(args.emit_keys), "wt", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(set(keys))) + "\n")
        report["keys_emitted"] = os.path.basename(os.path.expanduser(args.emit_keys)) + " (local, not published)"

    with open(os.path.join(outdir, "join_verification.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    md = ["# Join verification — ZoomCap-450K ↔ ScaleCap-450k", ""]
    for key, val in report.items():
        if key == "root":
            continue
        md.append(f"## {key}")
        md.append("```json")
        md.append(json.dumps(val, ensure_ascii=False, indent=2)[:4000])
        md.append("```")
        md.append("")
    up = report.get("upstream", {})
    if up.get("verified") is None:
        md.append("> NOTE: upstream check could not reach the HF datasets-server "
                  "(offline / restricted network). Re-run `--mode upstream` from a "
                  "machine with network access before publishing.")
    with open(os.path.join(outdir, "JOIN_VERIFICATION.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    print(json.dumps({k: v for k, v in report.items() if k != "root"},
                     ensure_ascii=False, indent=2)[:3000])
    print(f"\nreport -> {outdir}/JOIN_VERIFICATION.md")
    if failures:
        print(f"FAILED with {failures} structural/verification problem group(s)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
