#!/usr/bin/env python3
"""Recompute the corpus statistics that the paper reports for ZoomCap-450K.

Reads the published parquet (nothing internal) and reproduces, per split, the
four columns of ``tables/dataset_stats.tex``: average characters, words,
sentences and entities per caption, plus the row / unique-image counts.

Character, word and sentence counts are deterministic and are the numbers the
table quotes.  The **entity** count is only reproducible with the counter used
for the paper; what is implemented here is a clearly-labelled regex proxy
(capitalised surface forms and bold/quoted spans) so the card can state a
number that a third party can recompute.  Replace ``entity_mentions()`` with the
original script before claiming an exact reproduction of 12.4.

Usage
-----
    python3 tools/compute_corpus_stats.py \
        --root ~/WSP/zoomcap_release/ZoomCap-450K --latex
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

import pyarrow.parquet as pq

SENT_SPLIT = re.compile(r"[.!?]+[\"'”’)\]]*\s+|\Z")
CAPS = re.compile(r"\b[A-Z][A-Za-z0-9&'’\-]*(?:\s+[A-Z][A-Za-z0-9&'’\-]*)+\b")
MARKED = re.compile(r"\*\*[^*\n]{2,60}\*\*|“[^”\n]{2,60}”|\"[^\"\n]{2,60}\"")
HEADER_LINE = re.compile(r"^\s*(?:#{1,6}|\*\s|\-\s|\d+\.\s|\|)")


def entity_mentions(caption: str) -> Dict[str, int]:
    """Regex proxies for named-entity density (see module docstring)."""
    caps = 0
    for line in caption.splitlines():
        if HEADER_LINE.match(line):
            continue
        # drop the sentence-initial capital, which is orthography, not an entity
        for sent in SENT_SPLIT.split(line):
            sent = sent.strip()
            if not sent:
                continue
            body = sent[1:] if sent[0].isupper() else sent
            caps += len(CAPS.findall(body))
    return {"capitalised_forms": caps, "bold_or_quoted": len(MARKED.findall(caption))}


def summarise(vals: List[int]) -> Dict[str, float]:
    if not vals:
        return {}
    s = sorted(vals)

    def q(p: float) -> float:
        return s[min(len(s) - 1, int(p * len(s)))]
    return {
        "count": len(vals),
        "mean": round(sum(vals) / len(vals), 1),
        "median": q(0.5), "p01": q(0.01), "p99": q(0.99),
        "min": s[0], "max": s[-1],
    }


def collect(parquets: Iterable[str]) -> Dict[str, Any]:
    chars: List[int] = []
    words: List[int] = []
    sents: List[int] = []
    ent_caps: List[int] = []
    ent_marked: List[int] = []
    keys: set = set()
    per_source: Counter = Counter()
    for path in parquets:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=2048):
            imgs = batch.column("images").to_pylist()
            convs = batch.column("conversations").to_pylist()
            for im, conv in zip(imgs, convs):
                if im:
                    keys.add(im[0])
                    per_source[im[0].split("/", 1)[0]] += 1
                text = "".join(t.get("value", "") for t in (conv or [])
                               if t.get("from") == "gpt")
                chars.append(len(text))
                words.append(len(text.split()))
                sents.append(sum(1 for s in SENT_SPLIT.split(text) if s.strip()))
                ent = entity_mentions(text)
                ent_caps.append(ent["capitalised_forms"])
                ent_marked.append(ent["bold_or_quoted"])
    return {
        "rows": len(chars), "unique_image_keys": len(keys),
        "rows_per_source": dict(per_source),
        "caption_chars": summarise(chars),
        "caption_words": summarise(words),
        "caption_sentences": summarise(sents),
        "entity_proxy_capitalised_forms": summarise(ent_caps),
        "entity_proxy_bold_or_quoted": summarise(ent_marked),
        "chars_per_word": round(sum(chars) / max(1, sum(words)), 2),
        "words_per_sentence": round(sum(words) / max(1, sum(sents)), 1),
    }


def split_files(root: str, split: str) -> List[str]:
    d = os.path.join(root, split)
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".parquet")) \
        if os.path.isdir(d) else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--splits", nargs="+", default=["full", "clean", "pii_free"])
    ap.add_argument("--latex", action="store_true",
                    help="also print a row for tables/dataset_stats.tex")
    args = ap.parse_args(argv)

    root = os.path.abspath(os.path.expanduser(args.root))
    out: Dict[str, Any] = {}
    for split in args.splits:
        files = split_files(root, split)
        if not files:
            print(f"  (no parquet for split '{split}')", file=sys.stderr)
            continue
        print(f"computing {split} ({len(files)} shards)...", file=sys.stderr, flush=True)
        out[split] = collect(files)

    outdir = os.path.join(root, "verification")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "corpus_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    md = ["# Corpus statistics — ZoomCap-450K (recomputed from the published files)", "",
          "Entity counts are regex proxies; see `tools/compute_corpus_stats.py`.", ""]
    md.append("| split | rows | unique images | avg chars | avg words | avg sents | median chars | p99 chars | max chars | avg entities (caps) | avg entities (bold/quoted) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for split, st in out.items():
        md.append(
            f"| `{split}` | {st['rows']:,} | {st['unique_image_keys']:,} | "
            f"{st['caption_chars'].get('mean')} | {st['caption_words'].get('mean')} | "
            f"{st['caption_sentences'].get('mean')} | {st['caption_chars'].get('median')} | "
            f"{st['caption_chars'].get('p99')} | {st['caption_chars'].get('max')} | "
            f"{st['entity_proxy_capitalised_forms'].get('mean')} | "
            f"{st['entity_proxy_bold_or_quoted'].get('mean')} |")
    md.append("")
    md.append("```json")
    md.append(json.dumps(out, ensure_ascii=False, indent=2))
    md.append("```")
    with open(os.path.join(outdir, "CORPUS_STATS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    for split, st in out.items():
        print(f"\n=== {split} ===")
        print(json.dumps({k: v for k, v in st.items()
                          if k in ("rows", "unique_image_keys", "rows_per_source",
                                   "caption_chars", "caption_words",
                                   "caption_sentences", "chars_per_word",
                                   "words_per_sentence")}, ensure_ascii=False, indent=2))
    if args.latex and "full" in out:
        st = out["full"]
        print("\n% LaTeX row (column order of tables/dataset_stats.tex):")
        print(r"\textbf{ZoomCap-450K (Ours)} & %dK & ShareGPT4V-100K + LAION-5B subset & ZoomCap "
              r"& %.1f & %.1f & %.1f & -- \\" % (
                  st["unique_image_keys"] // 1000,
                  st["caption_chars"]["mean"],
                  st["caption_words"]["mean"],
                  st["caption_sentences"]["mean"]))
    print(f"\nwrote {outdir}/CORPUS_STATS.md and corpus_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
