# Join verification — ZoomCap-450K ↔ ScaleCap-450k

## structure_full
```json
{
  "rows": 454963,
  "unique_keys": 440238,
  "shards": 10,
  "problems": {}
}
```

## structure_clean
```json
{
  "rows": 451276,
  "unique_keys": 436642,
  "shards": 10,
  "problems": {}
}
```

## structure_pii_free
```json
{
  "rows": 447285,
  "unique_keys": 432755,
  "shards": 9,
  "problems": {}
}
```

## stats_reconciliation
```json
{
  "expected": {
    "full": 454963,
    "clean": 451276,
    "pii_free": 447285
  },
  "observed": {
    "full": 454963,
    "clean": 451276,
    "pii_free": 447285
  },
  "match": true
}
```

## keys_emitted
```json
"zoomcap450k_image_keys.txt.gz (local, not published)"
```

> NOTE: upstream check could not reach the HF datasets-server (offline / restricted network). Re-run `--mode upstream` from a machine with network access before publishing.
