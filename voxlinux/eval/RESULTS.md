# VoxLinux ASR benchmark — measured results

Date: 2026-10-20. Harness: `scripts/bench_models.py` (loads models via
`voxapp.engines.build_engine`, so VAD chunking + audio preprocessing are
included). Numbers below are **our own measurements**, not vendor numbers.

## Dataset

- **Source:** `bond005/sberdevices_golos_10h_crowd` on Hugging Face
  (validation split), derived from the SberDevices Golos corpus
  (16 kHz, Russian, crowd-sourced reading speech). Audio is embedded in
  the parquet as 16-bit mono PCM WAV, so no transcoding was needed.
- **Licence:** SberDevices Golos licence ("public license with attribution
  and conditions reserved") — see
  https://github.com/sberdevices/golos/blob/master/license/en_us.pdf.
  Attribution: Karpov et al., "Golos: Russian Dataset for Speech Research",
  arXiv:2106.10161.
- **Composition:** 27 utterances total:
  - 25 short crowd voice commands taken from the Golos validation split
    (indices chosen to span 2.0–11.6 s durations);
  - 1 synthesised sentence (`sample_ru_tts.wav`) with a hand-written
    reference: «Привет! Сегодня мы собираемся обсудить новый релиз. Мне
    нужно подготовить пять серверов и два отчёта к завтрашнему утру.»;
  - 1 literary excerpt (`sample_ru.wav`) whose reference was reconstructed
    from the canonical text of Pushkin's "Руслан и Людмила" dedication +
    opening line, matched against the model output («Ничьих не требуя
    похвал… У лукоморья дуб зелёный.»).
- **Total duration:** 128.34 s (2.14 min), 16 kHz mono.
- **Character of the speech:** read speech (crowd readers + one TTS clip
  + one poem recitation). It is **not** representative of free-form
  dictation: utterances are short command-style phrases, mostly clean,
  with no disfluencies. Treat the absolute WERs as an optimistic lower
  bound; the relative ranking between models is the useful signal.

Files: `eval/data/refs.json` (filename -> reference text) and
`eval/data/audio/*.wav`.

## Measured table

| model | raw WER % | norm WER % | raw CER % | norm CER % | RTF | mean decode latency (s) |
|---|---:|---:|---:|---:|---:|---:|
| gigaam-v3-e2e-rnnt-punct | 47.31 | 5.06 | 17.51 | 3.66 | 0.054 | 0.259 |
| gigaam-v3-e2e-ctc-punct | 46.71 | 8.23 | 18.58 | 5.31 | 0.048 | 0.227 |
| gigaam-v3 | 10.18 | 2.53 | 2.04 | 0.47 | 0.053 | 0.254 |

Micro-averaged (sum of edit distances / sum of reference lengths).
RTF = total decode time / total audio duration.

## Normalisation rule

- **Raw WER/CER:** Levenshtein on whitespace-tokenised strings exactly as
  emitted by the engine and the reference (case- and punctuation-
  preserving). No lowercasing, no punctuation removal, no number
  conversion.
- **Normalised WER/CER:** both reference and hypothesis are transformed by
  (1) lowercasing; (2) replacing every punctuation character with a space
  (stripping punctuation); (3) collapsing repeated whitespace; (4)
  converting spoken number-words to digits via the project's own
  `voxapp.itn.apply_itn`, so that "пять" and "5" compare equal ("treat
  digits/words as equivalent"); then Levenshtein on words (WER) /
  characters (CER).

The vendor's published table marks the e2e (`*-punct`) models with an
asterisk and states those numbers are computed "with post-processing
applied (removing punctuation and capitalization, replacing numerals,
etc.)"; the plain models are unmarked. Hence the two families are not
directly comparable on the vendor's single WER column — which is exactly
why both raw and normalised columns are reported here.

## Comparison with vendor numbers

Vendor (salute-developers/GigaAM/evaluation.md), average over 10 test sets:
V3 CTC (plain) 9.1% WER; V3 RNN-T (plain) 8.3%; e2e CTC* 12.0%;
e2e RNN-T* 11.2%. Golos Crowd subset: V3 CTC 2.8%, e2e RNN-T 9.1%.

Our measurements follow the same ordering — plain models are more accurate
than e2e ones, and RNN-T beats CTC within the punctuation-aware family
(5.06% vs 8.23%) — but the absolute WERs are lower because the eval set
is short, clean, read speech. Our legacy CTC normalised WER (2.53%) is
close to the vendor's Golos Crowd figure (2.8%), which supports that the
harness is measuring the same thing the vendor measures.

## Conclusion

- **Default for dictation:** keep `gigaam-v3-e2e-rnnt-punct` as the
  default. It is the most accurate of the punctuation-aware models we
  measured (normalised WER 5.06% vs 8.23% for the CTC punct variant) at
  essentially the same speed (RTF 0.054 vs 0.048, mean latency 0.259 s vs
  0.227 s per utterance), and it delivers native punctuation/casing that
  the heuristic pipeline cannot reliably reproduce.
- **Accuracy cost of native punctuation:** +2.53 percentage points of
  normalised WER versus the best plain model we have installed
  (`gigaam-v3`, 2.53% vs 5.06%), with no meaningful latency penalty
  (RTF 0.053 vs 0.054). If a user prioritises raw transcription accuracy
  over punctuation (e.g. command entry), `gigaam-v3` (legacy CTC) is the
  better choice; for prose dictation the punctuation-aware default wins
  on usability.
- **Versus vendor numbers:** our relative ranking matches the vendor's
  table; our absolute WERs are lower because the eval set is an easy,
  short-utterance read-speech subset rather than the vendor's 10-set
  average. The vendor's claim that e2e models are less accurate than
  plain ones (11.2 vs 9.1 average) is reproduced by our own measurement
  (5.06 vs 2.53 on this set).

## Limitations

- 27 utterances, ~2.1 minutes of audio: small; WER has high variance.
- Read speech (Golos crowd commands + TTS + one poem), not free-form
  dictation; no disfluencies, hesitations, or domain-specific vocabulary.
- Only 3 of the 4 catalogued models are installed locally (the plain
  RNN-T variant `gigaam-v3-rnnt-plain` is missing), so the plain-model
  comparison uses the CTC variant.
- Raw WER for punctuation-aware models is dominated by case/punctuation
  mismatches against the lowercase, unpunctuated references; the
  normalised column is the fair comparison.

## Reproduce

### Re-fetch the dataset

The 25 Golos clips are not stored in git. Their provenance (source parquet,
validation split, row index, PCM SHA-256) is recorded in
`eval/data/manifest.json`. To rebuild the audio directory from scratch:

```sh
# download the source parquet(s) into the cache and extract the rows
./.venv/bin/python eval/fetch_dataset.py

# verify the local files against the manifest (offline, no download)
./.venv/bin/python eval/fetch_dataset.py --check
```

`--cache-dir DIR` overrides the default cache location (`/tmp/opencode/eval-cache`).
`--audio-dir DIR` overrides the output directory (default `eval/data/audio`).

### Re-run the benchmark

```sh
./.venv/bin/python scripts/bench_models.py eval/data --model <id> ...
```

Examples:

```sh
./.venv/bin/python scripts/bench_models.py eval/data
./.venv/bin/python scripts/bench_models.py eval/data --model gigaam-v3-e2e-rnnt-punct --out /tmp/opencode/bench.md
```

### Licence and attribution

Dataset: `bond005/sberdevices_golos_10h_crowd` on Hugging Face, validation
split, derived from the SberDevices Golos corpus (16 kHz, Russian,
crowd-sourced reading speech). Licence: SberDevices Golos licence ("public
license with attribution and conditions reserved") — see
https://github.com/sberdevices/golos/blob/master/license/en_us.pdf.
Attribution: Karpov et al., "Golos: Russian Dataset for Speech Research",
arXiv:2106.10161.
