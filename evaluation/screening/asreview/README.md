# ASReview LAB baseline for the screening corpora

`../asreview_baseline.py` runs the ASReview LAB simulation on the records the screener scored
and reports how many records a reader working in ASReview's order has to read to reach the
screener's recall. The pinned version is `asreview==3.0.8` with the default model (`elas_u4`),
installed in its own virtual environment so that nothing is installed globally.

## Install

```bash
python -m venv evaluation/screening/asreview/.venv
evaluation/screening/asreview/.venv/Scripts/python.exe -m pip install -r evaluation/screening/asreview/requirements.txt
evaluation/screening/asreview/.venv/Scripts/python.exe -m pip check
evaluation/screening/asreview/.venv/Scripts/asreview.exe --version   # asreview 3.0.8
```

`requirements.txt` is the `pip freeze` of that environment. The `.venv` directory is ignored by
git.

## Run

Run the harness with the evaluation interpreter and pass the ASReview executable:

```bash
cd evaluation/screening
python asreview_baseline.py --dataset all --seeds 1-15 \
  --asreview-exe asreview/.venv/Scripts/asreview.exe --data-dir path/to/data
```

`--dataset` takes one corpus name or `all` (Nagtegaal_2019, Smid_2020, van_de_Schoot_2017).
`--seeds` takes `1-15` or a single seed. Results go to `results/v3/asreview/`:
`<dataset>_seedNN.order.json` (record ids and labels in reading order),
`<dataset>_asreview.json` (per-seed metrics and their aggregate) and `asreview_meta.json`
(versions, `pip freeze`, the argument list of every run with local paths replaced, the SHA-256
of each exported CSV, date and wall seconds).

## What is simulated

- Corpus: exactly the records run A screened, after the duplicate rule (`corpus_basis.py`), so
  the screener, the TF-IDF baseline and ASReview share one N. Each record has a title, an
  abstract (empty when the source has none) and its final-inclusion label.
- Priors: one relevant and one irrelevant record, drawn with the prior seed. The prior seed and
  the model seed both equal the run seed. Seeds are 1 to 15.
- The simulation runs until every relevant record is found, so the whole order is available.
- Stopping rule, fixed before any run: a reader stops after 100 consecutive irrelevant records,
  and the priors count as read. If the order ends with every relevant record found before such a
  run, the reader would read on for the rest of the run, which the harness counts
  (`min(N, length + 100 - trailing irrelevant)`).
- Reading effort is reported as records read and its share of N. A seed that never reaches a
  target gives `null` for that value, and the aggregate counts these in `n_not_reached`.

## Input check

One seed on Smid_2020 is checked against the export: the export has 2,627 rows, 27
positives, 640 empty abstracts and 33 empty titles; the labelling order agrees with
`label_included` for every record; rerunning seed 1 gives the identical order.

```bash
python asreview_baseline.py --input-check DIR1 DIR2 --dataset Smid_2020 --data-dir path/to/data
```

writes `DIR1/verdict.txt` and exits 1 on any failed criterion.
