# Corpus statistics — ZoomCap-450K (recomputed from the published files)

Entity counts are regex proxies; see `release/compute_corpus_stats.py`.

| split | rows | unique images | avg chars | avg words | avg sents | median chars | p99 chars | max chars | avg entities (caps) | avg entities (bold/quoted) |
|---|---|---|---|---|---|---|---|---|---|---|
| `full` | 454,963 | 440,238 | 4228.6 | 648.3 | 31.8 | 3932 | 10117 | 58722 | 3.2 | 34.2 |
| `clean` | 451,276 | 436,642 | 3963.3 | 604.6 | 28.9 | 3922 | 6581 | 29215 | 3.2 | 30.9 |
| `pii_free` | 447,285 | 432,755 | 3966.0 | 605.2 | 29.0 | 3926 | 6581 | 29215 | 3.2 | 30.9 |

```json
{
  "full": {
    "rows": 454963,
    "unique_image_keys": 440238,
    "rows_per_source": {
      "laion_filter_image": 352942,
      "share4v_image": 102021
    },
    "caption_chars": {
      "count": 454963,
      "mean": 4228.6,
      "median": 3932,
      "p01": 1982,
      "p99": 10117,
      "min": 8,
      "max": 58722
    },
    "caption_words": {
      "count": 454963,
      "mean": 648.3,
      "median": 600,
      "p01": 300,
      "p99": 1606,
      "min": 2,
      "max": 8636
    },
    "caption_sentences": {
      "count": 454963,
      "mean": 31.8,
      "median": 28,
      "p01": 13,
      "p99": 92,
      "min": 1,
      "max": 1759
    },
    "entity_proxy_capitalised_forms": {
      "count": 454963,
      "mean": 3.2,
      "median": 2,
      "p01": 0,
      "p99": 14,
      "min": 0,
      "max": 154
    },
    "entity_proxy_bold_or_quoted": {
      "count": 454963,
      "mean": 34.2,
      "median": 29,
      "p01": 10,
      "p99": 100,
      "min": 0,
      "max": 1877
    },
    "chars_per_word": 6.52,
    "words_per_sentence": 20.4
  },
  "clean": {
    "rows": 451276,
    "unique_image_keys": 436642,
    "rows_per_source": {
      "laion_filter_image": 350344,
      "share4v_image": 100932
    },
    "caption_chars": {
      "count": 451276,
      "mean": 3963.3,
      "median": 3922,
      "p01": 1979,
      "p99": 6581,
      "min": 208,
      "max": 29215
    },
    "caption_words": {
      "count": 451276,
      "mean": 604.6,
      "median": 599,
      "p01": 300,
      "p99": 1018,
      "min": 28,
      "max": 5147
    },
    "caption_sentences": {
      "count": 451276,
      "mean": 28.9,
      "median": 28,
      "p01": 13,
      "p99": 52,
      "min": 1,
      "max": 527
    },
    "entity_proxy_capitalised_forms": {
      "count": 451276,
      "mean": 3.2,
      "median": 2,
      "p01": 0,
      "p99": 14,
      "min": 0,
      "max": 96
    },
    "entity_proxy_bold_or_quoted": {
      "count": 451276,
      "mean": 30.9,
      "median": 29,
      "p01": 10,
      "p99": 66,
      "min": 0,
      "max": 1045
    },
    "chars_per_word": 6.55,
    "words_per_sentence": 20.9
  },
  "pii_free": {
    "rows": 447285,
    "unique_image_keys": 432755,
    "rows_per_source": {
      "laion_filter_image": 346618,
      "share4v_image": 100667
    },
    "caption_chars": {
      "count": 447285,
      "mean": 3966.0,
      "median": 3926,
      "p01": 1978,
      "p99": 6581,
      "min": 208,
      "max": 29215
    },
    "caption_words": {
      "count": 447285,
      "mean": 605.2,
      "median": 599,
      "p01": 300,
      "p99": 1019,
      "min": 28,
      "max": 5147
    },
    "caption_sentences": {
      "count": 447285,
      "mean": 29.0,
      "median": 28,
      "p01": 13,
      "p99": 52,
      "min": 1,
      "max": 527
    },
    "entity_proxy_capitalised_forms": {
      "count": 447285,
      "mean": 3.2,
      "median": 2,
      "p01": 0,
      "p99": 14,
      "min": 0,
      "max": 96
    },
    "entity_proxy_bold_or_quoted": {
      "count": 447285,
      "mean": 30.9,
      "median": 29,
      "p01": 10,
      "p99": 66,
      "min": 0,
      "max": 1045
    },
    "chars_per_word": 6.55,
    "words_per_sentence": 20.9
  }
}
```
