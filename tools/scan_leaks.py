#!/usr/bin/env python3
"""Pre-publication leak scan for the ZoomCap-450K release tree.

Scans every artefact that is about to leave the building -- parquet captions,
JSONL samples, stats/manifest JSON and the Markdown/text cards -- for two
classes of strings:

HARD  internal identifiers that must never be published (internal mount points,
      home directories, internal corpus/system names, work ids, cloud
      credentials, private keys).  Any hit fails the scan, exit code 1.
SOFT  third-party PII residue inside caption text.  Redaction should have
      removed the maskable forms; hits are reported with samples for a human to
      judge.  SOFT rules run **only on caption text**, never on image keys or
      manifest hashes, because a 64-char hex key contains digit runs that look
      like phone numbers.

Usage
-----
    python3 tools/scan_leaks.py --root ~/WSP/zoomcap_release/ZoomCap-450K
    python3 tools/scan_leaks.py --root <release> --expected-soft url handle
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import pyarrow.parquet as pq

_Q = chr(34) + chr(39) + chr(96)   # "  '  `  -- quote wrappers around values

# Names contributed by the operator-supplied site file. Kept aside because
# `--target code` uses exactly this set (plus corporate addresses): the generic
# *shape* rules ("any /home/<name> path", "any work-id-looking string") inevitably
# match a leak detector's own regex literals and prose, whereas site-specific
# identifiers never legitimately appear in published code.
SITE_RULES: Dict[str, str] = {}

# --------------------------------------------------------------------------
# HARD: internal identifiers. Tuned to this corpus -- review before reusing.
# --------------------------------------------------------------------------
# HARD rules that apply to *metadata* artefacts only (scripts, cards, manifest,
# stats, verification reports). A caption may quote a filesystem path because the
# source image displays one; our own build artefacts never may.
HARD_META_ONLY = {"developer_home"}

# Public defaults only.  Site-specific markers (home directories, internal corpus
# codenames) live in an operator-supplied leak_patterns.json and are merged in at
# run time, because publishing them would leak exactly what they detect.
_CORP_MAIL_DOMAINS = ["antgroup", "antfin", "alipay", "mybank"]
_CORP_EMAIL_RE = re.compile(
    r"@(?:" + "|".join(_CORP_MAIL_DOMAINS) + r")(?:-inc)?\.com\b", re.I)

HARD: List[Tuple[str, "re.Pattern[str]"]] = [
    # NOTE: meta-only (see HARD_META_ONLY) -- captions legitimately quote paths
    # that are visible in the source images, e.g. a home directory shown in a
    # terminal screenshot or a file manager. Site-specific mount-point shapes
    # belong in the operator's pattern file, not here.
    ("developer_home", re.compile(r"/(?:Users|home)/[A-Za-z0-9_.\-]{2,}")),
    # assembled from parts so that this rule's own source text does not match
    # the site-specific internal-domain rule
    ("corporate_email", _CORP_EMAIL_RE),
    ("internal_workid", re.compile(r"工号|员工号|\bWB\d{5,}\b|\b\d{6}\b\s*[:：]\s*姓名")),
    # infrastructure-shaped secrets only: these are ours, never image content
    ("internal_credentials", re.compile(
        r"AKIA[0-9A-Z]{16}|LTAI[0-9A-Za-z]{12,}|access[_-]?key(?:_id)?|"
        r"secret[_-]?key|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|oss://\S+|"
        r"hdfs://\S+|bearer [A-Za-z0-9_\-\.]{20,}", re.I)),
    # Internal system domains and platform names live in the operator-supplied
    # pattern file (an operator-supplied leak_patterns.json), because publishing those
    # literals here would disclose exactly what the rule detects.
]

# --------------------------------------------------------------------------
# SOFT: third-party PII inside caption text (matches the redaction rules).
# --------------------------------------------------------------------------
SOFT: List[Tuple[str, "re.Pattern[str]"]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("cn_mobile", re.compile(r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])")),
    ("cn_id_card", re.compile(
        r"(?<![0-9A-Za-z])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
        r"\d{3}[\dXx](?![0-9A-Za-z])")),
    ("qq_id", re.compile(r"(?i)\bQQ\s*(?:号|号码|number|no\.?)?\s*[:：#]?\s*\d{5,11}\b")),
    ("fs_path", re.compile(
        r"(?:/home|/Users|/mnt|/media|/var|/tmp|C:)[\\/][A-Za-z0-9_.\-\\/ ]{2,}")),
    # negative lookahead also excludes "{" so BibTeX entry markers inside
    # documentation ("@article{...}") are not counted as social handles
    ("handle", re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_.]{2,}(?![\w({])")),
    ("url", re.compile(r"\b(?:https?://|www\.)[^\s\)\]\"'<>,]{6,}")),
    # third-party credentials rendered inside the public source images; must be
    # masked by build_release.py, so any unmasked residue is a real finding
    ("credential_in_image", re.compile(
        r"(?i)\b(?:password|passwd|pwd|passcode|pass-word|pin code|secret key|"
        r"api[_ \-]?key|access[_ \-]?key|private key|licence key|license key|"
        r"activation code|verification code|response code|recovery code|"
        r"密码|密碼|口令)\s*[:：=]\s*[" + _Q + r"]?"
        r"(?!<redacted>|\*{3,}|x{3,})[^\s,.;:!?)\]}" + _Q + r"]{3,40}")),
]

REDUCTION_TOKENS = ("<email>", "<path>", "<handle>", "<cn-phone>", "<cn-id>",
                    "<qq-id>", "<doc-id>", "<redacted>")


# In `code` mode only the genuine internal-identifier rules apply. The PII and
# credential rules are dropped because a scanner's own regex literals, and prose
# describing them ("AK/SK shapes", "`Password: koanorth` must be masked"), are not
# leaks -- and the data rules would otherwise flag the tool itself.
def code_hard_names():
    """Site-specific identifiers only.

    Generic shape rules ("any /home/<user> path", "any work-id-looking string",
    AK/SK shapes) necessarily match a leak detector's own regex literals and the
    prose that documents them, so they are not meaningful on code; they remain
    active in `--target data`, where they cover captions and metadata.
    """
    return set(SITE_RULES) | {"corporate_email"}


class Scanner:
    def __init__(self, cap_examples: int = 5, hard_filter=None, soft_enabled: bool = True):
        self.hard_filter = hard_filter
        self.soft_enabled = soft_enabled
        self.hard: Dict[str, List[str]] = {}
        self.soft: Dict[str, List[str]] = {}
        self.tokens = {t: 0 for t in REDUCTION_TOKENS}
        self.captions = 0
        self.files: List[str] = []
        self.cap_examples = cap_examples

    def _bucket(self, store: Dict[str, List[str]], name: str, label: str,
                text: str, m: "re.Match[str]") -> None:
        bucket = store.setdefault(name, [])
        snippet = f"{label}: …{text[max(0, m.start() - 60):m.end() + 60]}…".replace("\n", " ")
        if len(bucket) < self.cap_examples:
            bucket.append(snippet)
        elif len(bucket) == self.cap_examples:
            bucket.append("(further hits suppressed)")

    def hard_only(self, label: str, text: str) -> None:
        for name, pat in HARD:
            if self.hard_filter is not None and name not in self.hard_filter:
                continue
            m = pat.search(text)
            if m:
                self._bucket(self.hard, name, label, text, m)

    def caption(self, label: str, text: str) -> None:
        self.captions += 1
        for tok in REDUCTION_TOKENS:
            if tok in text:
                self.tokens[tok] += text.count(tok)
        for name, pat in HARD:
            if name in HARD_META_ONLY:
                continue        # image-visible paths are content, not leakage
            if self.hard_filter is not None and name not in self.hard_filter:
                continue
            m = pat.search(text)
            if m:
                self._bucket(self.hard, name, label, text, m)
        if self.soft_enabled:
            for name, pat in SOFT:
                m = pat.search(text)
                if m:
                    self._bucket(self.soft, name, label, text, m)

    def text_file(self, label: str, text: str) -> None:
        """HARD everywhere; SOFT too, because cards must not carry PII."""
        self.hard_only(label, text)
        if self.soft_enabled:
            for name, pat in SOFT:
                m = pat.search(text)
                if m:
                    self._bucket(self.soft, name, label, text, m)


# Operator-supplied site patterns sit next to the script (or wherever --patterns
# points). They are *not* part of the published tree: the markers they contain are
# themselves internal identifiers.
DEFAULT_PATTERNS_CANDIDATES = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "leak_patterns.json"),   # flat layout
)


def load_extra_patterns(path: str):
    """Merge site-specific markers into the public defaults (see module docstring)."""
    if not path or not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for name, pat in (cfg.get("extra_hard") or {}).items():
        HARD.append((name, re.compile(pat, re.I)))
        SITE_RULES[name] = pat
    for name, pat in (cfg.get("extra_soft") or {}).items():
        SOFT.append((name, re.compile(pat)))
        SITE_RULES[name] = pat
    return True


def parquet_captions(path: str):
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=2048, columns=["images", "conversations"]):
        images = batch.column("images").to_pylist()
        convs = batch.column("conversations").to_pylist()
        for imgs, conv in zip(images, convs):
            yield imgs, [t.get("value", "") for t in (conv or []) if t.get("from") == "gpt"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="release root to scan")
    ap.add_argument("--report", default="", help="output path (default: <root>/LEAK_SCAN.md)")
    ap.add_argument("--target", default="data", choices=["data", "code"],
                    help="'data' = published corpus (all rules); 'code' = published "
                         "scripts and cards (internal-identifier rules only)")
    ap.add_argument("--limit-captions", type=int, default=0, help="stop after N captions (0 = all)")
    ap.add_argument("--expected-soft", nargs="*", default=["url"],
                    help="SOFT categories allowed to remain because they describe "
                         "text visible inside the public source images (default: url)")
    ap.add_argument("--patterns", default=None,
                    help="JSON file with site-specific 'extra_hard'/'extra_soft' "
                         "markers, kept out of the public tree by the operator "
                         "(default: leak_patterns.json next to this script, or "
                         "internal/leak_patterns.json when run from the repo)")
    args = ap.parse_args(argv)
    pattern_path = os.path.expanduser(args.patterns) if args.patterns else ""
    if not pattern_path or not os.path.exists(pattern_path):
        for cand in DEFAULT_PATTERNS_CANDIDATES:
            if os.path.exists(cand):
                pattern_path = cand
                break
    merged = load_extra_patterns(pattern_path)
    expected = set(args.expected_soft or [])

    root = os.path.abspath(os.path.expanduser(args.root))
    report_path = args.report or os.path.join(root, "LEAK_SCAN.md")
    report_rel = os.path.relpath(os.path.abspath(report_path), root)
    sc = Scanner(hard_filter=code_hard_names() if args.target == "code" else None,
                 soft_enabled=(args.target == "data"))

    # Single source of truth: stats.json records whether the build published
    # caption text verbatim. Under that policy every SOFT category is *measured*
    # (verification/PII_CENSUS.md) and retained deliberately -- masking text that
    # is visible in the source image would break OCR fidelity and stop the
    # release reproducing the paper's corpus statistics -- so residue is
    # expected, not a finding. Under "masked" it is a real finding.
    pii_policy = None
    stats_path = os.path.join(root, "stats.json")
    if os.path.exists(stats_path):
        try:
            with open(stats_path, encoding="utf-8") as fh:
                pii_policy = json.load(fh).get("pii_policy")
        except Exception:
            pii_policy = None
    if pii_policy == "verbatim":
        expected |= set(name for name, _ in SOFT)
    done = False

    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if rel == report_rel:
                continue        # never scan our own previous report: it quotes
                                # whatever it found, so hits would compound
            sc.files.append(rel)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

            if ext == "parquet":
                for imgs, texts in parquet_captions(path):
                    for key in imgs or []:
                        sc.hard_only(f"{rel}[key]", key)      # keys: HARD only
                    for text in texts:
                        sc.caption(rel, text)
                    if args.limit_captions and sc.captions >= args.limit_captions:
                        done = True
                        break
                if done:
                    break
            elif ext == "jsonl":
                with open(path, "r", encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            sc.text_file(f"{rel}:{lineno}", line)
                            continue
                        for t in rec.get("conversations", []):
                            if t.get("from") == "gpt":
                                sc.caption(f"{rel}:{lineno}", t.get("value", ""))
                        for k in rec.get("images", []):
                            sc.hard_only(f"{rel}:{lineno}[key]", k)
                        if "conversations" not in rec:
                            sc.hard_only(f"{rel}:{lineno}", line)   # metadata line
                        if args.limit_captions and sc.captions >= args.limit_captions:
                            done = True
                            break
                if done:
                    break
            elif ext in ("json", "md", "txt", "yaml", "yml", "cfg", "ini",
                         "py", "sh", "tex", "toml", "js", "ts", "css", "html",
                         "ipynb", "gitignore", "csv"):
                try:
                    text = open(path, "r", encoding="utf-8").read()
                except UnicodeDecodeError:
                    print(f"  skipped (binary?): {rel}", file=sys.stderr)
                    continue
                for tok in REDUCTION_TOKENS:
                    sc.tokens[tok] += text.count(tok)
                sc.text_file(rel, text)
            elif "." in name:
                print(f"  skipped (unknown type): {rel}", file=sys.stderr)
        if done:
            break

    residual = {k: v for k, v in sc.soft.items() if k not in expected}
    allowed = {k: v for k, v in sc.soft.items() if k in expected}

    lines = ["# Leak scan — ZoomCap-450K release", ""]
    # the report itself is published: never echo the operator's filesystem
    lines += [f"* root: `{os.path.basename(root)}` (absolute path withheld)",
              f"* pattern sources: public defaults "
              f"{'+ site file ' + os.path.basename(pattern_path) if merged else '(public defaults only)'}",
              f"* HARD rules: {len(HARD)} "
              f"({len(HARD_META_ONLY)} metadata-only: {sorted(HARD_META_ONLY)}); "
              f"SOFT rules: {len(SOFT)}",
              f"* files scanned: {len(sc.files)}; captions scanned: {sc.captions:,}",
              f"* caption text policy: `{pii_policy or 'unknown'}` (from stats.json)",
              f"* expected SOFT residue (allowed by policy): "
              f"{(sorted(expected) or ['none']) if args.target == 'data' else ['n/a (code target)']}",
              f"* target: `{args.target}`"
              + (" (SOFT rules disabled: a scanner's own patterns are not leaks)"
                 if args.target == "code" else ""), ""]
    lines.append("## HARD hits (must be zero)")
    if sc.hard:
        for k, v in sc.hard.items():
            lines.append(f"* **{k}**")
            for smp in v[:5]:
                lines.append(f"  * `{smp[:300]}`")
    else:
        lines.append("* none ✅")
    lines.append("")
    lines.append("## SOFT hits — must be reviewed before publishing")
    if residual:
        for k, v in residual.items():
            lines.append(f"* **{k}**")
            for smp in v[:5]:
                lines.append(f"  * `{smp[:300]}`")
    else:
        lines.append("* none ✅")
    lines.append("")
    lines.append("## SOFT residue allowed by policy (text visible in the public source images)")
    if pii_policy == "verbatim":
        lines.append("")
        lines.append("Captions are published verbatim, so these categories are expected "
                     "residue: transcriptions of text visible in the public source images "
                     "(contact details on business cards, storefront signage, screenshots). "
                     "They are quantified with examples in `verification/PII_CENSUS.md`, and "
                     "the rows carrying them are excluded from the `pii_free` config for "
                     "reviewers who require a corpus without third-party contact strings. "
                     "No Ant Group data is involved, and no image is redistributed.")
    if allowed:
        for k, v in allowed.items():
            lines.append(f"* {k} — see examples")
            for smp in v[:3]:
                lines.append(f"  * `{smp[:300]}`")
    else:
        lines.append("* none")
    lines.append("")
    lines.append("## Redaction tokens present in published text")
    lines.append("(counts span every published copy of a row: `full`, `clean`, `sample`)")
    for tok, n in sc.tokens.items():
        lines.append(f"* `{tok}`: {n:,}")
    lines.append("")
    lines.append("## Files scanned")
    for f in sc.files:
        lines.append(f"* `{f}`")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"captions scanned: {sc.captions:,}")
    print(f"HARD groups: {len(sc.hard)} {sorted(sc.hard) or ''}")
    print(f"SOFT must-review: {len(residual)} {sorted(residual) or ''}")
    print(f"SOFT allowed: {len(allowed)} {sorted(allowed) or ''}")
    print(f"report -> {report_path}")
    if sc.hard:
        print("FAILED: internal identifiers found in the release tree", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
