# PII census — ZoomCap-450K

* caption text policy: **verbatim** — captions are published byte-identical to the internal corpus; only the `images` path is rewritten. Sensitive rows are handled by exclusion (config `pii_free`), never by editing text.
* rows counted: 454,963

These strings are text visible inside the public source images (business cards, storefront signage, screenshots, classified ads). They are also what OCR-heavy evaluation rewards, so they are measured here rather than rewritten in place.

| category | occurrences | rows | share of rows | chars removed if masked | row flag |
| --- | --- | --- | --- | --- | --- |
| `handle` | 3,943 | 1,986 | 0.437% | 19,166 | `pii_contact` |
| `email` | 2,705 | 1,978 | 0.435% | 39,811 | `pii_contact` |
| `fs_path` | 136 | 95 | 0.021% | 2,045 | `pii_contact` |
| `cn_mobile` | 80 | 66 | 0.015% | 80 | `pii_identifier` |
| `credential_value` | 18 | 10 | 0.002% | 3 | `credential_in_image` |
| `qq_id` | 2 | 2 | 0.000% | 5 | `pii_identifier` |

## Config effect (row counts)

| config | rows | rule |
| --- | --- | --- |
| `full` | 454,963 | every caption, verbatim; row and character counts identical to the corpus the paper reports |
| `clean` | 451,276 | full minus rows with a degenerate-output QC flag |
| `pii_free` | 447,285 | clean minus rows whose image shows a third-party identifier or credential (row-level exclusion, no text edit) |

## QC / sensitivity flags

| flag | rows |
| --- | --- |
| `pii_contact` | 3,954 |
| `too_long` | 3,510 |
| `repetition_line` | 3,274 |
| `repetition_word` | 2,401 |
| `pii_identifier` | 67 |
| `credential_in_image` | 10 |
| `too_short` | 4 |

_(Verbatim example contexts are withheld from the public copy: they quote the exact third-party contact strings that this config excludes. The counts above are complete, and the full example set is part of the internal data-release application.)_
