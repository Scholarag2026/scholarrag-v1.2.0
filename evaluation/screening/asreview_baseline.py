"""ASReview LAB simulation baseline for the screening corpora (evaluation E1).

Interpreter: ``evaluation/.venv/Scripts/python`` (stdlib plus the evaluation requirements). The
ASReview command line is run from its own pinned venv, passed with ``--asreview-exe``; see
``asreview/README.md``.

For each dataset the corpus is exported to a CSV that holds exactly the records run A screened
(after the duplicate rule), ``asreview simulate`` runs with the default model, one relevant and
one irrelevant prior record and a fixed seed, and the labelling order is read back from the
project file. Reading effort is reported as records read and its share of N.

CLI::

    python asreview_baseline.py --dataset Smid_2020 --seeds 1 --asreview-exe PATH --data-dir PATH
    python asreview_baseline.py --input-check DIR1 DIR2 --dataset Smid_2020 --data-dir PATH
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import corpus_basis  # noqa: E402

from common import now_iso, read_json, read_jsonl, write_json  # noqa: E402

BASIS_DIR: Path = corpus_basis.BASIS_DIR
RESULTS_DIR: Path = HERE / "results" / "v3"
OUT_DIR: Path = HERE / "results" / "v3" / "asreview"

STOP_RULE_K: int = 100
STOP_RULE: dict[str, Any] = {"rule": "consecutive_irrelevant", "k": STOP_RULE_K}
SEEDS: tuple[int, ...] = tuple(range(1, 16))
DATASETS = ("Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017")

# Flags of ``asreview simulate`` for the pinned version (see ``asreview simulate --help``):
# one relevant and one irrelevant prior record, prior seed and model seed set per run, and the
# run ends when every relevant record has been found. ``{seed}`` is filled in by ``simulate``.
SIMULATE_ARGS: tuple[str, ...] = (
    "--n-prior-included",
    "1",
    "--n-prior-excluded",
    "1",
    "--prior-seed",
    "{seed}",
    "--seed",
    "{seed}",
)

# What the Smid_2020 export must reproduce.
INPUT_EXPECTED: dict[str, dict[str, int]] = {
    "Smid_2020": {"rows": 2627, "positives": 27, "empty_abstract": 640, "empty_title": 33}
}


# --------------------------------------------------------------------------------------
# Metrics on a labelling order
# --------------------------------------------------------------------------------------


def found_within(labels: Sequence[int], budget: int) -> int:
    """Relevant records among the first *budget* records read."""
    return int(sum(labels[: max(budget, 0)]))


def records_to_find(labels: Sequence[int], target: int) -> int | None:
    """Records read when the *target*-th relevant record appears; None when it never does."""
    if target <= 0:
        return 0
    found = 0
    for i, lab in enumerate(labels, start=1):
        found += lab
        if found >= target:
            return i
    return None


def wss_at_recall(labels: Sequence[int], n_total: int, n_pos: int, level: float) -> float | None:
    """Work saved over sampling at *level* recall; None when the recall target is not reached."""
    target = math.ceil(level * n_pos - 1e-9)
    read = records_to_find(labels, target)
    if read is None or n_total <= 0:
        return None
    return (n_total - read) / n_total - (1 - level)


def stop_after_consecutive_irrelevant(
    labels: Sequence[int], k: int, n_total: int, n_pos: int
) -> tuple[int, int]:
    """Apply the stopping rule to the order; return (records read, relevant found).

    The reader stops after *k* irrelevant records in a row (priors count as read). When the
    order ends with every positive found before such a run, the reader would read on for the
    rest of the run, so the records read are ``min(n_total, len(labels) + k - trailing)``.
    """
    run = 0
    found = 0
    for i, lab in enumerate(labels, start=1):
        if lab:
            found += 1
            run = 0
        else:
            run += 1
            if run >= k:
                return i, found
    if found >= n_pos:
        return min(n_total, len(labels) + k - run), found
    raise ValueError("order truncated before the stopping rule")


def _ratio(num: int | float | None, den: int | float) -> float | None:
    if num is None or not den:
        return None
    return num / den


def seed_metrics(
    labels: Sequence[int],
    n_total: int,
    n_pos: int,
    screener: Mapping[str, tuple[int, int]],
) -> dict[str, Any]:
    """Metrics of one seed; ``screener`` maps a run name to the screener's (budget, found)."""
    out: dict[str, Any] = {}
    for name, (budget, found) in screener.items():
        read = records_to_find(labels, found)
        got = found_within(labels, budget)
        out[name] = {
            "found_at_screener_budget": got,
            "recall_at_screener_budget": _ratio(got, n_pos),
            "records_to_screener_found": read,
            "share_to_screener_found": _ratio(read, n_total),
        }
    out["wss_at_95"] = wss_at_recall(labels, n_total, n_pos, 0.95)
    out["wss_at_100"] = wss_at_recall(labels, n_total, n_pos, 1.0)
    try:
        stop_records, stop_found = stop_after_consecutive_irrelevant(
            labels, STOP_RULE_K, n_total, n_pos
        )
    except ValueError:
        out["stop_rule_records"] = out["stop_rule_found"] = out["stop_rule_recall"] = None
    else:
        out["stop_rule_records"] = stop_records
        out["stop_rule_found"] = stop_found
        out["stop_rule_recall"] = _ratio(stop_found, n_pos)
    return out


def _flatten(d: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in d.items():
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def aggregate(per_seed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mean, min, max and the count of seeds where the value is None, for every numeric key."""
    rows = [_flatten(r) for r in per_seed]
    keys: list[str] = []
    for r in rows:
        for key in r:
            if key not in keys:
                keys.append(key)
    out: dict[str, Any] = {}
    for key in keys:
        vals = [r.get(key) for r in rows]
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not nums and any(v is not None for v in vals):
            continue
        out[key] = {
            "mean": sum(nums) / len(nums) if nums else None,
            "min": min(nums) if nums else None,
            "max": max(nums) if nums else None,
            "n_not_reached": sum(v is None for v in vals),
        }
    return out


# --------------------------------------------------------------------------------------
# Corpus export and project reading
# --------------------------------------------------------------------------------------


def _rid(value: Any) -> int:
    return int(float(value))


def _flag(value: Any) -> int:
    if value is None or str(value).strip() in ("", "None"):
        return 0
    return int(float(value))


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def screened_rows(
    dataset: str, results_dir: Path, run: str = "A", basis_dir: Path = BASIS_DIR
) -> list[dict[str, Any]]:
    """Rows of *run* that were screened, after the duplicate rule."""
    dup = corpus_basis.load_duplicate_ids(dataset, basis_dir)
    rows = read_jsonl(Path(results_dir) / f"{dataset}_run{run}.jsonl")
    for r in rows:
        r["record_id"] = _rid(r["record_id"])
    rows = corpus_basis.apply_basis(rows, dup)
    return [r for r in rows if r.get("predicted") is not None]


def export_corpus(
    dataset: str,
    data_dir: Path,
    results_dir: Path,
    out_csv: Path,
    basis_dir: Path = BASIS_DIR,
) -> list[int]:
    """Write the ASReview input; return the record ids in row order (sorted by record_id)."""
    ids = sorted({r["record_id"] for r in screened_rows(dataset, results_dir, "A", basis_dir)})
    keep = set(ids)
    recs: dict[int, Mapping[str, Any]] = {}
    for rec in read_jsonl(Path(data_dir) / f"{dataset}.jsonl"):
        rid = _rid(rec["record_id"])
        if rid in keep:
            recs[rid] = rec
    missing = keep - set(recs)
    if missing:
        raise ValueError(f"{dataset}: {len(missing)} screened records are not in the data file")
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["title", "abstract", "label_included"])
        for rid in ids:
            rec = recs[rid]
            w.writerow(
                [_text(rec.get("title")), _text(rec.get("abstract")), _flag(rec["label_included"])]
            )
    return ids


def read_label_order(project: Path, row_ids: Sequence[int]) -> list[tuple[int, int]]:
    """Labelling order of a finished project as (our record id, label), priors first."""
    with zipfile.ZipFile(project) as z:
        members = [m for m in z.namelist() if m.endswith("results.db")]
        if len(members) != 1:
            raise ValueError(f"expected one results.db in {project}, found {members}")
        data = z.read(members[0])
    with tempfile.TemporaryDirectory(prefix="asreview-db-") as tmp:
        db = Path(tmp) / "results.db"
        db.write_bytes(data)
        con = sqlite3.connect(db)
        try:
            rows = con.execute("select record_id, label from results order by rowid").fetchall()
        finally:
            con.close()
    out: list[tuple[int, int]] = []
    for idx, label in rows:
        if label is None:
            continue  # a record in the pool that was never labelled
        if not 0 <= idx < len(row_ids):
            raise ValueError("row index outside the export")
        out.append((row_ids[idx], int(label)))
    return out


# --------------------------------------------------------------------------------------
# Running ASReview
# --------------------------------------------------------------------------------------


def simulate(asreview_exe: Path, csv_path: Path, project: Path, seed: int) -> list[str]:
    """Run one simulation and return the argv; raise when ASReview fails."""
    argv = [
        str(asreview_exe),
        "simulate",
        str(csv_path),
        "--output",
        str(project),
        *(a.format(seed=seed) for a in SIMULATE_ARGS),
    ]
    Path(project).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"asreview simulate failed (exit {proc.returncode}): {proc.stderr[-2000:]}"
        )
    return argv


def _is_abs(arg: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", arg)) or arg.startswith(("/", "\\\\"))


def _under(path: str, base: Path) -> str | None:
    p = os.path.abspath(path)
    b = os.path.abspath(base)
    if os.path.normcase(p) == os.path.normcase(b):
        return ""
    if os.path.normcase(p).startswith(os.path.normcase(b) + os.sep):
        return Path(p[len(b) + 1 :]).as_posix()
    return None


def portable_argv(argv: Sequence[str], work_dir: Path, out_dir: Path) -> list[str]:
    """Replace the executable and local paths so a recorded argv carries no machine path."""
    result = ["asreview"]
    for arg in list(argv)[1:]:
        if not _is_abs(arg):
            result.append(arg)
            continue
        for tag, base in (("<work-dir>", work_dir), ("<out-dir>", out_dir)):
            rel = _under(arg, base)
            if rel is not None:
                result.append(f"{tag}/{rel}" if rel else tag)
                break
        else:
            raise ValueError(f"absolute path outside the work and output directories: {arg}")
    return result


# --------------------------------------------------------------------------------------
# Screener operating point and the input check
# --------------------------------------------------------------------------------------


def screener_points(
    dataset: str, results_dir: Path, basis_dir: Path = BASIS_DIR
) -> dict[str, tuple[int, int]]:
    """Screener (budget, found) for run A and run B on the same basis."""
    out: dict[str, tuple[int, int]] = {}
    for run in ("A", "B"):
        rows = screened_rows(dataset, results_dir, run, basis_dir)
        for r in rows:
            r["label_included"] = _flag(r.get("label_included"))
            r["predicted"] = _flag(r.get("predicted"))
        op = corpus_basis.operating_point(rows)
        out[run] = (op["n_screened_in"], op["n_final_kept"])
    return out


def _order_file(directory: Path, dataset: str, seed: int) -> Path:
    return Path(directory) / f"{dataset}_seed{seed:02d}.order.json"


def input_check(
    dir1: Path,
    dir2: Path,
    dataset: str,
    data_dir: Path,
    results_dir: Path,
    basis_dir: Path = BASIS_DIR,
) -> dict[str, tuple[bool, str]]:
    """The export, labelling-order, metrics and repeat checks as (passed, observed value)."""
    verdict: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory(prefix="asreview-input-") as tmp:
        csv_path = Path(tmp) / f"{dataset}.csv"
        ids = export_corpus(dataset, data_dir, results_dir, csv_path, basis_dir)
        with csv_path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    run_a = {r["record_id"] for r in screened_rows(dataset, results_dir, "A", basis_dir)}
    n_pos = sum(int(r["label_included"]) for r in rows)
    empty_abs = sum(not r["abstract"] for r in rows)
    empty_title = sum(not r["title"] for r in rows)
    observed = (
        f"rows={len(rows)} positives={n_pos} empty_abstract={empty_abs} "
        f"empty_title={empty_title} ids_match_run_a={set(ids) == run_a}"
    )
    ok = set(ids) == run_a
    expected = INPUT_EXPECTED.get(dataset)
    if expected is not None:
        ok = ok and (
            expected["rows"] == len(rows)
            and expected["positives"] == n_pos
            and expected["empty_abstract"] == empty_abs
            and expected["empty_title"] == empty_title
        )
    verdict["export"] = (ok, observed)

    order1 = read_json(_order_file(dir1, dataset, 1))
    order2 = read_json(_order_file(dir2, dataset, 1))
    gold = {}
    for rec in read_jsonl(Path(data_dir) / f"{dataset}.jsonl"):
        gold[_rid(rec["record_id"])] = _flag(rec.get("label_included"))
    rid, lab = order1["record_ids"], order1["labels"]
    mismatches = sum(gold.get(r) != label for r, label in zip(rid, lab, strict=False))
    repeats = len(rid) - len(set(rid))
    priors_ok = len(lab) >= 2 and sorted(lab[:2]) == [0, 1]
    all_pos = {r for r in rid if gold.get(r) == 1} == {r for r in ids if gold.get(r) == 1}
    p4 = mismatches == 0 and repeats == 0 and priors_ok and all_pos and len(rid) == len(lab)
    verdict["order"] = (
        p4,
        f"label_mismatches={mismatches} repeats={repeats} priors_one_relevant_one_irrelevant="
        f"{priors_ok} all_positives_present={all_pos} records={len(rid)}",
    )

    pts = screener_points(dataset, results_dir, basis_dir)
    m = seed_metrics(lab, len(ids), n_pos, pts)
    none_keys = [k for k, v in _flatten(m).items() if v is None]
    verdict["metrics"] = (
        not none_keys,
        "all keys have a value" if not none_keys else f"None: {none_keys}",
    )

    same = order1 == order2
    verdict["repeat"] = (same, "identical order" if same else "orders differ")
    return verdict


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _capture(argv: Sequence[str]) -> str:
    proc = subprocess.run(list(argv), capture_output=True, text=True, encoding="utf-8")
    return (proc.stdout or proc.stderr).strip()


def _parse_seeds(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def run_dataset(
    dataset: str,
    seeds: Sequence[int],
    asreview_exe: Path,
    data_dir: Path,
    results_dir: Path,
    out_dir: Path,
    work_dir: Path,
    meta: dict[str, Any],
) -> None:
    csv_path = Path(work_dir) / f"{dataset}.csv"
    ids = export_corpus(dataset, data_dir, results_dir, csv_path)
    meta["data_sha256"][csv_path.name] = _sha256(csv_path)
    gold = {
        _rid(r["record_id"]): _flag(r.get("label_included"))
        for r in read_jsonl(Path(data_dir) / f"{dataset}.jsonl")
    }
    n_total, n_pos = len(ids), sum(gold[i] for i in ids)
    points = screener_points(dataset, results_dir)
    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        project = Path(work_dir) / f"{dataset}_seed{seed:02d}.asreview"
        t0 = time.monotonic()
        argv = simulate(asreview_exe, csv_path, project, seed)
        wall = round(time.monotonic() - t0, 1)
        order = read_label_order(project, ids)
        write_json(
            _order_file(out_dir, dataset, seed),
            {"record_ids": [r for r, _ in order], "labels": [lab for _, lab in order]},
        )
        per_seed.append(
            {"seed": seed, **seed_metrics([lab for _, lab in order], n_total, n_pos, points)}
        )
        meta["runs"].setdefault(dataset, {})[str(seed)] = {
            "argv": portable_argv(argv, work_dir, out_dir),
            "wall_seconds": wall,
        }
    write_json(
        Path(out_dir) / f"{dataset}_asreview.json",
        {
            "dataset": dataset,
            "n_total": n_total,
            "n_pos": n_pos,
            "screener": {k: {"budget": b, "found": f} for k, (b, f) in points.items()},
            "per_seed": per_seed,
            "aggregate": aggregate([{k: v for k, v in s.items() if k != "seed"} for s in per_seed]),
            "stop_rule": STOP_RULE,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="all")
    ap.add_argument("--seeds", default="1-15")
    ap.add_argument("--asreview-exe", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=HERE / "data")
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--work-dir", type=Path, default=None)
    ap.add_argument("--input-check", nargs=2, type=Path, metavar=("DIR1", "DIR2"))
    args = ap.parse_args(argv)

    if args.input_check:
        dir1, dir2 = args.input_check
        verdict = input_check(dir1, dir2, args.dataset, args.data_dir, args.results_dir)
        lines = [
            f"{k}: {'PASS' if ok else 'FAIL'} ({obs})" for k, (ok, obs) in sorted(verdict.items())
        ]
        Path(dir1).mkdir(parents=True, exist_ok=True)
        (Path(dir1) / "verdict.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0 if all(ok for ok, _ in verdict.values()) else 1

    if args.asreview_exe is None:
        ap.error("--asreview-exe is required for a simulation run")
    datasets = DATASETS if args.dataset == "all" else (args.dataset,)
    seeds = _parse_seeds(args.seeds)
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="asreview-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = Path(args.asreview_exe)
    meta_path = out_dir / "asreview_meta.json"
    meta: dict[str, Any] = read_json(meta_path, {"runs": {}, "data_sha256": {}}) or {}
    meta.setdefault("runs", {})
    meta.setdefault("data_sha256", {})
    meta.update(
        {
            "asreview_version": _capture([str(exe), "--version"]),
            "python_version": _capture([str(exe.parent / "python.exe"), "--version"])
            if (exe.parent / "python.exe").exists()
            else sys.version.split()[0],
            "pip_freeze": _capture(
                [str(exe.parent / "python.exe"), "-m", "pip", "freeze"]
            ).splitlines()
            if (exe.parent / "python.exe").exists()
            else [],
            "seeds": seeds,
            "date": now_iso(),
        }
    )
    for ds in datasets:
        run_dataset(ds, seeds, exe, args.data_dir, args.results_dir, out_dir, work_dir, meta)
    write_json(meta_path, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
