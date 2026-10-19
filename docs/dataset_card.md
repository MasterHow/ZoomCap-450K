---
license: cc-by-nc-4.0
license_name: Creative Commons Attribution NonCommercial 4.0
license_link: https://creativecommons.org/licenses/by-nc/4.0/
task_categories:
  - image-to-text
  - text-to-image
  - visual-question-answering
language:
  - en
tags:
  - image-captioning
  - vision-language-model
  - continual-pretraining
  - multimodal
  - captions-only
size_categories:
  - 100K<n<1M
pretty_name: ZoomCap-450K
configs:
  - config_name: full
    data_files: full/*.parquet
  - config_name: clean
    data_files: clean/*.parquet
  - config_name: pii_free
    data_files: pii_free/*.parquet
papers:
  - arXiv:2610.21320
---

# ZoomCap-450K

**Dense image captions produced by the ZoomCap evidence-routing workflow, as a
drop-in caption replacement for
[ScaleCap-450k](https://huggingface.co/datasets/long-xing1/ScaleCap-450k).**

Code, verification tooling and the published evidence reports:
**https://github.com/MasterHow/ZoomCap-450K** (Apache-2.0).

This repository contains **captions only — no images**. Each row carries the
image key under which the picture is published upstream, so the corpus can be
joined to ScaleCap-450k (or to any local copy of the ShareGPT4V / LAION pools)
without redistributing a single picture.

The row schema is intentionally **identical to ScaleCap-450k** (`images` +
`conversations`, including its literal `<image>` human turn), so a ScaleCap
training recipe runs against ZoomCap-450K with no loader changes.

## Why

The companion paper
*ZoomCap: Evidence-Routed Visual Zooming for Recoverable Visual Information
Transfer* treats fine-grained captioning as **recoverable visual information
transfer**: a teacher acquires missing evidence under a finite observation
budget (conditional knowledge retrieval, OCR-sensitive reading, coverage-gap
recovery, adaptive visual zooming with grounded geometry) and converts it into
reusable supervision. Headline results, measured on this corpus and its
evaluations:

| Result | ZoomCap | baseline |
| --- | --- | --- |
| FactCycle transferred claims / image | **52.4** | 31.5 (ScaleCap) |
| Human tie-adjusted preference vs. a 10× larger flagship teacher | **81.9%** | — |
| 11-benchmark CPT average vs. strongest competing 450K corpus | **+1.31 … +2.38** | — |
| Production document/OCR monitor suite (`Ling-Tiny-VL-v3`, 60B tokens) | **+1.4** (+0.90 platform-wide) | — |
| Medical pre-training, 5 VQA benchmarks (2.64M images) | **+3.04** | +1.76 (same-image single-pass captions) |
| Captioning cost per image | **$0.0077** | 3.6× more expensive per image, 5.9× more expensive per transferred claim for the ScaleCap recipe |
| Total characters vs. ScaleCap-450K | **1.45×** | — |

Releasing the corpus is what makes the equal-scale CPT comparison in the paper
checkable.

## Layout

```
full/      train-00000 … train-00009.parquet   454,963 rows   549 MB
clean/     train-00000 … train-00009.parquet   451,276 rows   543 MB
pii_free/  train-00000 … train-00008.parquet   447,285 rows   536 MB
sample/    zoomcap_450k_sample.jsonl             1,000 rows  (readable preview)
stats.json                     per-build counters, QC flags, PII census tallies
release_manifest.json          sha256 + byte size of all 31 published files
verification/PII_CENSUS.md     every personal-information category, measured verbatim
verification/JOIN_VERIFICATION.md  schema + row-count + loadable checks
verification/CORPUS_STATS.md   the paper's corpus-statistics columns, recomputed
verification/PII_FREE_CHECK.md independent re-scan of `pii_free`: 0 detections
LEAK_SCAN.md                   result of the pre-publication internal-identifier scan
```

* `full` — every caption, verbatim, including the small degenerate tail. The row
  and character counts the paper reports refer to this config (mean 4,228.6
  characters, identical to the internal corpus).
* `clean` — `full` minus 3,687 rows with a degenerate-output flag (looped
  repetition, > 30,000 chars, < 200 chars). **Recommended for training.**
* `pii_free` — `clean` minus the 3,991 rows whose source image shows a
  third-party contact string or credential. Provided for users (and reviewers)
  who need a corpus with no such strings; the rows are *dropped*, never edited.

## Loading

```python
from datasets import load_dataset

ds = load_dataset("MasterHow/ZoomCap-450K", "clean", split="train")   # 451,276 rows
# configs: "full" (paper-exact) · "clean" (training) · "pii_free" (no contact rows)
print(ds[0])
# {'images': ['laion_filter_image/7156c3a92b9fdf307f8734b11cd4d98b'
#                            '70317652a937fb9622a24256048b910b.jpg'],
#  'conversations': [{'from': 'human', 'value': '<image>'},
#                    {'from': 'gpt',   'value': 'This dynamic, close-up action shot
#                      captures three Liverpool FC players celebrating a goal …'}]}
```

### Captions + images (join against ScaleCap-450k)

Images are not redistributed here; they live in ScaleCap-450k under exactly the
same key. Index the keys once, then stream the upstream images past them — the
index holds ~440K short strings (~40 MB), and captions stay on disk behind Arrow
random access:

```python
from datasets import load_dataset

zoom = load_dataset("MasterHow/ZoomCap-450K", "clean", split="train")   # arrow-backed
index = {}
for i, row in enumerate(zoom):                 # one pass over the keys only
    index.setdefault(row["images"][0], i)      # use a list if you want every caption
                                               # of a duplicated key

n = 0
for row in load_dataset("long-xing1/ScaleCap-450k", "ScaleCap450k",
                        split="train", streaming=True):
    i = index.get(row["images"][0])            # e.g. 'laion_filter_image/<sha256>.jpg'
    if i is None:
        continue
    caption = zoom[i]["conversations"][1]["value"]
    n += 1                                     # (row["images"][0], caption) is a pair
print("matched", n)
```

ScaleCap-450k is ~95 GB, so prefer `streaming=True`. If you already hold the
ShareGPT4V or LAION image pools locally, the same key resolves there:
`laion_filter_image/<sha256>.jpg` is the LAION-5B image key (sha256 of the source
URL, i.e. what `img2dataset` names its files), and `share4v_image/<name>.jpg` is
ShareGPT4V's own filename (`000000156836.jpg` COCO, `sa_24327.jpg` SAM,
`6e68d8a830ff2821.jpg` CC12M, `Vincent_Cassel.jpg` wikiart).

### LLaMA-Factory / CPT against ScaleCap

Register both corpora and change nothing else — the fields are the same:

```json
// data/dataset_info.json
"zoomcap_450k": {"hf_hub_url": "MasterHow/ZoomCap-450K", "subset": "clean",
                 "formatting": "sharegpt", "columns": {"messages": "conversations",
                 "images": "images"}, "tags": {"role_tag": "from", "content_tag": "value",
                 "user_tag": "human", "assistant_tag": "gpt"}},
"scalecap_450k": {"hf_hub_url": "long-xing1/ScaleCap-450k",
                  "formatting": "sharegpt", "columns": {"messages": "conversations",
                  "images": "images"}}
```

## Contents

| | `full` | `clean` | `pii_free` |
| --- | --- | --- | --- |
| rows | 454,963 | 451,276 | 447,285 |
| unique image keys | 440,238 | 436,642 | 432,755 |
| mean caption characters | 4,228.6 | 3,963.3 | 3,966.0 |
| median / p99 / max characters | 3,932 / 10,117 / 58,722 | 3,922 / 6,581 / 29,215 | 3,926 / 6,581 / 29,215 |
| `laion_filter_image` rows | 352,942 | 350,344 | 346,618 |
| `share4v_image` rows | 102,021 | 100,932 | 100,667 |

`full`'s mean of 4,228.6 characters is the number the paper's corpus-statistics
table reports, reproduced exactly: caption text is published verbatim.

Word and sentence means are recomputed from the published rows with the script in
`verification/CORPUS_STATS.md`; the paper's table quotes 622.8 words and 33.1
sentences from its own internal tokeniser, and the character column (4,228.6) is
reproduced to within 0.1 by the sanitised release.

**Duplicate keys are expected.** The upstream pool repeats 8,865 ShareGPT4V
images (5,395 keys twice, 1,848 three times, 1,000 four times, 494 five, 110 six,
18 seven times → 14,725 extra rows). Every occurrence was captioned
independently, so those rows are *different* captions of the same picture —
useful as augmentation, and something to deduplicate if you want strictly one
caption per image:

```python
seen = set()
ds = ds.filter(lambda r: not (r["images"][0] in seen or seen.add(r["images"][0])))
```

## Processing applied to the internal corpus

Everything below is reproducible from the scripts in the accompanying code
repository (`tools/build_release.py`, `tools/scan_leaks.py`,
`tools/verify_join.py`, `tools/compute_corpus_stats.py`).

1. **Key sanitising.** Captions were produced against an internal image cache
   whose absolute paths are not part of the upstream naming. They are rewritten
   to the upstream form `<source_dir>/<basename>`; the cache's 21 four-hex shard
   directories are dropped. De-sharding was verified injective on this corpus
   (no key is reachable from two shard directories), and the build fails hard if
   that ever changes.
2. **Caption text is published verbatim — no masking.** The strings a PII
   detector finds in this corpus are text *visible inside the source images*
   (contact e-mails on business cards, phone numbers on storefront signage,
   paths in screenshots, social handles in watermarks). Rewriting them would
   break three things at once: the OCR transcriptions that make this corpus
   useful, the caption-image consistency that reconstruction-style evaluation
   measures, and bit-for-bit reproduction of the paper's statistics. Instead we
   measure and expose them:

   | category | occurrences | rows | share of rows |
   | --- | --- | --- | --- |
   | social handle (at-sign username) | 3,943 | 1,986 | 0.44% |
   | e-mail address | 2,705 | 1,978 | 0.43% |
   | local filesystem path | 136 | 95 | 0.02% |
   | mainland-China mobile number | 80 | 66 | 0.015% |
   | in-image credential (password / activation code) | — | 10 | 0.002% |
   | QQ identifier | 2 | 2 | <0.001% |
   | national ID / passport / bank card | 0 | 0 | 0% |

   Verbatim contexts for every category, plus the exact detection patterns, ship
   in `verification/PII_CENSUS.md`; `verification/PII_FREE_CHECK.md` is an
   independent re-scan of the published `pii_free` shards (447,285 rows, 0
   detections) that does not reuse the build's own flags. Nothing in this corpus is Ant Group data:
   the images are the public ShareGPT4V / LAION pools that ScaleCap-450k already
   publishes, and the captions are our model's descriptions of them.
3. **Row-level exclusion, offered as a config.** Every row matching one of those
   categories carries a flag (`pii_contact`, `pii_identifier`,
   `credential_in_image`) and is dropped from `pii_free` — 3,991 rows, 0.88% of
   the corpus. Exclusion replaces editing, so the remaining rows stay exactly as
   generated. Textual masking remains available behind
   `build_release.py --redact-pii` for anyone who needs it; it is off by default
   precisely because it corrupts the corpus.
4. **Degeneracy QC**, deterministic thresholds: `too_short` < 200 chars (4 rows),
   `too_long` > 30,000 chars (3,510), `repetition_line` — one line of >= 40 chars
   repeated more than 5x (3,274), `repetition_word` — one 8-word shingle
   repeated more than 15x (2,401). Flagged rows: **3,687** removed in `clean`,
   kept in `full`.
5. **Internal-identifier scan** of every published file — internal mount points,
   developer home directories, internal corpus/system names, work ids, cloud
   credentials, private keys: **0 hits**. The same scan over the publishing
   scripts and this card is also clean (`LEAK_SCAN.md` ships with the release).
6. **Schema check** against the upstream contract (field order, arrow types,
   literal `<image>` human turn, key grammar, no absolute paths, no empty
   captions), a `datasets.load_dataset` check that the arrow feature signature
   equals ScaleCap-450k's, and reconciliation of every shard's row count with
   `stats.json`.

Residual in-image text is *not* scrubbed: URLs, watermark credits (e.g.
`© AFP/Getty Images`) and public-figure names appear where the source image
shows them, exactly as in the upstream public captions.

## Privacy stance in one paragraph

We publish descriptions of images that are already public. Captions can therefore
contain what those images show — including contact strings of third parties who
never interacted with us. Rather than edit the text (which would silently corrupt
OCR transcriptions and every statistic the paper reports), we (a) publish the full
census with verbatim examples, (b) ship `pii_free`, a config with all such rows
removed, (c) redistribute no images, and (d) restrict the corpus to
non-commercial research use under the upstream licence. If your use case cannot
tolerate any third-party contact string, load `pii_free`.

## Intended use and limitations

* **Intended:** research on vision-language models and text-to-image models —
  caption-corpus comparisons, continual pre-training, caption→image
  reconstruction studies.
* Captions are **model-generated** (teacher: the Qwen3.5-35B-A3B call used in the
  paper's ZoomCap workflow). They can contain hallucinated detail, misattributed
  names and wrong counts; the paper quantifies this rather than hiding it
  (FactCycle's truthfulness anchor exists precisely to measure it). Verify before
  relying on any single caption.
* Captions are English and highly structured (free-text overview plus
  `### Background Knowledge` and `### Visual Detail Supplement` sections), which
  is a property of the workflow, not of the images.
* **Not** for medical, legal or diagnostic use, and not for any
  identification/surveillance of the people who appear in the source images.
* The corpus contains descriptions of images that may depict nudity, violence or
  other disturbing content, inherited from LAION-5B / ShareGPT4V.

## License and attribution

Captions: **CC BY-NC 4.0**, research use only — the same licence as the upstream
corpus this overlays, so no downstream user gains rights beyond what
ScaleCap-450k already grants. The accompanying scripts are Apache-2.0.

No images are redistributed. Obtaining them remains the user's responsibility
under the upstream terms: ScaleCap-450k (CC BY-NC 4.0), ShareGPT4V-100K, and
LAION-5B (which publishes URL metadata only; image copyright stays with the
original creators). If you cannot satisfy those terms, do not use this dataset.

```bibtex
@article{shi2026zoomcap,
  title   = {ZoomCap: Evidence-Routed Visual Zooming for Recoverable Visual
             Information Transfer},
  author  = {Shi, Hao and Wang, Jiafeng and Fu, Yuzhuo and Zhang, Tao and
             Bai, Jian and Zhang, Juelu and Cui, Qing and Huang, Chao},
  journal = {arXiv preprint arXiv:2610.21320},
  year    = {2026}
}

@article{xing2025scalecap,
  title   = {ScaleCap: Inference-Time Scalable Image Captioning via
             Dual-Modality Debiasing},
  author  = {Xing, Long and Huang, Qidong and Dong, Xiaoyi and Zhang, Pan and
             Zang, Yuhang and Cao, Yuhang and Li, Jinsong and Ding, Shuangrui and
             Zhang, Weiming and Yu, Nenghai and Wang, Jiaqi and Wu, Feng and
             Lin, Dahua},
  journal = {arXiv preprint arXiv:2506.19848},
  year    = {2025}
}

@inproceedings{chen2023sharegpt4v,
  title     = {ShareGPT4V: Improving Large Multi-Modal Models with Better Captions},
  author    = {Chen, Lin and Li, Jisong and Dong, Xiaoyi and Zhang, Pan and
               He, Conghui and Wang, Jiaqi and Zhao, Feng and Lin, Dahua},
  booktitle = {European Conference on Computer Vision (ECCV)},
  year      = {2024}
}

@article{schuhmann2021laion,
  title   = {LAION-400M: Open Dataset of CLIP-Filtered 400 Million Image-Text Pairs},
  author  = {Schuhmann, Christoph and others},
  journal = {arXiv preprint arXiv:2111.02114},
  year    = {2021}
}
```

## Contact

Issues on this repository: https://github.com/MasterHow/ZoomCap-450K/issues
