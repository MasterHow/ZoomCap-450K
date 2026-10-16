# ZoomCap-450K

Dense image captions produced by the **ZoomCap evidence-routing workflow**, published as a drop-in caption replacement for [ScaleCap-450k](https://huggingface.co/datasets/long-xing1/ScaleCap-450k).

* **Data (captions only, no images):** https://huggingface.co/datasets/MasterHow/ZoomCap-450K — CC BY-NC 4.0, research use only
* **This repository:** the tooling that builds, sanitises, quality-checks, censuses and verifies that corpus — Apache-2.0
* **Paper:** [ZoomCap: Evidence-Routed Visual Zooming for Recoverable Visual Information Transfer](https://arxiv.org/abs/2610.21320) (arXiv:2610.21320)


---

# ZoomCap-450K — public release tooling

Scripts that turn the internal caption JSONL into the corpus we are allowed to
publish. **Nothing here uploads anything by itself**: every artefact is written
to a local directory, then reviewed, then submitted through the internal
data-output approval, and only after approval is it pushed to HuggingFace /
GitHub.

The published rows use exactly the schema of the upstream corpus they overlay —
[`long-xing1/ScaleCap-450k`](https://huggingface.co/datasets/long-xing1/ScaleCap-450k)
(`images` + `conversations`, ScaleCap's own field names and its literal `<image>`
human turn) — so ZoomCap-450K swaps into a ScaleCap training recipe with no
loader changes. No extra columns are added.

## Pipeline

```
internal JSONL                     build_release.py                     published tree
  messages + absolute      --->    rewrite image paths to         --->   full/train-*.parquet
  internal image paths             upstream join keys; QC +              clean/train-*.parquet
  (caption text untouched)         PII census; never edits text          pii_free/train-*.parquet
                                                                          sample/*.jsonl
                                   verify_join.py                   --->   stats.json
                                   scan_leaks.py                          release_manifest.json
                                   compute_corpus_stats.py                LEAK_SCAN.md
                                   verify_pii_free.py                     verification/*.md

                                   build_release.py --scan-copy   --->    ../scan_copy/*.jsonl
                                   (plain-text copy for the               internal only, never
                                    content-safety platform)               published
```

| Script | What it does | When to run |
| --- | --- | --- |
| `build_release.py` | Rewrites internal absolute image paths to the upstream join key `<source_dir>/<basename>`, computes QC and PII flags, and writes three configs + sample + `stats.json` + `release_manifest.json` + `verification/PII_CENSUS.md` (+ an uncompressed JSONL copy for the compliance scan). Caption text is left **verbatim** by default; `--redact-pii` exists only as a compliance fallback | once per data revision |
| `verify_join.py` | `structure` — schema/types, key grammar, row and shard totals reconciled with `stats.json`; `loadable` — loads a shard through `datasets` and asserts the arrow feature signature equals ScaleCap-450k's; `upstream` — samples keys against ScaleCap-450k through the HF datasets-server (needs internet, self-skips offline) | after every build |
| `scan_leaks.py` | `--target data` walks the release tree: internal identifiers (HARD, must be zero) + third-party PII residue (SOFT, human-reviewed), and writes `LEAK_SCAN.md`; `--target code` applies the internal-marker rules to the scripts/card that go to GitHub | after every build, before submission |
| `compute_corpus_stats.py` | Recomputes the paper's corpus-statistics columns from the published files and writes `CORPUS_STATS.md` | after every build |
| `verify_pii_free.py` | Re-detects every PII pattern family over the published `pii_free` parquet — independently of the build's own flags — and requires zero hits; writes `PII_FREE_CHECK.md`. This is the artefact behind the "contains no personal information" statement on the approval form | before submission, if `pii_free` is what gets published |
| `dataset_card.md` | Draft HuggingFace dataset card (publish as `README.md` of the HF repo) | at upload time |

Generated artefacts live **outside** the git repo (default
`~/WSP/zoomcap_`) so they never enter the arXiv bundle;
`make_arxiv_bundle.sh` copies an explicit file list and never sees this repository.

## Run it

```bash
SRC=<internal caption JSONL>                    # never published, path stays local
OUT=~/WSP/zoomcap_ZoomCap-450K

python3 tools/build_release.py --src "$SRC" --out "$OUT" \
    --scan-copy ~/WSP/zoomcap_scan_copy \
    --rows-per-shard 50000 --zstd-level 9 --sample-out 1000
python3 tools/verify_join.py --root "$OUT" --mode both --sample 200 \
    --emit-keys ~/WSP/zoomcap_zoomcap450k_image_keys.txt.gz
python3 tools/scan_leaks.py  --root "$OUT"          # must exit 0 (~20 min, 3 configs)
python3 tools/compute_corpus_stats.py --root "$OUT" --latex
python3 tools/verify_pii_free.py --root "$OUT"      # must exit 0 if pii_free ships

# last step: re-pin the sha256 manifest over the final data files, so the bytes
# that were scanned are provably the bytes that get uploaded
python3 tools/build_release.py --src "$SRC" --out "$OUT" --manifest-only

# before the *scripts* + card go to GitHub: prove they carry no internal
# identifiers either ('code' target = internal-marker rules only, because a
# scanner's own regex literals and the prose describing them are not leaks)
PUBSCAN="$TMPDIR/pubscan"; mkdir -p "$PUBSCAN" && \
  cp *.py README.md docs/dataset_card.md "$PUBSCAN/" && \
  python3 tools/scan_leaks.py --root "$PUBSCAN" --target code \
      --report "$PUBSCAN/PUBLIC_SCAN.md"            # must exit 0
```

Full build over 454,963 rows took ~6 min here (10/10/9 shards for
full/clean/pii_free, zstd-9); the leak scan over all three configs (1.35M
captions) takes ~20 min, and `verify_pii_free.py` ~4 min. `--mode both` also loads one
shard through `datasets` and asserts that the arrow feature signature is
identical to ScaleCap-450k's; its upstream membership probe needs internet
and self-skips after a 5 s pre-flight offline (it records `verified: null`,
never a false pass).

## What the current build produced

`release_manifest.json` pins the sha256 of the 31 published files (29 parquet
shards + `stats.json` + the 1,000-row sample; 1.61 GiB); the evidence artefacts (`LEAK_SCAN.md`, `verification/**`) are
excluded so the manifest can be re-pinned after a scan without invalidating
itself. `stats.json` headline numbers:

| | full | clean | pii_free |
| --- | --- | --- | --- |
| rows | 454,963 | 451,276 | 447,285 |
| shards | 10 × parquet | 10 × parquet | 9 × parquet |
| size | 549 MB | 543 MB | 536 MB |
| unique image keys | 440,238 | 436,642 | 432,755 |
| mean caption chars | **4,228.6** | 3,963.3 | 3,966.0 |

* Source split: `laion_filter_image` 352,942 rows, `share4v_image` 102,021 rows.
* Key multiplicity: 431,373 keys appear once, 5,395 twice, 1,848 three times,
  1,000 four times, 494 five, 110 six, 18 seven times — all duplicates are
  ShareGPT4V images that the upstream pool itself repeats; each occurrence got
  its own independent caption.
* Degeneracy QC (kept in `full`, excluded from `clean`): `too_long` (>30k chars)
  3,510; `repetition_line` 3,274; `repetition_word` 2,401; `too_short`
  (<200 chars) 4 → **3,687 rows** removed. Sensitivity flags (`pii_contact`,
  `pii_identifier`, `credential_in_image`) additionally remove **3,991 rows** in
  `pii_free`.
* Caption text is **verbatim**: mean 4,228.6 characters, exactly the figure the
  paper's corpus table reports. No PII masking is applied, because these strings
  are the source images' own visible text — masking them would degrade OCR
  transcriptions, break caption/image consistency and stop the release
  reproducing the paper's statistics. They are *measured* instead
  (`verification/PII_CENSUS.md`): handle 3,943 occurrences / 1,986 rows, e-mail
  2,705 / 1,978, filesystem paths 136 / 95, CN mobiles 80 / 66, in-image
  credentials 10 rows, QQ ids 2, national IDs 0. The affected rows are excluded
  from `pii_free` (3,991 rows, 0.88%) rather than edited.
* De-sharding is safe: the internal cache adds a 4-hex shard directory that the
  upstream corpus does not have; 21 shard directories were dropped and **0 keys
  spanned more than one shard directory** (the build hard-fails if that ever
  changes).

The detection patterns do double duty: they always produce the census, and they
produce masked text only under `--redact-pii` (or a subset via `--redact-only`). Their precision matters because
every false positive silently drops a good row from `pii_free` — which is why the
credential rule accepts only high-precision labels: bare `secret`, `token`,
`account`, `login` and `username` are *not* labels, they matched prose such as
`the account: 'Why do people do this'` and `a shocking secret: **Nami**`.

`scan_leaks.py` separates **internal** identifiers (mount points, developer home
directories, internal corpus/system names, work ids, cloud-credential shapes,
private keys, object-store URIs, bearer tokens — HARD, must be zero) from **third-party** content
rendered inside the public source images (SOFT: e-mails, handles, phone numbers,
in-image credentials), which under the default verbatim policy is expected
residue and is quantified in the census instead. It also reads `pii_policy` from
`stats.json`, so a masked build cannot be waved through as expected residue.

## Known gaps (fix before publishing)

1. **Word / sentence / entity counters disagree with the paper.** This tooling
   reports 648.3 avg words and 31.8 avg sentences for `full`, while
   `tables/dataset_stats.tex` states 622.8 and 33.1; characters match to 0.1.
   The paper's numbers came from the internal statistics script (different
   tokeniser/sentenciser, and an entity counter we do not have here). Either
   drop that script into this repository and re-run, or state in the card that the
   average-words/sentences/entity columns are computed with the internal tool
   and cannot be reproduced from the published files alone.
2. **Route labels (`patched` 280k / `no_patch` 174k) are not in the data.** They
   exist only in the internal filename. The schema is frozen to ScaleCap's, so
   if we want them public they must ship as a side-car file
   (e.g. `route_labels.jsonl.gz` of `image_key → route`), not as a column. That
   needs the pipeline's routing log as the source of truth.
3. **Upstream membership check is unverified from this laptop** (no outbound
   internet). Run `verify_join.py --mode both` from a networked machine: it
   samples image keys and confirms each exists in ScaleCap-450k before we
   advertise "100% joinable".

## Compliance options for the PII question

| option | commands | corpus effect | when to use |
| --- | --- | --- | --- |
| **A. verbatim (default)** | no flags | none — mean 4,228.6 chars, identical to the paper's table | the reviewer accepts image-visible text as the source images' own content |
| **B. exclude rows** | the `pii_free` config (built by default) | −3,991 rows (0.88%), zero text edits | the reviewer needs "no personal information output" to be provable — backed by `verify_pii_free.py` |
| **C. mask identifiers only** | `--redact-only cn_mobile,cn_id_card,document_id,qq_id,credential_value` | ~76 rows' text touched, ≈0.0 chars/caption; e-mails/handles stay verbatim | a middle ground if unambiguous identifiers are the only objection |
| **D. mask everything** | `--redact-pii` | 6,935 replacements, mean drops 4,228.6 → 4,228.5 | only if explicitly required — it corrupts OCR transcriptions, so avoid |

A and B are the recommendation: B is A with rows dropped, so the corpus that the
paper measured and the corpus that ships stay textually identical.

## Order of operations (mandatory)

1. Build → verify → scan → stats (above). `scan_leaks.py` must exit 0 and
   `LEAK_SCAN.md` must show no HARD hits.
2. Human read of `LEAK_SCAN.md`. Under the default verbatim policy every SOFT
   category is *expected* residue (it is image-visible text, quantified in
   `verification/PII_CENSUS.md`); what must be zero is the HARD group —
   internal identifiers.
3. If `pii_free` is the config that goes public, `verify_pii_free.py` must exit 0:
   that is the evidence for the "no personal information output" answer on the
   approval form.
4. Submit `scan_copy/zoomcap_450k_full.jsonl` (1.9 GB plain text — `clean` is a
   strict row subset of `full` with byte-identical text, so one file covers
   both) to the content/data-safety scan, then file the data-output approval
   described in the internal-only companion doc.
5. Only after approval: upload `data/`, `sample/`, `stats.json` and the card to
   HuggingFace, and the scripts + card + sample to GitHub.
6. Update the arXiv statements (Ethics / Reproducibility) to match what is
   actually released, and add the URL in a v2 revision.

## After approval: publishing (manual, not automated)

Nothing in this repository uploads, pushes or authenticates. Once both the data-output
approval and the open-source approval are granted, the person registered on the
approval ticket as the output executor runs, by hand:

```bash
# HuggingFace — data + card (needs `huggingface-cli login` on the approved org)
huggingface-cli upload <org>/ZoomCap-450K ~/WSP/zoomcap_ZoomCap-450K \
    --repo-type dataset --revision main
#   dataset_card.md becomes the repo README.md (frontmatter is already valid)

# GitHub — tooling + docs only, produced by the internal staging tool,
# which refuses to emit anything containing an internal identifier
```

Rules that stay in force after upload:

* the data goes up **only** in the exact form that was scanned and approved
  (`release_manifest.json` hashes each published file — re-run the pipeline and
  re-submit if anything changes);
* the release is CC BY-NC 4.0, research use only; do not re-licence or add
  mirrors with looser terms;
* arXiv v1 must not contain a live URL before approval — use the
  "will be released at …" wording and add the real link in v2.
