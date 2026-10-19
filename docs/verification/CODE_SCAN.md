# Leak scan — ZoomCap-450K release

* root: `ZoomCap-450K` (absolute path withheld)
* pattern sources: public defaults + site file leak_patterns.json
* HARD rules: 8 (1 metadata-only: ['developer_home']); SOFT rules: 8
* files scanned: 27; captions scanned: 1,000
* caption text policy: `unknown` (from stats.json)
* expected SOFT residue (allowed by policy): ['n/a (code target)']
* target: `code` (SOFT rules disabled: a scanner's own patterns are not leaks)

## HARD hits (must be zero)
* none ✅

## SOFT hits — must be reviewed before publishing
* none ✅

## SOFT residue allowed by policy (text visible in the public source images)
* none

## Redaction tokens present in published text
(counts span every published copy of a row: `full`, `clean`, `sample`)
* `<email>`: 2
* `<path>`: 2
* `<handle>`: 2
* `<cn-phone>`: 2
* `<cn-id>`: 2
* `<qq-id>`: 2
* `<doc-id>`: 2
* `<redacted>`: 4

## Files scanned
* `.gitignore`
* `LICENSE`
* `NOTICE.md`
* `README.md`
* `tools/build_release.py`
* `tools/compute_corpus_stats.py`
* `tools/scan_leaks.py`
* `tools/verify_join.py`
* `tools/verify_pii_free.py`
* `docs/TOOLING.md`
* `docs/dataset_card.md`
* `docs/verification/CORPUS_STATS.md`
* `docs/verification/JOIN_VERIFICATION.md`
* `docs/verification/LEAK_SCAN.md`
* `docs/verification/PII_CENSUS.md`
* `docs/verification/PII_FREE_CHECK.md`
* `sample/zoomcap_450k_pii_free_sample.jsonl`
* `assets/adoption.png`
* `assets/fact_density.png`
* `assets/factcycle.png`
* `assets/mechanisms.png`
* `assets/qualitative.png`
* `assets/t2i_main.jpg`
* `assets/t2i_more.jpg`
* `assets/t2i_scatter.png`
* `assets/teaser.png`
* `assets/zoomflow.jpg`
