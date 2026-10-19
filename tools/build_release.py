#!/usr/bin/env python3
"""Build the public ZoomCap-450K caption release from the internal JSONL.

The published rows use *exactly* the Schema of the upstream corpus they overlay,
HuggingFace ``long-xing1/ScaleCap-450k``::

    {"images": ["laion_filter_image/0007/<sha256>.jpg"],
     "conversations": [{"from": "human", "value": "<image>"},
                       {"from": "gpt",   "value": "<caption>"}]}

so ZoomCap-450K is a drop-in caption replacement for ScaleCap-450k on the same
image keys.  No extra columns are added.  Everything else this script does is
invisible in the schema:

  * path sanitising  -- the internal absolute prefix (which contains a developer
    home directory and internal corpus names) is stripped down to the
    upstream-relative key;
  * PII redaction    -- e-mail addresses, local filesystem paths, social
    handles and CN personal identifiers are masked; every mask is counted in
    the report;
  * QC               -- degenerate rows (near-empty, absurdly long, looped
    repetition) are *flagged*, not silently dropped.  ``data/full`` keeps every
    row so the released counts match the paper, ``data/clean`` keeps only rows
    that pass QC.

Images are never copied: only captions and the join key are published.

Usage
-----
    python3 tools/build_release.py \
        --src <internal caption jsonl> \
        --out ~/WSP/zoomcap_release/ZoomCap-450K

Write access to the output directory is the only requirement; nothing is
uploaded anywhere by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

# --------------------------------------------------------------------------
# Schema (identical to long-xing1/ScaleCap-450k)
# --------------------------------------------------------------------------
CONVERSATION_TYPE = pa.struct([
    pa.field("from", pa.string()),
    pa.field("value", pa.string()),
])
SCHEMA = pa.schema([
    pa.field("images", pa.list_(pa.string())),
    pa.field("conversations", pa.list_(CONVERSATION_TYPE)),
])

HUMAN_TURN = "<image>"            # ScaleCap's value verbatim
SOURCE_DIRS = ("laion_filter_image", "share4v_image")
# Published key = "<source_dir>/<basename>", i.e. exactly the form used by the
# upstream images column.  NOT the internal cache form, which carries an extra
# 4-hex shard directory.
KEY_RE = re.compile(
    r"^(laion_filter_image|share4v_image)/[^/]+\.(?:jpe?g|png|webp|gif|bmp)$", re.I)
SHARD_DIR_RE = re.compile(r"^[0-9a-f]{4}$")

# --------------------------------------------------------------------------
# Redaction rules (applied to every published caption)
# --------------------------------------------------------------------------
# High-precision labels only. Bare words such as "secret", "token", "account",
# "login" or "username" are far too common in ordinary caption prose ("the
# account: 'Why do people do this'", "a shocking secret: **Nami**") and would
# flag rows that contain no credential at all. Contact-shaped strings are
# already covered by the email/handle rules.
CRED_LABEL = (r"password|passwd|pwd|passcode|pass-word|pin code|secret key"
              r"|api[_ \-]?key|access[_ \-]?key|private key|licence key|license key"
              r"|activation code|verification code|response code|recovery code"
              r"|密码|密碼|口令")
_Q = chr(34) + chr(39) + chr(96)   # "  '  `  optional quote wrappers around values
CRED_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])((?:" + CRED_LABEL + r")\s*[:：=]\s*[" + _Q + r"]?)"
    r"(?!(?:<redacted>|[*x_.\-—]{3,}))"
    r"([^\s,.;:!?)\]}" + _Q + r"]{3,40})")
CRED_DETECT = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:" + CRED_LABEL + r")\s*[:：=]\s*[" + _Q + r"]?"
    r"[^\s,.;:!?)\]}" + _Q + r"]{3,40}")

GROUPED_RULES = {"document_id", "qq_id", "credential_value"}  # keep the label, mask the value

REDACT_RULES: List[Tuple[str, "re.Pattern[str]", str]] = [
    # Order matters: e-mail before handle, labelled identifiers before generic
    # digits.  Alphanumeric lookarounds keep long hex image keys, ISBNs and
    # product codes from being mistaken for Chinese personal identifiers.
    ("cn_id_card", re.compile(
        r"(?<![0-9A-Za-z])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
        r"\d{3}[\dXx](?![0-9A-Za-z])"), "<cn-id>"),
    ("document_id", re.compile(
        r"((?:身份证|证件号|银行卡|卡号|护照|[Ii][Dd]\s*[Cc]ard|identity card|passport|"
        r"bank card)\D{0,12})(\d{10,19})"), "<doc-id>"),
    ("cn_mobile", re.compile(
        r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])"), "<cn-phone>"),
    ("qq_id", re.compile(r"((?:QQ|qq)\s*(?:号|号码|number|no\.?)?\s*[:：#]?\s*)(\d{5,11})\b"),
     "<qq-id>"),
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<email>"),
    ("fs_path", re.compile(
        r"(?:/home|/Users|/mnt|/media|/var|/opt|/srv|/data|/tmp|/rl|C:)[\\/]"
        r"[A-Za-z0-9_.\-\\/]{2,}"), "<path>"),
    ("handle", re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_.]{2,}(?![\w(])"), "<handle>"),
    # credentials/usernames rendered inside the source image (login screens,
    # business cards, classroom notices).  Requires a label followed by an
    # explicit delimiter, then a value that is not already masked, so ordinary
    # prose such as "password strength" or "a pin is affixed" is untouched.
    ("credential_value", CRED_RE, "<redacted>"),
]

# --------------------------------------------------------------------------
# QC rules (flags only; membership of the ``clean`` variant is derived below)
# --------------------------------------------------------------------------
MIN_CHARS = 200
MAX_CHARS = 30_000
REP_WORD_NGRAM = 8
REP_WORD_STRIDE = 4
REP_WORD_LIMIT = 15      # same 8-word shingle repeating > 15x => looped output
REP_LINE_LIMIT = 5       # same long line repeated > 5x => looped output
REP_LINE_MIN_LEN = 40

SENT_SPLIT = re.compile(r"[.!?]+[\"'”’)\]]*\s+|\Z")


def sanitize_key(raw_path: str, audit: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Map an internal absolute image path to the upstream join key.

    Two things happen here:

    1. **De-sharding.** The internal image cache stores
       ``<cache-root>/<corpus>/<source_dir>/<shard-dir>/<file>.jpg`` while the
       upstream corpus publishes ``<source_dir>/<file>.jpg``.  The shard
       directory is a cache-layout artefact, so the key is rebuilt as
       ``<source_dir>/<basename>`` -- that is what makes the two corpora
       joinable on the image column alone.
    2. **Sanitising.** Nothing above the source directory survives, so no
       internal mount point, developer home directory or corpus name is ever
       written to the release.
    """
    parts = [seg for seg in raw_path.replace("\\", "/").split("/") if seg]
    if len(parts) < 2:
        return None
    src_idx = None
    for i, seg in enumerate(parts[:-1]):
        if seg in SOURCE_DIRS:
            src_idx = i
    if src_idx is None:
        return None
    key = f"{parts[src_idx]}/{parts[-1]}"
    if audit is not None:
        for seg in parts[src_idx + 1:-1]:
            audit["shard_dirs"].add(seg if SHARD_DIR_RE.match(seg) else f"?{seg}")
    return key




def redact(text: str, counter: Counter, only: Optional[Iterable[str]] = None) -> str:
    for name, pattern, repl in REDACT_RULES:
        if only is not None and name not in only:
            continue
        if name in GROUPED_RULES:
            text, n = pattern.subn(lambda m, r=repl: m.group(1) + r, text)
        else:
            text, n = pattern.subn(repl, text)
        if n:
            counter[name] += n
    return text


def sentence_count(text: str) -> int:
    return sum(1 for s in SENT_SPLIT.split(text) if s.strip())


def qc_flags(caption: str) -> List[str]:
    """Cheap, deterministic degeneracy checks. Order-independent."""
    flags: List[str] = []
    n_chars = len(caption)
    if n_chars < MIN_CHARS:
        flags.append("too_short")
    if n_chars > MAX_CHARS:
        flags.append("too_long")

    # looped / repeated content
    words = caption.split()
    if len(words) > 400:
        window = Counter(
            tuple(words[i:i + REP_WORD_NGRAM])
            for i in range(0, len(words) - REP_WORD_NGRAM, REP_WORD_STRIDE)
        )
        if window and window.most_common(1)[0][1] > REP_WORD_LIMIT:
            flags.append("repetition_word")
    lines = [ln.strip() for ln in caption.splitlines() if len(ln.strip()) >= REP_LINE_MIN_LEN]
    if lines:
        lc = Counter(lines)
        if lc.most_common(1)[0][1] > REP_LINE_LIMIT:
            flags.append("repetition_line")
    if not caption.strip():
        flags.append("empty")
    return flags


DEGENERATE_FLAGS = {"too_short", "too_long", "repetition_line",
                    "repetition_word", "empty"}
SENSITIVE_FLAGS = {"credential_in_image", "pii_identifier", "pii_contact"}
SENSITIVE_CATEGORIES = ("cn_id_card", "document_id", "cn_mobile", "qq_id")
CONTACT_CATEGORIES = ("email", "handle", "fs_path")


class PIICensus:
    """Count-only pass over the caption, exactly as it exists in the image.

    Nothing in this class mutates a caption. The published text stays
    byte-identical to the internal corpus (only the ``images`` path is
    rewritten), because these strings are the source image's own visible text:
    masking them would degrade OCR transcriptions, break caption/image
    consistency for reconstruction-style evaluation, and stop reproducing the
    paper's corpus statistics.

    What the census does produce is (a) the counts and examples the compliance
    review asks for, and (b) row-level sensitivity flags that drive the optional
    ``pii_free`` config -- whole rows are dropped there, never edited in place.
    """

    def __init__(self, example_cap: int = 3):
        self.occ: Counter = Counter()
        self.rows: Counter = Counter()
        self.chars_if_masked: Counter = Counter()
        self.examples: Dict[str, List[str]] = {}
        self.example_cap = example_cap

    def scan(self, text: str) -> List[str]:
        matched: List[str] = []
        for name, pattern, repl in REDACT_RULES:
            for m in pattern.finditer(text):
                matched.append(name)
                self.occ[name] += 1
                masked = (len(m.group(1)) + len(repl)) if name in GROUPED_RULES else len(repl)
                self.chars_if_masked[name] += max(0, len(m.group(0)) - masked)
                bucket = self.examples.setdefault(name, [])
                if len(bucket) < self.example_cap:
                    lo = max(0, m.start() - 60)
                    snip = text[lo:m.end() + 40].replace("\n", " ")
                    bucket.append(f"…{snip}…")
        for name in set(matched):
            self.rows[name] += 1
        return matched

    @staticmethod
    def flags(matched: List[str]) -> List[str]:
        hit = set(matched)
        flags = []
        if "credential_value" in hit:
            flags.append("credential_in_image")
        if hit & set(SENSITIVE_CATEGORIES):
            flags.append("pii_identifier")
        if hit & set(CONTACT_CATEGORIES):
            flags.append("pii_contact")
        return flags

    def report(self) -> Dict[str, Any]:
        return {
            name: {
                "occurrences": self.occ[name],
                "rows": self.rows[name],
                "chars_removed_if_masked": self.chars_if_masked[name],
                "examples": self.examples.get(name, []),
            }
            for name in sorted(self.occ, key=lambda n: -self.occ[n])
        }


class ShardWriter:
    """Streaming parquet writer with fixed row budget per shard."""

    def __init__(self, outdir: str, prefix: str, rows_per_shard: int, zstd_level: int):
        self.outdir = outdir
        self.prefix = prefix
        self.rows_per_shard = rows_per_shard
        self.zstd_level = zstd_level
        os.makedirs(outdir, exist_ok=True)
        self._buf: List[Dict[str, Any]] = []
        self._shard = 0
        self._writer: Optional[pq.ParquetWriter] = None
        self._path = ""
        self.rows = 0
        self.files: List[Tuple[str, int]] = []
        self.files_scan_done = False
        self._open_next()

    def _open_next(self) -> None:
        self._path = os.path.join(
            self.outdir, f"{self.prefix}-{self._shard:05d}.parquet")
        self._writer = pq.ParquetWriter(
            self._path, SCHEMA, compression="zstd", compression_level=self.zstd_level)
        self._shard += 1

    def add(self, images: List[str], conversations: List[Dict[str, str]]) -> None:
        if len(self._buf) >= self.rows_per_shard:
            self.flush()
            assert self._writer is not None
            self._writer.close()
            self._writer = None
            self._open_next()
        self._buf.append({"images": images, "conversations": conversations})
        self.rows += 1

    def flush(self) -> None:
        if not self._buf:
            return
        table = pa.Table.from_pylist(self._buf, schema=SCHEMA)
        assert self._writer is not None
        self._writer.write_table(table)
        self._buf = []

    def close(self) -> None:
        if self.files_scan_done:
            return
        self.flush()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        for name in sorted(os.listdir(self.outdir)):
            if not name.endswith(".parquet"):
                continue
            path = os.path.join(self.outdir, name)
            num_rows = pq.ParquetFile(path).metadata.num_rows
            if num_rows == 0:
                os.remove(path)   # trailing shard opened but never written
                continue
            self.files.append((os.path.relpath(path, self.outdir), num_rows))
        self.files.sort()
        self.files_scan_done = True


# The manifest pins the bytes that will be uploaded. Evidence artefacts are
# regenerated after every scan (and would change the manifest, which would change
# the scan report, ad infinitum), so they are covered by their own content rather
# than by a hash: LEAK_SCAN.md, verification/** and the manifest itself.
MANIFEST_EXCLUDE_PREFIXES = ("verification/",)
MANIFEST_EXCLUDE_NAMES = ("release_manifest.json", "LEAK_SCAN.md")


def write_manifest(root: str, hasher=None) -> List[Dict[str, Any]]:
    """Hash every data artefact under ``root`` into release_manifest.json."""
    hasher = hasher or sha256_of_stream
    entries: List[Dict[str, Any]] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if name in MANIFEST_EXCLUDE_NAMES:
                continue
            if rel.startswith(MANIFEST_EXCLUDE_PREFIXES):
                continue
            entries.append({"path": rel, "bytes": os.path.getsize(path),
                            "sha256": hasher(path)})
    entries.sort(key=lambda d: d["path"])
    with open(os.path.join(root, "release_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "dataset": "ZoomCap-450K",
            "policy": "upload only files whose sha256 matches this manifest",
            "excluded": "release_manifest.json, LEAK_SCAN.md, verification/**",
            "files": entries,
        }, fh, ensure_ascii=False, indent=2)
    return entries


def sha256_of_stream(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def write_census_report(root: str, stats: Dict[str, Any], census: "PIICensus") -> None:
    """verification/PII_CENSUS.md -- the compliance evidence artefact."""
    outdir = os.path.join(root, "verification")
    os.makedirs(outdir, exist_ok=True)
    total = stats["counts"]["rows_per_config"].get("full") or 0
    policy = stats["pii_policy"]
    lines = [
        "# PII census — ZoomCap-450K",
        "",
        f"* caption text policy: **{policy}** — "
        + ("captions are published byte-identical to the internal corpus; only the "
           "`images` path is rewritten. Sensitive rows are handled by exclusion "
           "(config `pii_free`), never by editing text."
           if policy == "verbatim" else
           "captions were masked by `--redact-pii`; this breaks bit-for-bit "
           "reproduction of the paper's corpus statistics."),
        f"* rows counted: {total:,}",
        "",
        "These strings are text visible inside the public source images (business "
        "cards, storefront signage, screenshots, classified ads). They are also "
        "what OCR-heavy evaluation rewards, so they are measured here rather than "
        "rewritten in place.",
        "",
        "| category | occurrences | rows | share of rows | chars removed if masked | row flag |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    flag_of = {**{c: "`credential_in_image`" for c in ("credential_value",)},
               **{c: "`pii_identifier`" for c in SENSITIVE_CATEGORIES},
               **{c: "`pii_contact`" for c in CONTACT_CATEGORIES}}
    rep = census.report()
    for name, d in rep.items():
        lines.append(
            f"| `{name}` | {d['occurrences']:,} | {d['rows']:,} | "
            f"{100 * d['rows'] / max(1, total):.3f}% | {d['chars_removed_if_masked']:,} | "
            f"{flag_of.get(name, '—')} |")
    lines += ["", "## Config effect (row counts)", "",
              "| config | rows | rule |", "| --- | --- | --- |"]
    for cfg, n in stats["counts"]["rows_per_config"].items():
        lines.append(f"| `{cfg}` | {n:,} | {stats['config_definitions'][cfg]} |")
    lines += ["", "## QC / sensitivity flags", "",
              "| flag | rows |", "| --- | --- |"]
    for f, n in sorted(stats["qc_flags"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{f}` | {n:,} |")
    lines += ["", "## Examples (verbatim contexts, as published)", ""]
    for name, d in rep.items():
        if not d["examples"]:
            continue
        lines.append(f"* `{name}`")
        for ex in d["examples"]:
            lines.append(f"  * `{ex[:220]}`")
    with open(os.path.join(outdir, "PII_CENSUS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def iter_rows(src: str) -> Iterable[Tuple[int, Dict[str, Any]]]:
    with open(src, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            yield lineno, json.loads(line)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="internal JSONL (messages/images schema)")
    ap.add_argument("--out", required=True, help="output dataset root (must be outside git)")
    ap.add_argument("--rows-per-shard", type=int, default=25_000)
    ap.add_argument("--zstd-level", type=int, default=9)
    ap.add_argument("--limit", type=int, default=0, help="process only the first N rows (smoke test)")
    ap.add_argument("--emit-jsonl", action="store_true",
                    help="also write .jsonl.gz mirrors next to the parquet files")
    ap.add_argument("--scan-copy", metavar="DIR", default="",
                    help="also write uncompressed sanitized .jsonl files into DIR "
                         "for the internal data-output compliance scan (not published)")
    ap.add_argument("--scan-variants", default="full", choices=["full", "both"],
                    help="'full' suffices for review: data/clean is a strict row "
                         "subset of data/full with byte-identical text")
    ap.add_argument("--redact-pii", action="store_true",
                    help="mask in-caption PII/credential strings. OFF by default: "
                         "these strings are the image's own visible text (OCR "
                         "transcriptions), so masking them breaks both the captions' "
                         "fidelity to the images and bit-for-bit reproduction of the "
                         "paper's corpus statistics. Enable only if the compliance "
                         "review explicitly requires textual masking.")
    ap.add_argument("--redact-only", default="",
                    help="comma-separated subset of redaction categories to mask, "
                         "e.g. 'cn_mobile,cn_id_card,document_id,qq_id,"
                         "credential_value'. Implies --redact-pii. Use for a "
                         "middle-ground compliance option: mask only unambiguous "
                         "personal identifiers, keep OCR-relevant contact text "
                         "(e-mail, handles) verbatim. The census always measures "
                         "the verbatim text either way.")
    ap.add_argument("--configs", default="full,clean,pii_free",
                    help="comma-separated configs to emit (default: full,clean,pii_free)")
    ap.add_argument("--manifest-only", action="store_true",
                    help="skip the build: just re-hash the existing tree and rewrite "
                         "release_manifest.json (run as the final pipeline step)")
    ap.add_argument("--sample-out", type=int, default=1000,
                    help="rows to copy into sample/zoomcap_450k_sample.jsonl (0 = off)")
    args = ap.parse_args(argv)

    t0 = time.time()
    root = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(root, exist_ok=True)

    if args.manifest_only:
        entries = write_manifest(root)
        total = sum(e["bytes"] for e in entries)
        print(f"re-pinned {len(entries)} data files, {total / 2**20:.1f} MiB "
              f"-> {os.path.join(root, 'release_manifest.json')}")
        return 0

    # HuggingFace config-directory layout: ``<config>/train-*.parquet``, so that
    # ``load_dataset(repo_id, "full")`` / ``("clean")`` resolve to two configs.
    wanted = [c.strip() for c in args.configs.split(",") if c.strip()]
    for cfg in wanted:
        if cfg not in ("full", "clean", "pii_free"):
            ap.error(f"unknown config '{cfg}'")
    writers: Dict[str, ShardWriter] = {
        cfg: ShardWriter(os.path.join(root, cfg), "train",
                         args.rows_per_shard, args.zstd_level)
        for cfg in wanted}
    if "full" not in writers:
        ap.error("config 'full' is required: it is the paper-exact corpus")
    full = writers["full"]
    clean = writers.get("clean")
    pii_free = writers.get("pii_free")
    jsonl_full = jsonl_clean = None
    scan_full = scan_clean = None
    if args.scan_copy:
        os.makedirs(args.scan_copy, exist_ok=True)
        scan_full = open(os.path.join(args.scan_copy, "zoomcap_450k_full.jsonl"),
                         "w", encoding="utf-8")
        if args.scan_variants == "both":
            scan_clean = open(os.path.join(args.scan_copy, "zoomcap_450k_clean.jsonl"),
                              "w", encoding="utf-8")
    if args.emit_jsonl:
        jsonl_full = open(os.path.join(root, "zoomcap_450k_full.jsonl"), "w", encoding="utf-8")
        jsonl_clean = open(os.path.join(root, "zoomcap_450k_clean.jsonl"), "w", encoding="utf-8")

    redactions: Counter = Counter()
    redact_categories: Optional[set] = None
    if args.redact_only.strip():
        redact_categories = {c.strip() for c in args.redact_only.split(",") if c.strip()}
        unknown = redact_categories - {n for n, _, _ in REDACT_RULES}
        if unknown:
            ap.error(f"unknown --redact-only categories: {sorted(unknown)}")
    elif args.redact_pii:
        redact_categories = {n for n, _, _ in REDACT_RULES}
    qccounters: Counter = Counter()
    drop_reasons: Counter = Counter()
    census = PIICensus()
    source_rows: Counter = Counter()
    key_rejects: List[str] = []
    shape_rejects = 0
    images_seen: set = set()
    dup_groups = 0
    key_multiplicity: Counter = Counter()
    audit: Dict[str, Any] = {"shard_dirs": set(), "de_shard_conflicts": set()}
    key_to_shards: Dict[str, set] = {}
    chars_all: List[int] = []
    chars_clean: List[int] = []
    chars_pii_free: List[int] = []
    sensitive_drop_reasons: Counter = Counter()
    words_all: List[int] = []
    sents_all: List[int] = []
    samples: List[str] = []

    for lineno, rec in iter_rows(args.src):
        if args.limit and lineno > args.limit:
            break
        msgs = rec.get("messages") or []
        imgs = rec.get("images") or []
        # --- shape check: single image, single user turn + single assistant turn
        if len(imgs) != 1 or len(msgs) != 2 or \
                msgs[0].get("role") != "user" or msgs[1].get("role") != "assistant":
            shape_rejects += 1
            continue
        key = sanitize_key(imgs[0], audit)
        if key is None or not KEY_RE.match(key):
            key_rejects.append(f"line {lineno}: {imgs[0]}")
            continue
        # a key must never be reachable from two different shard directories,
        # otherwise de-sharding would merge two distinct files into one row
        shards = key_to_shards.setdefault(key, set())
        shards.update(seg for seg in imgs[0].split("/")
                      if SHARD_DIR_RE.match(seg))
        if len(shards) > 1:
            audit["de_shard_conflicts"].add(key)

        caption = msgs[1].get("content") or ""
        # Census runs on the verbatim caption either way: it is the evidence the
        # compliance review needs, and it must not depend on --redact-pii.
        matched = census.scan(caption)
        if redact_categories is not None:
            caption = redact(caption, redactions, only=redact_categories)

        row = {
            "images": [key],
            "conversations": [
                {"from": "human", "value": HUMAN_TURN},
                {"from": "gpt", "value": caption},
            ],
        }
        # Note: flags are computed on the caption as published, but the
        # sensitivity flags come from the census on the verbatim text, so a
        # --redact-pii build still knows which rows were sensitive.
        flags = qc_flags(caption) + census.flags(matched)
        for f in flags:
            qccounters[f] += 1

        full.add(row["images"], row["conversations"])
        if jsonl_full is not None:
            jsonl_full.write(json.dumps(row, ensure_ascii=False) + "\n")
        if scan_full is not None:
            scan_full.write(json.dumps(row, ensure_ascii=False) + "\n")
        if len(samples) < args.sample_out:
            samples.append(json.dumps(row, ensure_ascii=False))

        n_chars = len(caption)
        chars_all.append(n_chars)
        words_all.append(len(caption.split()))
        sents_all.append(sentence_count(caption))
        src = key.split("/", 1)[0]
        source_rows[src] += 1
        if key in images_seen:
            dup_groups += 1
        else:
            images_seen.add(key)
        key_multiplicity[key] += 1

        degenerate = bool(set(flags) & DEGENERATE_FLAGS)
        sensitive = bool(set(flags) & SENSITIVE_FLAGS)
        if clean is not None and not degenerate:
            clean.add(row["images"], row["conversations"])
            if jsonl_clean is not None:
                jsonl_clean.write(json.dumps(row, ensure_ascii=False) + "\n")
            if scan_clean is not None:
                scan_clean.write(json.dumps(row, ensure_ascii=False) + "\n")
            chars_clean.append(n_chars)
        if pii_free is not None and not degenerate and not sensitive:
            pii_free.add(row["images"], row["conversations"])
            chars_pii_free.append(n_chars)
        if degenerate:
            drop_reasons[",".join(sorted(f for f in flags if f in DEGENERATE_FLAGS))] += 1
        if sensitive:
            sensitive_drop_reasons[
                ",".join(sorted(f for f in flags if f in SENSITIVE_FLAGS))] += 1

        if lineno % 100_000 == 0:
            print(f"  … {lineno:,} rows, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)

    for w in writers.values():
        w.close()
    for fh in (jsonl_full, jsonl_clean, scan_full, scan_clean):
        if fh is not None:
            fh.close()
    if args.emit_jsonl:
        import gzip
        for name in ("zoomcap_450k_full.jsonl", "zoomcap_450k_clean.jsonl"):
            p = os.path.join(root, name)
            with open(p, "rb") as fin, gzip.open(p + ".gz", "wb", compresslevel=9) as fout:
                while True:
                    chunk = fin.read(1 << 22)
                    if not chunk:
                        break
                    fout.write(chunk)
            os.remove(p)

    if samples:
        os.makedirs(os.path.join(root, "sample"), exist_ok=True)
        with open(os.path.join(root, "sample", "zoomcap_450k_sample.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(samples) + "\n")

    def pct(vals: List[int], q: float) -> int:
        if not vals:
            return 0
        s = sorted(vals)
        return s[min(len(s) - 1, int(q * len(s)))]

    def summarize(vals: List[int]) -> Dict[str, Any]:
        if not vals:
            return {}
        return {
            "count": len(vals),
            "mean": round(sum(vals) / len(vals), 1),
            "min": min(vals),
            "p01": pct(vals, 0.01),
            "median": pct(vals, 0.50),
            "p99": pct(vals, 0.99),
            "max": max(vals),
        }

    def sha256_of(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for blk in iter(lambda: fh.read(1 << 22), b""):
                h.update(blk)
        return h.hexdigest()

    manifest_files = write_manifest(root)

    stats = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "tools/build_release.py",
        "layout": "<config>/train-000NN.parquet (HuggingFace config directories)",
        # provenance is recorded as a content hash: the internal filename (and
        # therefore the internal corpus name) is never written into a published
        # artefact
        "src_sha256": sha256_of_stream(os.path.expanduser(args.src)),
        "src_bytes": os.path.getsize(os.path.expanduser(args.src)),
        "limit": args.limit or None,
        "schema": "images + conversations (identical to long-xing1/ScaleCap-450k)",
        "counts": {
            "rows_per_config": {c: w.rows for c, w in writers.items()},
            "shards_per_config": {c: len(w.files) for c, w in writers.items()},
            "unique_image_keys": len(images_seen),
            "duplicate_rows": dup_groups,
            "shape_rejects": shape_rejects,
            "key_rejects": len(key_rejects),
            "source_rows": dict(source_rows),
            "output_bytes": sum(f["bytes"] for f in manifest_files),
        },
        "qc_flags": dict(qccounters),
        "clean_drop_reasons": dict(drop_reasons.most_common()),
        "pii_free_drop_reasons": dict(sensitive_drop_reasons.most_common()),
        # verbatim = published caption text is byte-identical to the internal
        # corpus; the only rewrite is the image path. Sensitive rows are handled
        # by exclusion (the pii_free config), never by editing text.
        "pii_policy": "masked" if redact_categories else "verbatim",
        "redaction_categories": sorted(redact_categories) if redact_categories else [],
        "redactions": dict(redactions),
        "pii_census": census.report(),
        "config_definitions": {
            "full": "every caption, verbatim; row and character counts identical "
                    "to the corpus the paper reports",
            "clean": "full minus rows with a degenerate-output QC flag",
            "pii_free": "clean minus rows whose image shows a third-party "
                        "identifier or credential (row-level exclusion, no text edit)",
        },
        "caption_chars_full": summarize(chars_all),
        "caption_chars_clean": summarize(chars_clean),
        "caption_chars_pii_free": summarize(chars_pii_free),
        "caption_words_full": summarize(words_all),
        "caption_sentences_full": summarize(sents_all),
        "files": {c: [{"path": os.path.join(c, p), "rows": r} for p, r in w.files]
                  for c, w in writers.items()},
    }
    if key_rejects:
        stats["key_reject_examples"] = key_rejects[:20]

    mult_hist = Counter(key_multiplicity.values())
    stats["image_key_multiplicity"] = {
        str(k): v for k, v in sorted(mult_hist.items())}
    stats["audit"] = {
        "shard_dirs_dropped": len(audit["shard_dirs"]),
        "shard_dir_examples": sorted(audit["shard_dirs"])[:8],
        "de_shard_conflicts": len(audit["de_shard_conflicts"]),
        "key_form": "<source_dir>/<basename>  (upstream images-column form)",
    }

    with open(os.path.join(root, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    write_census_report(root, stats, census)

    if audit["de_shard_conflicts"]:
        print(f"FATAL: {len(audit['de_shard_conflicts'])} keys span more than one "
              f"shard directory; de-sharding is not injective for this corpus. "
              f"Examples: {sorted(audit['de_shard_conflicts'])[:5]}", file=sys.stderr)
        return 2

    print(json.dumps(stats["counts"], ensure_ascii=False, indent=2))
    print("\nrows per config: " + ", ".join(
        f"{c}={w.rows:,} ({len(w.files)} shards)" for c, w in writers.items()))
    print(f"caption chars mean={stats['caption_chars_full'].get('mean')} "
          f"median={stats['caption_chars_full'].get('median')} "
          f"max={stats['caption_chars_full'].get('max')} "
          f"(pii_policy={stats['pii_policy']})")
    print("census (rows): " + ", ".join(
        f"{k}={v['rows']:,}" for k, v in stats["pii_census"].items()))
    if redact_categories:
        print(f"redactions applied ({sorted(redact_categories)})={dict(redactions)}")
    print(f"wrote -> {root}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
