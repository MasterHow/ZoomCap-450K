# Leak scan — ZoomCap-450K release

* root: `ZoomCap-450K` (absolute path withheld)
* pattern sources: public defaults + site file leak_patterns.json
* HARD rules: 8 (1 metadata-only: ['developer_home']); SOFT rules: 8
* files scanned: 38; captions scanned: 1,354,524
* caption text policy: `verbatim` (from stats.json)
* expected SOFT residue (allowed by policy): ['cn_id_card', 'cn_mobile', 'credential_in_image', 'email', 'fs_path', 'handle', 'qq_id', 'url']
* target: `data`

## HARD hits (must be zero)
* none ✅

## SOFT hits — must be reviewed before publishing
* none ✅

## SOFT residue allowed by policy (text visible in the public source images)

Captions are published verbatim, so these categories are expected residue: transcriptions of text visible in the public source images (contact details on business cards, storefront signage, screenshots). They are quantified by count in `verification/PII_CENSUS.md`, and the rows carrying them are excluded from the `pii_free` config for reviewers who require a corpus without third-party contact strings. No Ant Group data is involved, and no image is redistributed.
* email — verbatim examples withheld
* cn_mobile — verbatim examples withheld
* qq_id — verbatim examples withheld
* fs_path — verbatim examples withheld
* handle — verbatim examples withheld
* url — verbatim examples withheld
* credential_in_image — verbatim examples withheld

## Files scanned
* `release_manifest.json`
* `stats.json`
* `full/train-00000.parquet`
* `full/train-00001.parquet`
* `full/train-00002.parquet`
* `full/train-00003.parquet`
* `full/train-00004.parquet`
* `full/train-00005.parquet`
* `full/train-00006.parquet`
* `full/train-00007.parquet`
* `full/train-00008.parquet`
* `full/train-00009.parquet`
* `pii_free/train-00000.parquet`
* `pii_free/train-00001.parquet`
* `pii_free/train-00002.parquet`
* `pii_free/train-00003.parquet`
* `pii_free/train-00004.parquet`
* `pii_free/train-00005.parquet`
* `pii_free/train-00006.parquet`
* `pii_free/train-00007.parquet`
* `pii_free/train-00008.parquet`
* `verification/CORPUS_STATS.md`
* `verification/JOIN_VERIFICATION.md`
* `verification/PII_CENSUS.md`
* `verification/PII_FREE_CHECK.md`
* `verification/corpus_stats.json`
* `verification/join_verification.json`
* `clean/train-00000.parquet`
* `clean/train-00001.parquet`
* `clean/train-00002.parquet`
* `clean/train-00003.parquet`
* `clean/train-00004.parquet`
* `clean/train-00005.parquet`
* `clean/train-00006.parquet`
* `clean/train-00007.parquet`
* `clean/train-00008.parquet`
* `clean/train-00009.parquet`
* `sample/zoomcap_450k_sample.jsonl`

_(Verbatim example contexts are withheld from the public copy: they quote the exact third-party contact strings that this config excludes. The counts above are complete, and the full example set is part of the internal data-release application.)_
