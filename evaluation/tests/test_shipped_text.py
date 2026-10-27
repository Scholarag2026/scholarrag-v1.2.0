"""Guard (D2): shipped evaluation files must not name the development model and must not
carry the earlier development-label tables or numbers.

Stdlib only. The model word comes from conftest so this file never spells it."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from conftest import DEV_MODEL_WORD, EVAL_ROOT

REPO_ROOT = EVAL_ROOT.parent
UNSHIPPED = ("claims/annotation", "screening/results/archive/fn_categorisation_earlier_run")
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", "data"}
SUFFIXES = {".py", ".md", ".json", ".jsonl", ".csv", ".tsv", ".txt", ".yml", ".yaml", ".toml"}


def _shipped_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for path in sorted(EVAL_ROOT.rglob("*")):
        rel = path.relative_to(EVAL_ROOT)
        parts = rel.parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        posix = rel.as_posix()
        if any(posix == u or posix.startswith(u + "/") for u in UNSHIPPED):
            continue
        if path.is_file() and path.suffix.lower() in SUFFIXES:
            out.append((f"evaluation/{posix}", path))
    return out


def _lines(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    yield from enumerate(text.splitlines(), start=1)


def test_no_shipped_evaluation_file_names_the_development_model():
    pattern = re.compile(rf"(?i)(?<![.\w]){DEV_MODEL_WORD}")
    hits = [
        f"{label}:{n}"
        for label, path in _shipped_files()
        for n, line in _lines(path)
        if pattern.search(line)
    ]
    assert hits == []


def test_no_shipped_evaluation_output_carries_the_earlier_label_tables_or_numbers():
    table_key = re.compile(r"\bTable E2-[dg]\b|\b(?:hss|real)_vs_annotation\b")
    number = re.compile(r"\b11\s*(?:/|of)\s*26\b|(?<![\d.])0\.423\d*")
    marker = re.compile(
        r"(?i)annotat|adjudicat|model-authored|development label|earlier label"
    )
    table_hits: list[str] = []
    number_hits: list[str] = []
    for label, path in _shipped_files():
        if label.startswith("evaluation/tests/"):
            continue
        for n, line in _lines(path):
            if table_key.search(line):
                table_hits.append(f"{label}:{n}")
            if number.search(line) and marker.search(line):
                number_hits.append(f"{label}:{n}")
    assert table_hits == []
    assert number_hits == []


def test_unshipped_dirs_match_the_release_exporter():
    exporter = REPO_ROOT / "softwarex publication" / "code" / "stage_and_zip.py"
    if not exporter.exists():
        pytest.skip("release exporter not present in this tree")
    spec = importlib.util.spec_from_file_location("d2_stage_and_zip", exporter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for d in UNSHIPPED:
        assert module.excluded(Path("evaluation") / d / "x.md") is True
    assert module.excluded(Path("evaluation/claims/label_sets.py")) is False
