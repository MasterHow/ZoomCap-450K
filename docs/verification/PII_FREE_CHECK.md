# `pii_free` personal-information check — PASS

* rows re-scanned from the published parquet: 447,285
* pattern families re-run independently of the build flags: 7 (cn_id_card, cn_mobile, credential, email, fs_path, handle, qq_id)
* detections: 0

No third-party e-mail address, social handle, local filesystem path, mainland-China mobile number, national ID, QQ identifier or in-image credential is present in any row of this config.

Verbatim in-image text is retained in the `full` and `clean` configs by design (masking would corrupt OCR transcriptions and break reproduction of the paper's corpus statistics); see `verification/PII_CENSUS.md`.
