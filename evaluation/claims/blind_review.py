"""Seeds, commitments and the leak audit for the blind labelling workbooks.

A blind workbook shows a labeller only what the whitelist below allows: the item text, the
cited source and empty answer columns. This module holds the pieces that every blind build
shares:

* the whitelist headers and sheet names (the rule is a whitelist, not a blacklist: a column
  or sheet that is not listed here does not ship);
* the round's random seeds, written once to a private file, and their salted commitments
  (``sha256("<seed>:<salt>")``) which are the only seed material a committed file may carry;
* ``audit_blind_workbook``, which opens a built file with openpyxl and the zip reader and
  reports one plain sentence per leak (tool output, item category, hidden content, file
  metadata, ordering by category).

Sources cells show ``display_source_text`` of the stored text; any check of a human_quote
against the source compares with ``common.quote_is_verbatim(quote,
display_source_text(stored))``.

It reads no run result and no annotation file. The audit takes only the workbook and, when
given, the key csv.

Interpreter: the evaluation venv's python (openpyxl), run from any directory::

    python claims/blind_review.py seeds --out PATH
    python claims/blind_review.py audit PATH --kind claims|screening [--key KEY]
    python claims/blind_review.py screening --screening-record F --expect-git REV:PATH ...
    python claims/blind_review.py manifest --items F... --cache-dir D... --screening-record F ...
    python claims/blind_review.py validate PATH --kind claims|screening [--screening-record F]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import secrets
import sys
import unicodedata
import zipfile
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import export_review_sheet as ex  # noqa: E402
import openpyxl  # noqa: E402
from openpyxl.styles import Alignment, Font  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

ORDER_CHECK_MIN_ROWS = 30
ORDER_CHANGE_FRACTION = 0.5

# The answer columns sit next to the claim (or the title) and are frozen with the id, so a
# labeller sees the text and the answer cells together. Every reader keys by header name.
BLIND_CLAIMS_HEADER = (
    "item_id", "claim", "human_verdict", "confidence", "human_quote", "human_note",
    "minutes_spent", "stored_text", "cited_title", "cited_doi", "cited_first_author_year",
)
BLIND_SCREENING_HEADER = (
    "record_id", "title", "human_decision", "human_criterion", "human_note", "abstract",
    "venue", "year",
)
SOURCES_HEADER = ("item_id", "part", "text")
BLIND_SOURCES_MAX_CHARS = 2_500
ATTESTATION_HEADER = ("question", "answer")
CLAIMS_SHEETS = ("Guide", "Claims", "Sources", "Attestation")
SCREENING_SHEETS = ("Guide", "Screening", "Attestation")
CLAIMS_ID_PREFIX = "BC-"
SCREENING_ID_PREFIX = "BS-"
CONFIDENCE_CHOICES = ("high", "medium", "low")
SCREENING_DECISIONS = ("include", "exclude", "unsure")
CRITERION_CHOICE_PATTERN = re.compile(r"^[IE]\d+$|^TOPIC$")
FREE_TEXT_COLUMNS = {
    "claims": {"claim", "cited_title"},
    "screening": {"title", "abstract", "venue"},
}

_CLAIMS_FORBIDDEN_EXTRA = (
    "Model_labels", "Provenance", "blindness", "verifier", "constructed", "construction",
    "over_specified", "wrong_paper", "paraphrase", "verbatim", "altered", "expected_label",
    "ScholarRAG",
)
_CLAIMS_FORBIDDEN = tuple(
    name for name in ex.review_header()
    if name not in BLIND_CLAIMS_HEADER and name != "set"
) + _CLAIMS_FORBIDDEN_EXTRA
_SCREENING_FORBIDDEN = (
    "needs_review", "not_established", "undecidable", "unanchored_exclude", "no_abstract",
    "second_pass", "stratum", "judge_demoted", "inclusion judge", "screener", "to_confirm",
    "openalex", "ScholarRAG",
)
_SCREENING_FORBIDDEN_CASE_SENSITIVE = ("INCLUDE", "EXCLUDE", "NEEDS_REVIEW")

_FORBIDDEN_PART_PATTERNS = (
    "xl/comments", "xl/threadedComments/", "xl/externalLinks/", "xl/vbaProject.bin",
    "xl/embeddings/", "customXml/",
)
_PROPERTY_NAMES = (
    "creator", "title", "subject", "description", "keywords", "category", "lastModifiedBy",
)
_SEED_MAX = 2**31 - 1


# --------------------------------------------------------------------------------------
# Seeds and commitments
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BlindSeeds:
    salt: str
    claims_id_seed: int
    claims_row_seeds: tuple[int, int, int]
    screening_sample_seed: int
    screening_id_seed: int
    screening_row_seeds: tuple[int, int, int]


def new_seeds() -> BlindSeeds:
    rng = random.SystemRandom()

    def one() -> int:
        return rng.randint(1, _SEED_MAX)

    return BlindSeeds(
        salt=secrets.token_hex(16),
        claims_id_seed=one(),
        claims_row_seeds=(one(), one(), one()),
        screening_sample_seed=one(),
        screening_id_seed=one(),
        screening_row_seeds=(one(), one(), one()),
    )


def write_seeds_file(path: Path, seeds: BlindSeeds) -> None:
    payload = {
        "salt": seeds.salt,
        "claims_id_seed": seeds.claims_id_seed,
        "claims_row_seeds": list(seeds.claims_row_seeds),
        "screening_sample_seed": seeds.screening_sample_seed,
        "screening_id_seed": seeds.screening_id_seed,
        "screening_row_seeds": list(seeds.screening_row_seeds),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:  # "x" raises FileExistsError
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def load_seeds(path: Path) -> BlindSeeds:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return BlindSeeds(
        salt=data["salt"],
        claims_id_seed=data["claims_id_seed"],
        claims_row_seeds=tuple(data["claims_row_seeds"]),  # type: ignore[arg-type]
        screening_sample_seed=data["screening_sample_seed"],
        screening_id_seed=data["screening_id_seed"],
        screening_row_seeds=tuple(data["screening_row_seeds"]),  # type: ignore[arg-type]
    )


def seed_commitment(seed: int, salt: str) -> str:
    return hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()


def blind_workbook_id(id_keys: Sequence[str], id_seed: int, salt: str) -> str:
    """Salted replacement for ``ex.compute_workbook_id``: the id cannot be brute-forced back
    to the id seed without the salt."""
    h = hashlib.sha256()
    h.update(f"{salt}:{id_seed}".encode())
    for key in id_keys:
        h.update(b"\x00" + str(key).encode("utf-8"))
    return h.hexdigest()[:16]


def derive_seed(base: int, salt: str, label: str) -> int:
    """A seed derived from ``base``, so one seed can serve several independent shuffles."""
    digest = hashlib.sha256(f"{base}:{salt}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % _SEED_MAX + 1


def id_seed(seeds: BlindSeeds, kind: Literal["claims", "screening"], copy: str) -> int:
    """Seed of the id order. Copies 1 to 3 share one."""
    if copy not in ("1", "2", "3"):
        raise ValueError(f"copy must be 1, 2 or 3, got {copy!r}")
    return seeds.claims_id_seed if kind == "claims" else seeds.screening_id_seed


def row_seed(seeds: BlindSeeds, kind: Literal["claims", "screening"], copy: str) -> int:
    if copy not in ("1", "2", "3"):
        raise ValueError(f"copy must be 1, 2 or 3, got {copy!r}")
    table = seeds.claims_row_seeds if kind == "claims" else seeds.screening_row_seeds
    return table[int(copy) - 1]


def shuffle_permutation(seed: int, n: int) -> list[int]:
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return idx


def _check_orders_differ(ids: int, rows: int, n: int) -> None:
    if ids == rows or (n >= 2 and shuffle_permutation(ids, n) == shuffle_permutation(rows, n)):
        raise ex.ExportError(
            "the row order would repeat the id order; the id seed and the row seed must differ")


def min_set_changes(counts: Mapping[str, int]) -> int | None:
    """Fewest value changes the key's set (or stratum) column must show along an order.

    ``None`` below ``ORDER_CHECK_MIN_ROWS`` rows. Otherwise a fraction of the number of
    changes a random order would show in expectation."""
    n = sum(counts.values())
    if n < ORDER_CHECK_MIN_ROWS:
        return None
    same = sum(c * (c - 1) for c in counts.values()) / (n * (n - 1))
    expected = (n - 1) * (1 - same)
    return math.ceil(round(ORDER_CHANGE_FRACTION * expected, 9))


# --------------------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------------------


def _word_regex(word: str, flags: int) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", flags)


def _forbidden_patterns(kind: str) -> list[re.Pattern[str]]:
    if kind == "claims":
        return [_word_regex(w, re.IGNORECASE) for w in _CLAIMS_FORBIDDEN]
    pats = [_word_regex(w, re.IGNORECASE) for w in _SCREENING_FORBIDDEN]
    pats += [_word_regex(w, 0) for w in _SCREENING_FORBIDDEN_CASE_SENSITIVE]
    return pats


def _forbidden_hit(text: str, pats: Sequence[re.Pattern[str]]) -> str | None:
    for pat in pats:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def _list_choices(dv: object) -> list[str] | None:
    formula = getattr(dv, "formula1", None)
    if not isinstance(formula, str) or not (formula.startswith('"') and formula.endswith('"')):
        return None
    return [c.strip() for c in formula[1:-1].split(",")]


def _read_key(key_path: Path, kind: str) -> tuple[dict[str, str], str]:
    group_col = "set" if kind == "claims" else "stratum"
    with Path(key_path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    id_col = next((c for c in ("opaque_id", "record_id", "item_id")
                   if rows and c in rows[0]), "opaque_id")
    return {r.get(id_col, ""): r.get(group_col, "") for r in rows}, group_col


def _changes(groups: Sequence[str]) -> int:
    return sum(1 for a, b in zip(groups, groups[1:], strict=False) if a != b)


def row_order_repeats_id_order(row_ids: Sequence[str], groups: Mapping[str, str]) -> bool:
    """True when reading the ids down the rows twice sorts the key groups into blocks.

    That is what a build shows when the row order is the same shuffle as the id order."""
    n = len(row_ids)
    try:
        t = [int(i[3:]) - 1 for i in row_ids]
    except ValueError:
        return False
    if sorted(t) != list(range(n)):
        return False
    q = [t[t[j]] for j in range(n)]
    by_q = sorted(range(n), key=lambda j: q[j])
    listed = [groups[row_ids[j]] for j in by_q]
    return len(set(listed)) > 1 and _changes(listed) == len(set(listed)) - 1


def _audit(
    path: Path, kind: str, key_path: Path | None,
) -> tuple[list[str], list[str]]:
    path = Path(path)
    findings: list[str] = []
    notes: list[str] = []
    expected_sheets = CLAIMS_SHEETS if kind == "claims" else SCREENING_SHEETS
    data_name = expected_sheets[1]
    data_header = BLIND_CLAIMS_HEADER if kind == "claims" else BLIND_SCREENING_HEADER
    id_pattern = re.compile(r"^BC-\d{3}$" if kind == "claims" else r"^BS-\d{3}$")
    free_cols = FREE_TEXT_COLUMNS[kind]
    pats = _forbidden_patterns(kind)

    if "scholarrag" in path.name.lower():
        findings.append(f"The file name {path.name} contains the tool name.")

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for name in names:
            if any(name.startswith(p) for p in _FORBIDDEN_PART_PATTERNS):
                findings.append(f"The file holds the part {name}, which must not ship.")
            if name.startswith("docProps/") and name.endswith(".xml"):
                text = zf.read(name).decode("utf-8", errors="replace")
                hit = _forbidden_hit(text, pats)
                if hit:
                    findings.append(f"The file part {name} contains the word {hit}.")

    wb = openpyxl.load_workbook(path)
    for prop in _PROPERTY_NAMES:
        value = getattr(wb.properties, prop, None)
        if value not in (None, ""):
            findings.append(f"The file property {prop} is not empty.")
    if tuple(wb.sheetnames) != expected_sheets:
        findings.append(
            f"The sheets are {list(wb.sheetnames)} but must be {list(expected_sheets)}."
        )
    if len(wb.defined_names) > 0:
        findings.append("The workbook has a defined name.")

    allowed_dv = {"yes", "no"}
    if kind == "claims":
        allowed_dv |= set(ex.HUMAN_VERDICT_CHOICES) | set(CONFIDENCE_CHOICES)
    else:
        allowed_dv |= set(SCREENING_DECISIONS)

    data_ids: list[str] = []
    for ws in wb.worksheets:
        name = ws.title
        if ws.sheet_state != "visible":
            findings.append(f"The sheet {name} is not visible.")
        if len(ws.defined_names) > 0:
            findings.append(f"The sheet {name} has a defined name.")
        hit = _forbidden_hit(name, pats)
        if hit:
            findings.append(f"The sheet name {name} contains the word {hit}.")
        for key, dim in ws.column_dimensions.items():
            if dim.hidden:
                findings.append(f"The sheet {name} has a hidden column {key}.")
        for key, dim in ws.row_dimensions.items():
            if dim.hidden:
                findings.append(f"The sheet {name} has a hidden row {key}.")
        for dv in ws.data_validations.dataValidation:
            if dv.type != "list":
                continue
            if not dv.showErrorMessage:
                findings.append(
                    f"The sheet {name} has a dropdown that accepts values outside its list.")
            choices = _list_choices(dv)
            if choices is None:
                findings.append(f"The sheet {name} has a dropdown that is not a literal list.")
                continue
            for choice in choices:
                ok = choice in allowed_dv or (
                    kind == "screening" and CRITERION_CHOICE_PATTERN.match(choice)
                )
                if not ok:
                    findings.append(
                        f"The sheet {name} has a dropdown choice {choice!r} outside the "
                        "allowed values."
                    )

        header = [c.value for c in ws[1]] if ws.max_row >= 1 else []
        header = [h for h in header]
        while header and header[-1] is None:
            header.pop()
        want: tuple[str, ...] | None = None
        if name == data_name:
            want = data_header
        elif name == "Sources":
            want = SOURCES_HEADER
        elif name == "Attestation":
            want = ATTESTATION_HEADER
        if want is not None and tuple(header) != want:
            findings.append(f"The header of {name} is {header} but must be {list(want)}.")

        for ri, row in enumerate(ws.iter_rows(), start=1):
            for cell in row:
                if cell.comment is not None:
                    findings.append(f"The cell {name}!{cell.coordinate} has a comment.")
                v = cell.value
                if v is None:
                    continue
                if cell.data_type == "f":
                    findings.append(f"The cell {name}!{cell.coordinate} holds a formula.")
                    continue
                text = str(v)
                col_name = header[cell.column - 1] if cell.column - 1 < len(header) else None
                is_header = ri == 1
                free = (
                    not is_header
                    and ((name == data_name and col_name in free_cols)
                         or (name == "Sources" and col_name == "text"))
                )
                if name in ("Guide", "Attestation") and "—" in text:
                    findings.append(f"The cell {name}!{cell.coordinate} contains an em dash.")
                if free and (name == "Sources" or kind == "screening"):
                    odd = (_UNSEARCHABLE if name == "Sources" else _TIDY_LEFTOVER).search(text)
                    if odd:
                        findings.append(
                            f"The {name} cell {cell.coordinate} holds {_describe_leftover(odd)}, "
                            "which a typed search does not match.")
                if free:
                    continue
                if ex.REAL_ITEM_ID_PATTERN.search(text):
                    findings.append(
                        f"The cell {name}!{cell.coordinate} contains a real item id."
                    )
                hit = _forbidden_hit(text, pats)
                if hit:
                    findings.append(
                        f"The cell {name}!{cell.coordinate} contains the word {hit}."
                    )
                if name in (data_name, "Sources") and cell.column == 1 and not is_header:
                    if not id_pattern.match(text):
                        findings.append(
                            f"The id {text} in {name}!{cell.coordinate} is not an opaque id."
                        )
                    if name == data_name:
                        data_ids.append(text)

    if key_path is not None:
        key_groups, group_col = _read_key(Path(key_path), kind)
        if set(data_ids) != set(key_groups):
            only_sheet = sorted(set(data_ids) - set(key_groups))
            only_key = sorted(set(key_groups) - set(data_ids))
            findings.append(
                f"The ids in the workbook and the key differ: {len(only_sheet)} only in the "
                f"workbook, {len(only_key)} only in the key."
            )
        else:
            if row_order_repeats_id_order(data_ids, key_groups):
                findings.append(
                    f"The row order repeats the id order: reading the ids down the rows twice "
                    f"sorts the key {group_col} into blocks."
                )
            counts: dict[str, int] = {}
            for g in key_groups.values():
                counts[g] = counts.get(g, 0) + 1
            need = min_set_changes(counts)
            if need is None:
                notes.append(
                    f"order check skipped, {len(key_groups)} rows < {ORDER_CHECK_MIN_ROWS}"
                )
            else:
                by_id = _changes([key_groups[i] for i in sorted(key_groups)])
                by_row = _changes([key_groups[i] for i in data_ids])
                if by_id < need:
                    findings.append(
                        f"The key {group_col} changes {by_id} times along id order; "
                        f"at least {need} are needed, so the order sorts by category."
                    )
                if by_row < need:
                    findings.append(
                        f"The key {group_col} changes {by_row} times along row order; "
                        f"at least {need} are needed, so the order sorts by category."
                    )
    return findings, notes


def audit_blind_workbook(
    path: Path, *, kind: Literal["claims", "screening"], key_path: Path | None = None,
) -> list[str]:
    """One plain sentence per problem; an empty list when the workbook is clean."""
    return _audit(path, kind, key_path)[0]


# --------------------------------------------------------------------------------------
# Blind claims workbook
# --------------------------------------------------------------------------------------

STORED_TEXT_SEE_SOURCES = (
    "See the Sources sheet: filter its item_id column to this row's item_id."
)
GUIDE_LAST_PARAGRAPH = (
    "Leave every other cell as it is. When you have finished, fill in the Attestation sheet "
    "(write numbers as whole numbers, such as 0 or 12, and the date as YYYY-MM-DD), save the "
    "workbook and send it back."
)
CLAIMS_GUIDE_TEMPLATE = (
    "What this workbook is. Each row of the Claims sheet is one claim sentence taken from a "
    "piece of academic writing, together with the paper the sentence cites. There are "
    "{n_rows} rows. Your task is to decide, for each row, whether the cited paper supports "
    "the claim.",
    "Claims are shown without their in-text citations. The paper each claim cites is given in "
    "the cited_title, cited_doi and cited_first_author_year columns.",
    "How to work through a row. Read the claim and pick two to four key terms from it, such "
    "as a number, a named group or a distinctive word. Filter the Sources item_id column to "
    "the row's item_id, then search the sheet (Ctrl+F, or Cmd+F on a Mac) for each term. Read "
    "the passage around each hit, then decide. Read the whole paper only when the searches do "
    "not settle the row. A long paper is split over several Sources rows, numbered in the "
    "part column. If a Sources cell holds more text than its row shows, select the cell and "
    "read the text in the formula bar.",
    "A sentence may continue in the next part. Read the next part as well, and when you quote "
    "across two parts, join them with one space.",
    "The Sources text is the stored text of the paper with its line breaks joined. Unusual "
    "spaces, quote marks, special hyphens, minus signs and joined letter pairs in the stored "
    "text were replaced with plain characters, so a typed search finds most words. A word "
    "broken at a line end keeps its hyphen (for example stu-dents). If a search finds "
    "nothing, also search for the first part of the word. Copy quotes from it as shown.",
    "Labels. Choose exactly one label in the human_verdict column:",
    "{definitions}",
    "If the paper states a different number, direction or detail for the same thing the claim "
    "describes, the paper contradicts the claim: choose unsupported. Choose needs_nuance for a "
    "detail the paper does not state, or for a claim that overstates the paper or leaves out a "
    "qualification it makes.",
    "A number or finding that the cited paper states counts as support, even when the paper "
    "reports it from another source.",
    "A row whose stored_text cell reads \"{marker}\" has no text on the Sources sheet. Label "
    "it no_full_text, even if the same paper appears under another item_id.",
    "Rules. Judge each row only from the claim and its stored text. Do not use your own "
    "knowledge of the subject, other sources, the internet, any AI tool or language model, "
    "or the other labellers. Do not try to find out where these claims come from.",
    "Also fill in, for every row: confidence (high, medium or low); human_quote (the sentence "
    "from the stored text that decided your label, copied exactly, or blank if there is "
    "none); human_note (one sentence saying why); minutes_spent (whole minutes you spent on "
    "the row).",
    "Time. Expect {per_row} per row on average and {workbook_time} for this workbook. You do "
    "not need to finish in one sitting. Write the minutes for each row in minutes_spent, and "
    "the total for the whole workbook in the Attestation sheet.",
    GUIDE_LAST_PARAGRAPH,
)
GUIDE_ID_LINE = "Workbook id: {workbook_id}. Copy: {copy}. Exported {export_time}."
ATTESTATION_QUESTIONS = (
    ("Highest degree and field of study", "text"),
    ("Current role (for example doctoral student, lecturer, researcher, editor)", "text"),
    ("Years of experience reading research articles in English", "text"),
    ("Your relation to the authors who asked you to label these items (none, colleague, "
     "current or former student, supervisor, friend or family, or other: please describe)",
     "text"),
    ("Have you seen any of these items, or any labels for them, before this workbook?",
     "yes_no"),
    ("I used no AI tool or language model while labelling.", "yes_no"),
    ("I did not discuss any item with the other labellers before sending this workbook back.",
     "yes_no"),
    ("I decided every row only from what this workbook shows.", "yes_no"),
    ("I agree to be named in the paper as one of the labellers.", "yes_no"),
    ("If yes, your name as it should appear", "text"),
    ("Total minutes spent on this workbook", "text"),
    ("Date you finished", "text"),
)
_WORKBOOK_ID_PATTERN = re.compile(r"Workbook id: ([0-9a-f]{16})")
_CLAIMS_WIDTHS = {
    "item_id": 10, "claim": 50, "cited_title": 35, "cited_doi": 22,
    "cited_first_author_year": 18, "stored_text": 30, "human_verdict": 16, "confidence": 12,
    "human_quote": 30, "human_note": 30, "minutes_spent": 10,
}
_CLAIMS_LINE_HEIGHT = 15
_CLAIMS_MIN_ROW_HEIGHT = 45
_CLAIMS_SIZED_COLUMNS = (
    "claim", "cited_title", "cited_doi", "cited_first_author_year", "stored_text")
_SOURCES_ROW_HEIGHT = 409
_MAX_ROW_HEIGHT = 409
_SOURCES_WIDTH = 120
_SOURCES_LINE_HEIGHT = 15
# A 409-point row shows 27 wrapped lines of 15 points. Columns hold about as many prose
# characters per line as their width in Excel units, so the width is the characters-per-line
# rule used to size rows and to cut Sources parts (it is slightly conservative).
_SOURCES_MAX_LINES = _MAX_ROW_HEIGHT // _SOURCES_LINE_HEIGHT
_GUIDE_CHARS_PER_LINE = 110
_GUIDE_LINE_HEIGHT = 15


_PARTICLE_WORDS = frozenset(
    "van von de der den du da di del della dos das le la ter ten".split())


def _surname(full_name: str) -> str:
    """The last token plus the lowercase particles just before it ("van der Heijden")."""
    parts = full_name.strip().split()
    if not parts:
        return full_name.strip()
    first = len(parts) - 1
    while first > 0 and parts[first - 1] in _PARTICLE_WORDS:
        first -= 1
    return " ".join(parts[first:])


def first_author_year(authors: Sequence[str] | None, year: Any) -> str:
    """Same rule as ``annotation/build_sheet_v3.first_author_year`` (reimplemented, not
    imported) except that lowercase particles stay with the surname ("van der Heijden"): last
    whitespace token as surname; one, two, or "et al."; "Unknown"; "n.d."."""
    surnames = [_surname(a) for a in authors] if authors else []
    if not surnames:
        base = "Unknown"
    elif len(surnames) == 1:
        base = surnames[0]
    elif len(surnames) == 2:
        base = f"{surnames[0]} & {surnames[1]}"
    else:
        base = f"{surnames[0]} et al."
    year_str = str(year) if year is not None else "n.d."
    return f"{base}, {year_str}"


def load_year_index(paths: Sequence[Path]) -> dict[str, Any]:
    """DOI to ``year`` from source lists such as ``claims/hss_test_v3_sources.json``."""
    index: dict[str, Any] = {}
    for path in paths:
        for entry in json.loads(Path(path).read_text(encoding="utf-8")):
            if entry.get("doi") and entry.get("year") is not None:
                index[entry["doi"]] = entry["year"]
    return index


def _item_year(item: Mapping[str, Any], doi: str, year_index: Mapping[str, Any]) -> Any:
    for value in (year_index.get(doi), item.get("cited_year"), item.get("year")):
        if value not in (None, ""):
            return value
    return None


_CITE_PARTICLE = r"(?:van|von|de|der|den|du|da|di|del|della|dos|das|le|la|ter|ten)"
_CITE_CAP = r"[A-ZÀ-Þ][\w'’\-]*"
_CITE_NAME = rf"(?:{_CITE_PARTICLE}\s+)*{_CITE_CAP}"
_CITE_PNAME = rf"(?:{_CITE_PARTICLE}\s+)*{_CITE_CAP}(?:\s+{_CITE_CAP})*"
_CITE_YEAR = r"(?:19|20)\d{2}[a-z]?"
_CITE_ONE = (rf"(?:e\.g\.,?\s+|see\s+)?{_CITE_PNAME}(?:\s+et al\.)?"
             rf"(?:(?:,\s+|\s+)(?:and|&)\s+{_CITE_PNAME}|,\s+{_CITE_PNAME})*,?\s+{_CITE_YEAR}"
             r"(?:,\s+pp?\.\s*\d+(?:\s*[-–]\s*\d+)?)?")
PARENTHETICAL_CITATION = re.compile(rf"\s?\((?:{_CITE_ONE})(?:\s*;\s*{_CITE_ONE})*\)")
NARRATIVE_CITATION = re.compile(
    rf"(?P<names>{_CITE_NAME}(?:\s+et al\.)?(?:\s+(?:and|&)\s+{_CITE_NAME})?)"
    rf"\s+\((?P<year>{_CITE_YEAR})\)")
_CITE_PREPOSITIONS = {"by", "with", "to", "from", "of", "for", "on", "than", "as"}
_THE_BEFORE = re.compile(r"(?<!\w)([Tt]he)\s+$")
_WORD_BEFORE = re.compile(r"(\w+)\W*$")


def neutralise_citations(claim: str) -> str:
    """Show a claim without its in-text citations, by one fixed rule.

    A parenthetical citation group is deleted with the space before it. A narrative citation
    such as ``Amels et al. (2020)`` becomes a pronoun, or "the author" for a single author.
    Nothing else in the claim changes."""
    text = PARENTHETICAL_CITATION.sub("", claim)
    out: list[str] = []
    pos = 0
    for m in NARRATIVE_CITATION.finditer(text):
        names = m.group("names")
        single = " and " not in names and " & " not in names and "et al." not in names
        start, prefix = m.start(), text[:m.start()]
        the = _THE_BEFORE.search(prefix)
        if the and the.start() >= pos:
            start = the.start()
            capital = the.group(1) == "The"
            word = "author's" if single else "their"
            repl = (word[0].upper() + word[1:]) if capital else word
            repl = f"{'The' if capital else 'the'} {word}" if single else repl
        elif single:
            repl = "The author" if start == 0 else "the author"
        else:
            before = _WORD_BEFORE.search(prefix)
            if before and before.group(1).lower() in _CITE_PREPOSITIONS:
                repl = "them"
            else:
                repl = "They" if start == 0 else "they"
        out.append(text[pos:start])
        out.append(repl)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def blind_claim_row(
    item: Mapping[str, Any], opaque_id: str, *, year_index: Mapping[str, Any],
    max_cell_chars: int,
) -> dict[str, Any]:
    title, doi = ex.cited_title_and_doi(item)
    stored = (STORED_TEXT_SEE_SOURCES if item.get("chunk_doi")
              else ex.NO_FULL_TEXT_EVIDENCE_MARKER)
    claim = neutralise_citations(item.get("claim") or "")
    row: dict[str, Any] = {
        "item_id": opaque_id,
        "claim": ex.cap_text(ex.sanitize_for_excel(claim), max_cell_chars),
        "cited_title": ex.cap_text(ex.sanitize_for_excel(title), max_cell_chars),
        "cited_doi": ex.sanitize_for_excel(doi),
        "cited_first_author_year": first_author_year(
            item.get("authors"), _item_year(item, doi, year_index)),
        "stored_text": stored,
    }
    return {name: row.get(name, "") for name in BLIND_CLAIMS_HEADER}


def build_blind_claims_workbook(
    item_specs: Sequence[tuple[Path, Path]], *, year_sources: Sequence[Path],
    seeds: BlindSeeds, copy: str, sources_max_chars: int, max_cell_chars: int,
    select_ids: Sequence[str] | None = None, export_time: str | None = None,
) -> tuple[openpyxl.Workbook, list[dict[str, Any]], dict[str, str], str]:
    items = ex.read_items(item_specs)
    caches = ex.build_caches(item_specs)
    if select_ids is not None:
        known = {it["item_id"] for it in items}
        unknown = [i for i in select_ids if i not in known]
        if unknown:
            raise ex.ExportError(f"unknown select id: {', '.join(unknown)}")
        wanted = set(select_ids)
        items = [it for it in items if it["item_id"] in wanted]

    texts: dict[str, str] = {}
    for it in items:
        doi = it.get("chunk_doi")
        if not doi:
            continue
        text = ex.sanitize_for_excel(ex.full_text_for_doi(doi, caches[it["_cache_dir"]]))
        if not text:
            raise ex.ExportError(f"no cached text for chunk_doi {doi} (item {it['item_id']})")
        texts[it["item_id"]] = text

    ids_seed = id_seed(seeds, "claims", copy)
    rows_seed = row_seed(seeds, "claims", copy)
    _check_orders_differ(ids_seed, rows_seed, len(items))
    ordered = [items[i] for i in shuffle_permutation(ids_seed, len(items))]
    opaque_ids = {it["item_id"]: f"{CLAIMS_ID_PREFIX}{rank:03d}"
                  for rank, it in enumerate(ordered, start=1)}
    workbook_id = blind_workbook_id([it["item_id"] for it in ordered], ids_seed, seeds.salt)
    export_time = export_time or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    year_index = load_year_index(year_sources)
    id_rows = [blind_claim_row(it, opaque_ids[it["item_id"]], year_index=year_index,
                               max_cell_chars=max_cell_chars) for it in ordered]
    shuffled_rows = [id_rows[i] for i in shuffle_permutation(rows_seed, len(id_rows))]

    wb = openpyxl.Workbook()
    wb.properties.creator = ""
    _write_claims_guide(wb.active, len(id_rows), workbook_id, copy, export_time)
    _write_claims_sheet(wb.create_sheet("Claims"), shuffled_rows)
    _write_sources_sheet(
        wb.create_sheet("Sources"), ordered, opaque_ids, texts, sources_max_chars)
    write_attestation_sheet(wb)
    return wb, ordered, opaque_ids, workbook_id


def _put(ws: Any, row: int, col: int, value: Any) -> Any:
    """Writes one cell. Every string is stored as a string, whatever its first character, so
    text such as "=6.200, p =.013" is never read as a formula and is displayed unchanged."""
    cell = ws.cell(row=row, column=col, value=ex.sanitize_for_excel(value))
    if isinstance(cell.value, str):
        cell.data_type = "s"
    return cell


def _write_claims_guide(
    ws: Any, n_rows: int, workbook_id: str, copy: str, export_time: str,
) -> None:
    ws.title = "Guide"
    paragraphs: list[str] = []
    for template in CLAIMS_GUIDE_TEMPLATE:
        if template == "{definitions}":
            paragraphs.extend(ex.STATUS_DEFINITIONS_V3)
        else:
            paragraphs.append(template.format(
                n_rows=n_rows, marker=ex.NO_FULL_TEXT_EVIDENCE_MARKER,
                per_row=f"about {round(CLAIMS_MINUTES_PER_ITEM)} minutes",
                workbook_time=time_phrase(n_rows * CLAIMS_MINUTES_PER_ITEM)))
    paragraphs.append(GUIDE_ID_LINE.format(
        workbook_id=workbook_id, copy=copy, export_time=export_time))
    ws.column_dimensions["A"].width = 120
    for r, text in enumerate(paragraphs, start=1):
        cell = _put(ws, r, 1, text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        lines = max(1, math.ceil(len(text) / _GUIDE_CHARS_PER_LINE))
        ws.row_dimensions[r].height = lines * _GUIDE_LINE_HEIGHT


_DV_ENFORCE = {
    "showErrorMessage": True, "errorStyle": "stop", "errorTitle": "Not in the list",
    "error": "Choose a value from the dropdown list.",
}


def _column_letter(header: Sequence[str], name: str) -> str:
    """The sheet column letter of the header named ``name``."""
    return get_column_letter(list(header).index(name) + 1)


def _add_list_validation(ws: Any, column: str, choices: Sequence[str], last_row: int) -> None:
    dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True,
                        **_DV_ENFORCE)
    dv.add(f"{column}2:{column}{last_row}")
    ws.add_data_validation(dv)


def claims_row_needed_height(row: Mapping[str, Any]) -> int:
    """Points the longest wrapped cell of a Claims row needs, at one character per width unit
    and 15 points per line, before the 409-point limit."""
    lines = max(
        wrapped_line_count(str(row.get(name) or ""), _CLAIMS_WIDTHS[name])
        for name in _CLAIMS_SIZED_COLUMNS)
    return lines * _CLAIMS_LINE_HEIGHT


def claims_row_height(row: Mapping[str, Any]) -> int:
    return min(_MAX_ROW_HEIGHT, max(_CLAIMS_MIN_ROW_HEIGHT, claims_row_needed_height(row)))


def count_claims_overflow_rows(rows: Sequence[Mapping[str, Any]]) -> int:
    """Claims rows whose text needs more than Excel's 409-point maximum row height."""
    return sum(1 for r in rows if claims_row_needed_height(r) > _MAX_ROW_HEIGHT)


def _write_claims_sheet(ws: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    for c, name in enumerate(BLIND_CLAIMS_HEADER, start=1):
        cell = _put(ws, 1, c, name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(c)].width = _CLAIMS_WIDTHS[name]
    for r, row in enumerate(rows, start=2):
        for c, name in enumerate(BLIND_CLAIMS_HEADER, start=1):
            _put(ws, r, c, row[name]).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = claims_row_height(row)
    ws.freeze_panes = "C2"
    last = len(rows) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(BLIND_CLAIMS_HEADER))}{last}"
    _add_list_validation(
        ws, _column_letter(BLIND_CLAIMS_HEADER, "human_verdict"), ex.HUMAN_VERDICT_CHOICES, last)
    _add_list_validation(
        ws, _column_letter(BLIND_CLAIMS_HEADER, "confidence"), CONFIDENCE_CHOICES, last)


NL = chr(10)
_LINE_BREAK = re.compile(chr(13) + NL + "|" + chr(13) + "|" + NL)
_PARAGRAPH_BREAK = re.compile(NL + "[ " + chr(9) + "]*" + NL + "+")
_HYPHENS = "-" + chr(0x2010)


def wrapped_line_count(text: str, chars_per_line: int) -> int:
    """Lines a cell needs: each newline-separated paragraph takes ceil(len / chars_per_line)
    lines, and an empty paragraph takes one."""
    return sum(max(1, math.ceil(len(part) / chars_per_line))
               for part in _LINE_BREAK.split(text))


def join_hard_wraps(text: str) -> str:
    """Display form of a Sources text: single line breaks inside a paragraph become spaces,
    blank-line paragraph breaks stay, and a word split by hyphenation at a line end is joined
    without a space (its hyphen stays). CRLF, a lone CR and LF are the same line break. The
    stored text is not changed."""
    text = _LINE_BREAK.sub(NL, text)
    out: list[str] = []
    for para in _PARAGRAPH_BREAK.split(text):
        lines = [ln.strip() for ln in para.split(NL) if ln.strip()]
        joined = ""
        for ln in lines:
            if not joined:
                joined = ln
            elif (joined[-1] in _HYPHENS and len(joined) > 1 and joined[-2].isalpha()
                    and ln[0].islower()):
                joined += ln
            else:
                joined += " " + ln
        out.append(joined)
    return (NL * 2).join(p for p in out if p)


_TIDY_LEFTOVER = re.compile(
    "[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000\u2010\u2011\u2212\u2018\u2019\u201c\u201d]"
    "|[ \t]{2,}")
_UNSEARCHABLE = re.compile(_TIDY_LEFTOVER.pattern + "|[\ufb00-\ufb06\u0134]")
_DASH_QUOTE_MAP = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
})
_SPACE_RUN = re.compile("[ \t]{2,}")
_SPLIT_LIGATURE = re.compile("([\ufb00-\ufb06]) {1,2}(?=[a-z])")
_JOINED_LIGATURE = re.compile(r"[\ufb00-\ufb06](?=[^\W\d_])")
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
}
_TT_GLYPH_SPACED = re.compile("(?<=[A-Za-z])\u0134 ?(?=[a-z])")
_TT_GLYPH = re.compile("(?<=[A-Za-z])\u0134")
_SENTENCE_END = re.compile(
    "(?:[.!?][\"'\u201d\u2019)\\]]*[ \t]+(?=[A-Z0-9\"'(\\[\u201c\u2018])|\n\n+)")


def fold_unicode_spaces(text: str) -> str:
    """Every Unicode space other than U+0020 becomes U+0020, so a typed space matches it.
    U+200B has no width, so it is deleted: a space there would split a URL or a DOI."""
    text = text.replace("\u200b", "")
    return "".join(
        " " if ch != " " and unicodedata.category(ch) == "Zs" else ch for ch in text)


def repair_extraction_glyphs(text: str) -> str:
    """Undo three PDF extraction artefacts so that a typed search finds the words.

    1. A text in the split style (a ligature, a space, a lowercase letter, as in "fi rst"),
       where split pairs outnumber joined ones, has the spaces after its ligatures removed.
       A text with mostly joined ligatures is left alone there, because a genuine word can
       end in a ligature before a space ("off the").
    2. Ligature characters become their letters (an explicit map, not NFKC of the text).
    3. U+0134 after a letter stands for "tt" (as in "attitudes"); one following space goes."""
    if len(_SPLIT_LIGATURE.findall(text)) > len(_JOINED_LIGATURE.findall(text)):
        text = _SPLIT_LIGATURE.sub(r"\1", text)
    text = "".join(_LIGATURES.get(ch, ch) for ch in text)
    text = _TT_GLYPH_SPACED.sub("tt", text)
    return _TT_GLYPH.sub("tt", text)


def tidy_display_characters(text: str) -> str:
    """Plain characters for a displayed text: Unicode spaces become a space (U+200B is
    deleted), U+2010, U+2011 and U+2212 become a hyphen, curly quotes become straight ones,
    and a run of two or more spaces or tabs becomes one space. Newlines are untouched. No
    ligature or glyph repair."""
    text = fold_unicode_spaces(text).translate(_DASH_QUOTE_MAP)
    return _SPACE_RUN.sub(" ", text)


def display_source_text(text: str) -> str:
    """The text a Sources cell shows for a stored paper text. The stored text is not changed.
    The character maps run before the line joiner, so a line-end hyphen of any kind is a
    plain hyphen when it tests for one; space runs are collapsed last."""
    text = fold_unicode_spaces(text).translate(_DASH_QUOTE_MAP)
    return _SPACE_RUN.sub(" ", repair_extraction_glyphs(join_hard_wraps(text)))


def _describe_leftover(match: re.Match[str]) -> str:
    found = match.group(0)
    if found.strip(" \t") == "":
        return "a run of two or more spaces or tabs"
    return f"the character U+{ord(found):04X}"


def _sentence_cut(text: str, start: int, end: int, floor: int) -> int:
    """The end of the last sentence break in text[start:end] that lies past ``floor``
    characters of the window, or 0 when there is none."""
    best = 0
    for m in _SENTENCE_END.finditer(text, start, min(len(text), end + 1)):
        if m.end() <= end and m.end() - start > floor:
            best = m.end() - start
    return best


def split_source_text(
    text: str, limit: int, *, max_lines: int | None = None, chars_per_line: int | None = None,
) -> list[str]:
    """Split ``text`` into parts of at most ``limit`` characters. A part ends at the last
    sentence end in the second half of its window, else after the last whitespace, so that a
    word is not cut; a part with neither is cut at ``limit``. With
    ``max_lines`` and ``chars_per_line`` a part is also kept within that many wrapped lines."""
    parts: list[str] = []
    start = 0
    while start < len(text):
        size = limit
        while True:
            end = start + size
            if end >= len(text):
                end = len(text)
            else:
                window = text[start:end]
                cut = _sentence_cut(text, start, end, size // 2)
                if not cut:
                    cut = max(
                        (k for k, ch in enumerate(window) if ch.isspace()), default=-1) + 1
                end = start + cut if cut > size // 2 else end
            part = text[start:end]
            if (max_lines is None or chars_per_line is None or size <= 1
                    or wrapped_line_count(part, chars_per_line) <= max_lines):
                break
            size = int(size * 0.9)
        parts.append(part)
        start = end
    return parts


def _write_sources_sheet(
    ws: Any, ordered: Sequence[Mapping[str, Any]], opaque_ids: Mapping[str, str],
    texts: Mapping[str, str], sources_max_chars: int,
) -> None:
    for c, name in enumerate(SOURCES_HEADER, start=1):
        _put(ws, 1, c, name).font = Font(bold=True)
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 8
    ws.column_dimensions["C"].width = _SOURCES_WIDTH
    r = 2
    for it in ordered:
        text = texts.get(it["item_id"])
        if not text:
            continue
        shown = display_source_text(text)
        for part, chunk in enumerate(split_source_text(
                shown, sources_max_chars, max_lines=_SOURCES_MAX_LINES,
                chars_per_line=_SOURCES_WIDTH), start=1):
            _put(ws, r, 1, opaque_ids[it["item_id"]])
            _put(ws, r, 2, part)
            _put(ws, r, 3, chunk).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[r].height = _SOURCES_ROW_HEIGHT
            r += 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:C{max(r - 1, 1)}"


def write_attestation_sheet(wb: openpyxl.Workbook) -> None:
    ws = wb.create_sheet("Attestation")
    for c, name in enumerate(ATTESTATION_HEADER, start=1):
        _put(ws, 1, c, name).font = Font(bold=True)
    ws.column_dimensions["A"].width = 70
    ws.column_dimensions["B"].width = 40
    dv = DataValidation(type="list", formula1='"yes,no"', allow_blank=True, **_DV_ENFORCE)
    for r, (question, kind) in enumerate(ATTESTATION_QUESTIONS, start=2):
        _put(ws, r, 1, question).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = _GUIDE_LINE_HEIGHT * max(
            1, math.ceil(len(question) / 65))
        if kind == "yes_no":
            dv.add(f"B{r}")
    ws.add_data_validation(dv)
    ws.freeze_panes = "A2"


def read_guide_workbook_id(path: Path) -> str | None:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        for (value,) in wb["Guide"].iter_rows(min_col=1, max_col=1, values_only=True):
            if isinstance(value, str):
                m = _WORKBOOK_ID_PATTERN.search(value)
                if m:
                    return m.group(1)
    finally:
        wb.close()
    return None


COPY_IDENTIFICATION_METHODS = ("guide_line", "explicit_copy", "row_order")


def _first_column_ids(path: Path, sheet: str) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        if sheet not in wb.sheetnames:
            return []
        rows = wb[sheet].iter_rows(min_col=1, max_col=1, values_only=True)
        next(rows, None)
        return [str(v).strip() for (v,) in rows if v is not None and str(v).strip()]
    finally:
        wb.close()


def resolve_workbook_id(
    path: Path, *, kind: Literal["claims", "screening"], copy: str | None = None,
    sent_dir: Path | None = None,
) -> tuple[str, str]:
    """(workbook id, method) for a returned workbook. The method is ``guide_line`` when the
    Guide still has the ``Workbook id:`` line, else ``explicit_copy`` when *copy* names the
    sent copy, else ``row_order`` when exactly one sent copy has the same id order in its
    Claims (or Screening) sheet. The sent copies are read from *sent_dir*, which is needed
    only when the Guide has lost its id line. Raises ValueError when there is no *sent_dir*,
    or when no sent copy, or more than one, matches. The id itself is returned for the
    caller to check and is never printed here."""
    found = read_guide_workbook_id(path)
    if found is not None:
        return found, "guide_line"
    if sent_dir is None:
        raise ValueError(
            f"{Path(path).name}: the Guide has no workbook id line, so the folder of the "
            "sent copies is needed (--sent-dir)")
    folder = Path(sent_dir)
    sent = {n: folder / f"blind-{kind}-copy{n}.xlsx" for n in ("1", "2", "3")}
    sheet = "Claims" if kind == "claims" else "Screening"
    if copy is not None:
        if copy not in sent or not sent[copy].is_file():
            raise ValueError(f"{Path(path).name}: copy {copy!r} is not a sent {kind} copy")
        sent_id = read_guide_workbook_id(sent[copy])
        if sent_id is None:
            raise ValueError(f"{Path(path).name}: the sent copy {copy!r} has no workbook id")
        return sent_id, "explicit_copy"
    order = _first_column_ids(Path(path), sheet)
    matches = [n for n, p in sent.items()
               if p.is_file() and _first_column_ids(p, sheet) == order]
    if not matches:
        raise ValueError(
            f"{Path(path).name}: no sent copy has the same {sheet} row order and the Guide "
            "has no workbook id line")
    if len(matches) > 1:
        raise ValueError(
            f"{Path(path).name}: more than one sent copy has the same {sheet} row order")
    sent_id = read_guide_workbook_id(sent[matches[0]])
    if sent_id is None:
        raise ValueError(f"{Path(path).name}: the matching sent copy has no workbook id")
    return sent_id, "row_order"


def _run_claims(args: argparse.Namespace) -> int:
    seeds = load_seeds(args.seeds_file)
    select_ids = None
    if args.select_ids is not None:
        select_ids = [ln.strip() for ln in Path(args.select_ids).read_text(
            encoding="utf-8").splitlines() if ln.strip()]
    specs = ex.resolve_item_specs(args.items, args.cache_dir)
    try:
        wb, ordered, opaque_ids, workbook_id = build_blind_claims_workbook(
            specs, year_sources=args.year_sources, seeds=seeds, copy=args.copy,
            sources_max_chars=args.sources_max_chars, max_cell_chars=args.max_cell_chars,
            select_ids=select_ids)
    except ex.ExportError as err:
        print(f"ERROR: {err}")
        return 1
    n_rows = len(ordered)
    if args.expect_items is not None and args.expect_items != n_rows:
        print(f"ERROR: expected {args.expect_items} items but the build has {n_rows}")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    ex.write_key_csv(args.key_out, ordered, opaque_ids, workbook_id=workbook_id)
    findings, notes = _audit(args.out, "claims", args.key_out)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    for finding in findings:
        print(finding)
    ws = openpyxl.load_workbook(args.out)["Claims"]
    shown = [{name: ws.cell(r, c).value for c, name in enumerate(BLIND_CLAIMS_HEADER, start=1)}
             for r in range(2, ws.max_row + 1)]
    print(f"  rows taller than the 409-point maximum: {count_claims_overflow_rows(shown)} "
          f"of {n_rows}")
    print(f"wrote {args.out} ({n_rows} rows, workbook id {workbook_id}) and {args.key_out}")
    return 1 if findings else 0


# --------------------------------------------------------------------------------------
# Blind screening sample and workbook
# --------------------------------------------------------------------------------------

BLIND_SCREENING_STRATA = ("exclude", "include", "judge_demoted", "other_needs_review")
DEFAULT_SCREENING_SIZES = {
    "exclude": 80, "include": 30, "judge_demoted": 20, "other_needs_review": 10,
}
SCREENING_KEY_HEADER = (
    "opaque_id", "stratum", "status", "needs_review_reason", "openalex_id", "doi", "title",
    "workbook_id",
)
SCREENING_GUIDE_TEMPLATE = (
    "What this workbook is. Each row of the Screening sheet is one record found by a "
    "literature search: its title, abstract, venue and year. There are {n_rows} rows. Your "
    "task is to decide, for each record, whether it belongs in a review that answers the "
    "question below, using the title and abstract alone.",
    "Review question: {query}",
    "Criteria:\n{criteria}",
    "Decisions. Choose exactly one in the human_decision column:",
    "include: from the title and abstract, the record appears to meet every inclusion "
    "criterion (I) and no exclusion criterion (E). Leave human_criterion blank.",
    "exclude: the record clearly fails at least one criterion. Put that criterion's id in "
    "human_criterion (for example I2 or E3), or TOPIC if the record is not about the review "
    "question at all.",
    "unsure: the title and abstract do not settle it. Put the criterion that cannot be "
    "settled in human_criterion.",
    "Use TOPIC when the record is not about the review question at all. Otherwise record the "
    "first failing criterion in list order; for unsure, record the first criterion in list "
    "order that the title and abstract cannot settle.",
    "A record whose abstract cell reads \"(no abstract)\" has no abstract, and an abstract "
    "that is cut short (it stops mid-word or ends with \"...\") is treated the same way. "
    "Decide from the title and whatever abstract text there is, and choose unsure if that "
    "does not settle it.",
    "Rules. Decide each record only from what this workbook shows. Do not use other sources, "
    "the internet, any AI tool or language model, or the other labellers. Do not try to find "
    "out where these records come from.",
    "Also fill in human_note with one short sentence whenever you choose exclude or unsure.",
    "Long abstracts. Every row is as tall as its text needs, up to the largest row height Excel "
    "allows. If an abstract is longer than the row shows, click the cell and read the rest in "
    "the formula bar above the sheet.",
    "Time and uncertainty. Expect {per_row} per record and {workbook_time} for this "
    "workbook. The Screening sheet has no time column. When you have finished, "
    "write the total minutes you spent on this workbook in the Attestation row "
    "\"{total_minutes_question}\". If the title and abstract do not let you decide a record, "
    "choose unsure; there is no separate confidence column.",
    GUIDE_LAST_PARAGRAPH,
)
_SCREENING_WIDTHS = {
    "record_id": 10, "title": 45, "abstract": 150, "venue": 28, "year": 8,
    "human_decision": 14, "human_criterion": 14, "human_note": 30,
}
_SCREENING_LINE_HEIGHT = 15
_SCREENING_MIN_ROW_HEIGHT = 45


def screening_row_needed_height(row: Mapping[str, Any]) -> int:
    """Points the longest wrapped cell (title, abstract or venue) needs, at one character per width
    unit and 15 points per line, before the 409-point limit."""
    lines = max(
        wrapped_line_count(str(row.get(name) or ""), _SCREENING_WIDTHS[name])
        for name in ("title", "abstract", "venue"))
    return lines * _SCREENING_LINE_HEIGHT


def screening_row_height(row: Mapping[str, Any]) -> int:
    return min(_MAX_ROW_HEIGHT, max(_SCREENING_MIN_ROW_HEIGHT, screening_row_needed_height(row)))


def count_overflow_rows(rows: Sequence[Mapping[str, Any]]) -> int:
    """Rows whose text needs more than Excel's 409-point maximum row height."""
    return sum(1 for r in rows if screening_row_needed_height(r) > _MAX_ROW_HEIGHT)


def normalise_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def record_match_keys(record: Mapping[str, Any]) -> set[str]:
    """Keys by which two screening records are the same paper: OpenAlex id, DOI, title."""
    keys: set[str] = set()
    openalex = str(record.get("openalex_id") or "").strip()
    if openalex:
        keys.add(f"openalex:{openalex.rsplit('/', 1)[-1]}")
    doi = str(record.get("doi") or "").strip().lower()
    if doi:
        keys.add(f"doi:{doi}")
    title = normalise_title(record.get("title"))
    if title:
        keys.add(f"title:{title}")
    return keys


def load_key_lines(path: Path | None) -> set[str]:
    """Record keys, one per line; no path means no keys."""
    if path is None:
        return set()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {ln.strip() for ln in lines if ln.strip()}


def blind_screening_stratum(record: Mapping[str, Any]) -> str | None:
    status = record.get("status")
    if status == "EXCLUDE":
        return "exclude"
    if status == "INCLUDE":
        return "include"
    if status == "NEEDS_REVIEW":
        if record.get("needs_review_reason") == "not_established":
            return "judge_demoted"
        return "other_needs_review"
    return None


def draw_screening_sample(
    records: Sequence[Mapping[str, Any]], *, sizes: Mapping[str, int], seed: int,
    exclude_keys: AbstractSet[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    pools: dict[str, list[Mapping[str, Any]]] = {s: [] for s in BLIND_SCREENING_STRATA}
    for record in records:
        stratum = blind_screening_stratum(record)
        if stratum is not None and record_match_keys(record).isdisjoint(exclude_keys):
            pools[stratum].append(record)
    rng = random.Random(seed)
    sample: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for stratum in BLIND_SCREENING_STRATA:
        pool = pools[stratum]
        # A short stratum is taken whole and not refilled from another stratum; the counts
        # record how many were drawn and how many were available.
        k = min(sizes[stratum], len(pool))
        for record in rng.sample(pool, k):
            sample.append({**record, "_stratum": stratum})
        counts[stratum] = {"drawn": k, "available": len(pool)}
    return sample, counts


def criterion_choices(criteria: Mapping[str, Any]) -> tuple[str, ...]:
    n_in = len(criteria.get("inclusion_criteria") or [])
    n_ex = len(criteria.get("exclusion_criteria") or [])
    return (
        *(f"I{i}" for i in range(1, n_in + 1)),
        *(f"E{i}" for i in range(1, n_ex + 1)),
        ex.TOPIC_CRITERION_ID,
    )


def blind_screening_row(
    record: Mapping[str, Any], opaque_id: str, *, max_cell_chars: int,
) -> dict[str, Any]:
    abstract = tidy_display_characters(ex.render_abstract_for_screening(record.get("abstract")))
    row: dict[str, Any] = {
        "record_id": opaque_id,
        "title": ex.cap_text(
            ex.sanitize_for_excel(tidy_display_characters(record.get("title") or "")),
            max_cell_chars),
        "abstract": (ex.cap_text(ex.sanitize_for_excel(abstract), max_cell_chars)
                     if abstract else ex.NO_ABSTRACT_PLACEHOLDER),
        "venue": ex.cap_text(
            ex.sanitize_for_excel(tidy_display_characters(record.get("journal") or "")),
            max_cell_chars),
        "year": record.get("year") or "",
    }
    return {name: row.get(name, "") for name in BLIND_SCREENING_HEADER}


def _id_key(record: Mapping[str, Any]) -> str:
    keys = record_match_keys(record)
    for prefix in ("openalex:", "doi:", "title:"):
        found = sorted(k for k in keys if k.startswith(prefix))
        if found:
            return found[0]
    return ""


def _git_show_bytes(rev_path: str) -> bytes:
    """Return the committed bytes of REV:PATH from the repository that holds this code."""
    import subprocess

    done = subprocess.run(
        ["git", "-C", str(HERE.parent.parent), "show", rev_path],
        capture_output=True, check=False)
    if done.returncode != 0:
        raise ex.ExportError(f"cannot read {rev_path} from git")
    return done.stdout


def check_record_identity(
    record_path: Path, *, expect_sha256: str | None, expect_git: str | None,
) -> None:
    """Refuse a screening record that is not the expected file. The comparison is made in
    memory and the message carries no digest."""
    if (expect_sha256 is None) == (expect_git is None):
        raise ValueError("give exactly one of expect_sha256 and expect_git")
    if expect_git is not None:
        if _git_show_bytes(expect_git) != Path(record_path).read_bytes():
            raise ex.ExportError(f"the screening record differs from {expect_git}")
    elif hashlib.sha256(Path(record_path).read_bytes()).hexdigest() != expect_sha256:
        raise ex.ExportError("the screening record does not match the expected sha256")


def build_blind_screening_workbook(
    record_path: Path, *, expect_sha256: str | None = None, expect_git: str | None = None,
    exclude_keys_path: Path | None = None, seeds: BlindSeeds,
    copy: str, max_cell_chars: int, sizes: Mapping[str, int] | None = None,
    export_time: str | None = None,
) -> tuple[openpyxl.Workbook, list[dict[str, Any]], dict[str, str], str,
           dict[str, dict[str, int]]]:
    check_record_identity(record_path, expect_sha256=expect_sha256, expect_git=expect_git)
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    records = record["records"]
    criteria = record["criteria"]
    excluded_keys = load_key_lines(exclude_keys_path)
    main_sizes = DEFAULT_SCREENING_SIZES if sizes is None else sizes
    rows_seed = row_seed(seeds, "screening", copy)
    ids_seed = id_seed(seeds, "screening", copy)

    sample, counts = draw_screening_sample(
        records, sizes=main_sizes, seed=seeds.screening_sample_seed, exclude_keys=excluded_keys)

    _check_orders_differ(ids_seed, rows_seed, len(sample))
    ordered = [sample[i] for i in shuffle_permutation(ids_seed, len(sample))]
    opaque_ids = {_id_key(r): f"{SCREENING_ID_PREFIX}{rank:03d}"
                  for rank, r in enumerate(ordered, start=1)}
    workbook_id = blind_workbook_id([_id_key(r) for r in ordered], ids_seed, seeds.salt)
    export_time = export_time or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    id_rows = [blind_screening_row(r, opaque_ids[_id_key(r)], max_cell_chars=max_cell_chars)
               for r in ordered]
    shuffled_rows = [id_rows[i] for i in shuffle_permutation(rows_seed, len(id_rows))]

    wb = openpyxl.Workbook()
    wb.properties.creator = ""
    _write_screening_guide(wb.active, criteria, len(id_rows), workbook_id, copy, export_time)
    _write_screening_sheet(wb.create_sheet("Screening"), shuffled_rows, criteria)
    write_attestation_sheet(wb)
    return wb, ordered, opaque_ids, workbook_id, counts


def _write_screening_guide(
    ws: Any, criteria: Mapping[str, Any], n_rows: int, workbook_id: str, copy: str,
    export_time: str,
) -> None:
    ws.title = "Guide"
    paragraphs = [
        template.format(
            n_rows=n_rows, query=str(criteria.get("query") or ""),
            criteria=ex.render_numbered_criteria(criteria),
            per_row=(f"about {round(SCREENING_MINUTES_LOW)} to "
                     f"{round(SCREENING_MINUTES_PER_RECORD)} minutes"),
            workbook_time=time_range_phrase(
                n_rows * SCREENING_MINUTES_LOW, n_rows * SCREENING_MINUTES_PER_RECORD),
            total_minutes_question=next(
                q for q, _ in ATTESTATION_QUESTIONS if q.startswith(_TOTAL_MINUTES_PREFIX)))
        for template in SCREENING_GUIDE_TEMPLATE
    ]
    paragraphs.append(GUIDE_ID_LINE.format(
        workbook_id=workbook_id, copy=copy, export_time=export_time))
    ws.column_dimensions["A"].width = 120
    for r, text in enumerate(paragraphs, start=1):
        cell = _put(ws, r, 1, text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        lines = sum(max(1, math.ceil(len(part) / _GUIDE_CHARS_PER_LINE))
                    for part in text.split("\n"))
        ws.row_dimensions[r].height = lines * _GUIDE_LINE_HEIGHT


def _write_screening_sheet(
    ws: Any, rows: Sequence[Mapping[str, Any]], criteria: Mapping[str, Any],
) -> None:
    for c, name in enumerate(BLIND_SCREENING_HEADER, start=1):
        cell = _put(ws, 1, c, name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(c)].width = _SCREENING_WIDTHS[name]
    for r, row in enumerate(rows, start=2):
        for c, name in enumerate(BLIND_SCREENING_HEADER, start=1):
            _put(ws, r, c, row[name]).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = screening_row_height(row)
    ws.freeze_panes = "C2"
    last = len(rows) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(BLIND_SCREENING_HEADER))}{last}"
    _add_list_validation(
        ws, _column_letter(BLIND_SCREENING_HEADER, "human_decision"), SCREENING_DECISIONS, last)
    _add_list_validation(
        ws, _column_letter(BLIND_SCREENING_HEADER, "human_criterion"),
        criterion_choices(criteria), last)


def write_screening_key_csv(
    path: Path, sample: Sequence[Mapping[str, Any]], opaque_ids: Mapping[str, str], *,
    workbook_id: str,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCREENING_KEY_HEADER)
        writer.writeheader()
        for r in sample:
            writer.writerow({
                "opaque_id": opaque_ids[_id_key(r)], "stratum": r["_stratum"],
                "status": r.get("status") or "",
                "needs_review_reason": r.get("needs_review_reason") or "",
                "openalex_id": r.get("openalex_id") or "", "doi": r.get("doi") or "",
                "title": r.get("title") or "", "workbook_id": workbook_id,
            })


def _run_screening(args: argparse.Namespace) -> int:
    seeds = load_seeds(args.seeds_file)
    try:
        wb, sample, opaque_ids, workbook_id, counts = build_blind_screening_workbook(
            args.screening_record, expect_sha256=args.expect_sha256,
            expect_git=args.expect_git, exclude_keys_path=args.exclude_keys, seeds=seeds,
            copy=args.copy, max_cell_chars=args.max_cell_chars)
    except ex.ExportError as err:
        print(f"ERROR: {err}")
        return 1
    n_rows = len(sample)
    if args.expect_records is not None and args.expect_records != n_rows:
        print(f"ERROR: expected {args.expect_records} records but the build has {n_rows}")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    write_screening_key_csv(args.key_out, sample, opaque_ids, workbook_id=workbook_id)
    findings, notes = _audit(args.out, "screening", args.key_out)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    for stratum, c in counts.items():
        print(f"  {stratum}: {c['drawn']} of {c['available']}")
    for finding in findings:
        print(finding)
    ws = openpyxl.load_workbook(args.out)["Screening"]
    col = {name: BLIND_SCREENING_HEADER.index(name) + 1 for name in ("title", "abstract", "venue")}
    shown = [{name: ws.cell(r, c).value for name, c in col.items()}
             for r in range(2, ws.max_row + 1)]
    print(f"  rows taller than the 409-point maximum: {count_overflow_rows(shown)} of {n_rows}")
    print(f"wrote {args.out} ({n_rows} rows, workbook id {workbook_id}) and {args.key_out}")
    return 1 if findings else 0


# --------------------------------------------------------------------------------------
# Manifest and filled-workbook validator
# --------------------------------------------------------------------------------------

COMMITMENT_RULE = (
    "sha256 of '<seed>:<salt>', seed in decimal; seeds and salt are published with the results"
)
FULL_ROUND_REAL = 26
FULL_ROUND_CONSTRUCTED_TEXT = 52
FULL_ROUND_NO_TEXT = 8
FULL_ROUND_SCREENING_RECORDS = 140
CLAIMS_HOURS_ESTIMATE = 14.0
SCREENING_HOURS_LOW = 2.5
SCREENING_HOURS_ESTIMATE = 4.5
FULL_ROUND_CLAIM_ITEMS = FULL_ROUND_REAL + FULL_ROUND_CONSTRUCTED_TEXT + FULL_ROUND_NO_TEXT
CLAIMS_MINUTES_PER_ITEM = CLAIMS_HOURS_ESTIMATE * 60 / FULL_ROUND_CLAIM_ITEMS
SCREENING_MINUTES_PER_RECORD = SCREENING_HOURS_ESTIMATE * 60 / FULL_ROUND_SCREENING_RECORDS
SCREENING_MINUTES_LOW = SCREENING_HOURS_LOW * 60 / FULL_ROUND_SCREENING_RECORDS
_INTEGER_PATTERN = re.compile(r"\d+")
_NAME_QUESTION_PREFIX = "If yes, your name"
_CONSENT_QUESTION_PREFIX = "I agree to be named"
_TOTAL_MINUTES_PREFIX = "Total minutes"


def time_range_phrase(low: float, high: float) -> str:
    """"about 2.5 to 4.5 hours": two rounded times, the unit named once when both share it."""
    first, second = time_phrase(low), time_phrase(high)
    unit = second.rsplit(" ", 1)[1]
    if first.endswith(unit):
        first = first[: -len(unit) - 1]
    return f"{first} to {second[len('about '):]}"


def time_phrase(minutes: float) -> str:
    """A rounded time for the Guide: whole fives of minutes below 90, else half hours."""
    if minutes < 90:
        return f"about {max(5, 5 * round(minutes / 5))} minutes"
    return f"about {round(minutes / 30) / 2:g} hours"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_sha256(item: Mapping[str, Any]) -> str:
    return _sha256_text(f"{item['item_id']}\x00{item.get('claim') or ''}")


def record_sha256(record: Mapping[str, Any]) -> str:
    return _sha256_text(_id_key(record))


def build_manifest(
    item_specs: Sequence[tuple[Path, Path]], record_path: Path, exclude_keys_path: Path | None,
    seeds: BlindSeeds, *, exporter_commit: str, sizes: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """The committed record of what the round holds: hashes of the items and records, and
    salted seed commitments. It carries no seed value and no salt."""
    items = ex.read_items(item_specs)
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    records = record["records"]
    excluded_keys = load_key_lines(exclude_keys_path)
    sample, counts = draw_screening_sample(
        records, sizes=DEFAULT_SCREENING_SIZES if sizes is None else sizes,
        seed=seeds.screening_sample_seed, exclude_keys=excluded_keys)
    salt = seeds.salt

    def commit(seed: int) -> str:
        return seed_commitment(seed, salt)

    return {
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exporter_commit": exporter_commit,
        "commitment_rule": COMMITMENT_RULE,
        "rubric_sha256": _sha256_text("\n".join(ex.STATUS_DEFINITIONS_V3)),
        "claims": {
            "n_items": len(items),
            "n_no_full_text": sum(1 for it in items if it.get("rule") == "no_full_text"),
            "item_sha256": sorted(item_sha256(it) for it in items),
            "id_seed_commitment": commit(seeds.claims_id_seed),
            "row_seed_commitments": [commit(s) for s in seeds.claims_row_seeds],
        },
        "screening": {
            "record_sha256_file": hashlib.sha256(Path(record_path).read_bytes()).hexdigest(),
            "n_records_in_file": len(records),
            "n_records": len(sample),
            "n_records_left_out_by_key": sum(
                1 for r in records if not record_match_keys(r).isdisjoint(excluded_keys)),
            "strata": {s: c["drawn"] for s, c in counts.items()},
            "record_sha256": sorted(record_sha256(r) for r in sample),
            "sample_seed_commitment": commit(seeds.screening_sample_seed),
            "id_seed_commitment": commit(seeds.screening_id_seed),
            "row_seed_commitments": [commit(s) for s in seeds.screening_row_seeds],
        },
    }


def _label_problem(row_id: str, column: str, raw: Any, choices: Sequence[str]) -> str | None:
    """None when *raw* is exactly one of *choices*; else one sentence naming row and column.
    A value that matches only after ``strip().lower()`` is flagged too."""
    text = "" if raw is None else str(raw)
    if not text.strip():
        return f"{row_id}, column {column}: the cell is empty."
    canonical = {c.lower(): c for c in choices}.get(text.strip().lower())
    if canonical is None:
        return (f"{row_id}, column {column}: {text!r} is not one of "
                f"{', '.join(choices) or 'the allowed values'}.")
    if text != canonical:
        return (f"{row_id}, column {column}: {text!r} has a different case or extra spaces; "
                f"it must read {canonical!r}.")
    return None


def _yes_no_problem(label: str, raw: Any) -> str | None:
    """An Attestation yes/no answer is valid in any case and with spaces around it."""
    text = "" if raw is None else str(raw)
    if not text.strip():
        return f"{label}, column answer: the cell is empty."
    if text.strip().lower() not in ("yes", "no"):
        return f"{label}, column answer: {text!r} is not one of yes, no."
    return None


def _minutes_value(raw: Any) -> int | None:
    """The whole non-negative number of minutes in *raw*, or None when it is not one."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() and raw >= 0 else None
    if isinstance(raw, str) and _INTEGER_PATTERN.fullmatch(raw):
        return int(raw)
    return None


def _minutes_problem(row_id: str, column: str, raw: Any) -> str | None:
    """Labellers do not record time, so a blank is fine; a value that is present must be a
    whole number of minutes."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if _minutes_value(raw) is not None:
        return None
    shown = "empty" if raw is None or raw == "" else repr(raw)
    return f"{row_id}, column {column}: {shown} is not a whole number of minutes (0 or more)."


def _data_rows(wb: openpyxl.Workbook, sheet: str) -> list[tuple[str, dict[str, Any]]]:
    if sheet not in wb.sheetnames:
        raise ex.ExportError(f"the workbook has no {sheet} sheet")
    rows = wb[sheet].iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(rows, ())]
    out: list[tuple[str, dict[str, Any]]] = []
    for values in rows:
        if values and values[0] is not None and str(values[0]).strip():
            record = {h: (values[i] if i < len(values) else None) for i, h in enumerate(header)}
            out.append((str(values[0]).strip(), record))
    return out


def _attestation_answers(wb: openpyxl.Workbook) -> dict[str, tuple[int, Any]]:
    """Question text to (sheet row, answer)."""
    if "Attestation" not in wb.sheetnames:
        return {}
    found: dict[str, tuple[int, Any]] = {}
    for r, row in enumerate(wb["Attestation"].iter_rows(values_only=True), start=1):
        if r > 1 and row and isinstance(row[0], str):
            found[row[0].strip()] = (r, row[1] if len(row) > 1 else None)
    return found


def _is_blank(raw: Any) -> bool:
    """True for no answer: None or text of spaces only. The number 0 is an answer."""
    return raw is None or not str(raw).strip()


INTEGRITY_RULES: tuple[tuple[str, str, str], ...] = (
    ("ai_tool_used", "I used no AI tool", "no"),
    ("seen_before", "Have you seen any of these items", "yes"),
    ("discussed_with_others", "I did not discuss any item", "no"),
)
_INTEGRITY_MEANING = {
    "ai_tool_used": "an AI tool was used",
    "seen_before": "the items were seen before",
    "discussed_with_others": "items were discussed with others",
}


def integrity_flags(path: Path) -> list[tuple[str, str]]:
    """(key, sentence) for each Attestation answer that raises an integrity flag. A blank
    answer raises none, since validation already reports it."""
    wb = openpyxl.load_workbook(path)
    answers = _attestation_answers(wb)
    flags: list[tuple[str, str]] = []
    for key, prefix, flag_answer in INTEGRITY_RULES:
        for question, (row, raw) in answers.items():
            if question.startswith(prefix) and not _is_blank(raw):
                if str(raw).strip().lower() == flag_answer:
                    flags.append((key, (
                        f"Integrity flag: Attestation row {row}: the answer to {question!r} "
                        f"is {flag_answer}, so {_INTEGRITY_MEANING[key]}.")))
                break
    return flags


def integrity_counts(paths: Sequence[Path]) -> dict[str, Any]:
    """Counts of integrity flags over workbooks, and the 1-based positions of flagged ones.
    No file name and no labeller name is recorded."""
    counts: dict[str, Any] = {"n_workbooks": len(paths)}
    for key, _, _ in INTEGRITY_RULES:
        counts[key] = 0
    flagged: list[int] = []
    for pos, path in enumerate(paths, start=1):
        keys = {k for k, _ in integrity_flags(Path(path))}
        for k in keys:
            counts[k] += 1
        if keys:
            flagged.append(pos)
    counts["flagged_workbooks"] = flagged
    return counts


def integrity_warning_lines(counts: Mapping[str, Any]) -> list[str]:
    """One ``warning:`` line per non-zero count, for the scorers."""
    return [
        f"warning: {counts[key]} of {counts['n_workbooks']} workbooks: {_INTEGRITY_MEANING[key]}"
        for key, _, _ in INTEGRITY_RULES if counts[key]
    ]


def _attestation_findings(wb: openpyxl.Workbook) -> list[str]:
    answers = _attestation_answers(wb)
    if not answers:
        return ["Attestation: the sheet is missing or has no questions."]
    consent = next((a for q, (_, a) in answers.items()
                    if q.startswith(_CONSENT_QUESTION_PREFIX)), None)
    consent_yes = str(consent or "").strip().lower() == "yes"
    findings: list[str] = []
    for question, kind in ATTESTATION_QUESTIONS:
        if question not in answers:
            if question.startswith(_TOTAL_MINUTES_PREFIX):
                continue  # time is optional, so a workbook may omit the question
            findings.append(f"Attestation: the question {question[:40]!r} is missing.")
            continue
        row, raw = answers[question]
        label = f"Attestation row {row} ({question[:40]})"
        if kind == "yes_no":
            problem = _yes_no_problem(label, raw)
        elif question.startswith(_NAME_QUESTION_PREFIX):
            problem = (
                f"{label}, column answer: the name is empty although you agreed to be named."
                if consent_yes and _is_blank(raw) else None)
        elif question.startswith(_TOTAL_MINUTES_PREFIX):
            problem = _minutes_problem(label, "answer", raw)
        else:
            problem = (None if not _is_blank(raw)
                       else f"{label}, column answer: the cell is empty.")
        if problem:
            findings.append(problem)
    return findings


def validate_filled_workbook(
    path: Path, *, kind: Literal["claims", "screening"], criteria_choices: Sequence[str] = (),
) -> list[str]:
    """One finding per problem in a returned workbook, each naming the row id and column."""
    wb = openpyxl.load_workbook(path)
    findings: list[str] = []
    if kind == "claims":
        for row_id, row in _data_rows(wb, "Claims"):
            for column, choices in (("human_verdict", ex.HUMAN_VERDICT_CHOICES),
                                    ("confidence", CONFIDENCE_CHOICES)):
                problem = _label_problem(row_id, column, row.get(column), choices)
                if problem:
                    findings.append(problem)
            problem = _minutes_problem(row_id, "minutes_spent", row.get("minutes_spent"))
            if problem:
                findings.append(problem)
    else:
        for row_id, row in _data_rows(wb, "Screening"):
            problem = _label_problem(
                row_id, "human_decision", row.get("human_decision"), SCREENING_DECISIONS)
            if problem:
                findings.append(problem)
                continue
            decision = str(row["human_decision"]).strip().lower()
            if decision in ("exclude", "unsure"):
                raw = row.get("human_criterion")
                if criteria_choices:
                    problem = _label_problem(row_id, "human_criterion", raw, criteria_choices)
                elif _is_blank(raw):
                    problem = f"{row_id}, column human_criterion: the cell is empty."
                else:
                    problem = None
                if problem:
                    findings.append(problem)
    findings.extend(_attestation_findings(wb))
    return findings


def _run_manifest(args: argparse.Namespace) -> int:
    seeds = load_seeds(args.seeds_file)
    try:
        check_record_identity(
            args.screening_record, expect_sha256=args.expect_sha256,
            expect_git=args.expect_git)
        manifest = build_manifest(
            ex.resolve_item_specs(args.items, args.cache_dir), args.screening_record,
            args.exclude_keys, seeds, exporter_commit=args.exporter_commit)
    except ex.ExportError as err:
        print(f"ERROR: {err}")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    choices: tuple[str, ...] = ()
    if args.kind == "screening" and args.screening_record is not None:
        record = json.loads(Path(args.screening_record).read_text(encoding="utf-8"))
        choices = criterion_choices(record["criteria"])
    findings = validate_filled_workbook(args.path, kind=args.kind, criteria_choices=choices)
    for finding in findings:
        print(finding)
    flags = integrity_flags(args.path)
    for _, sentence in flags:
        print(f"warning: {sentence}")
    keys = [k for k, _ in flags]
    print("integrity flags: " + ", ".join(
        f"{key}={keys.count(key)}" for key, _, _ in INTEGRITY_RULES))
    return 1 if findings else 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_seeds = sub.add_parser("seeds", help="write a new private seeds file")
    p_seeds.add_argument("--out", type=Path, required=True)
    p_audit = sub.add_parser("audit", help="audit a built blind workbook")
    p_audit.add_argument("path", type=Path)
    p_audit.add_argument("--kind", choices=("claims", "screening"), required=True)
    p_audit.add_argument("--key", type=Path, default=None)
    p_claims = sub.add_parser("claims", help="build a blind claims workbook and its key")
    p_claims.add_argument("--items", type=Path, nargs="+", required=True)
    p_claims.add_argument("--cache-dir", type=Path, nargs="+", required=True)
    p_claims.add_argument("--year-sources", type=Path, nargs="*", default=[])
    p_claims.add_argument("--seeds-file", type=Path, required=True)
    p_claims.add_argument("--copy", choices=("1", "2", "3"), required=True)
    p_claims.add_argument("--out", type=Path, required=True)
    p_claims.add_argument("--key-out", type=Path, required=True)
    p_claims.add_argument("--select-ids", type=Path, default=None)
    p_claims.add_argument("--expect-items", type=int, default=None)
    p_claims.add_argument(
        "--sources-max-chars", type=int, default=BLIND_SOURCES_MAX_CHARS)
    p_claims.add_argument("--max-cell-chars", type=int, default=ex.DEFAULT_MAX_CELL_CHARS)
    p_scr = sub.add_parser("screening", help="build a blind screening workbook and its key")
    p_scr.add_argument("--screening-record", type=Path, required=True)
    identity = p_scr.add_mutually_exclusive_group(required=True)
    identity.add_argument("--expect-sha256")
    identity.add_argument("--expect-git", metavar="REV:PATH")
    p_scr.add_argument("--exclude-keys", type=Path, default=None,
                       help="record keys to leave out of the draw")
    p_scr.add_argument("--seeds-file", type=Path, required=True)
    p_scr.add_argument("--copy", choices=("1", "2", "3"), required=True)
    p_scr.add_argument("--out", type=Path, required=True)
    p_scr.add_argument("--key-out", type=Path, required=True)
    p_scr.add_argument("--expect-records", type=int, default=None)
    p_scr.add_argument("--max-cell-chars", type=int, default=ex.DEFAULT_MAX_CELL_CHARS)
    p_man = sub.add_parser("manifest", help="write the committed manifest of the round")
    p_man.add_argument("--items", type=Path, nargs="+", required=True)
    p_man.add_argument("--cache-dir", type=Path, nargs="+", required=True)
    p_man.add_argument("--screening-record", type=Path, required=True)
    p_man.add_argument("--exclude-keys", type=Path, default=None,
                       help="record keys to leave out of the draw")
    p_man.add_argument("--seeds-file", type=Path, required=True)
    p_man.add_argument("--exporter-commit", required=True)
    man_identity = p_man.add_mutually_exclusive_group(required=True)
    man_identity.add_argument("--expect-sha256")
    man_identity.add_argument("--expect-git", metavar="REV:PATH")
    p_man.add_argument("--out", type=Path, required=True)
    p_val = sub.add_parser("validate", help="check a filled workbook")
    p_val.add_argument("path", type=Path)
    p_val.add_argument("--kind", choices=("claims", "screening"), required=True)
    p_val.add_argument("--screening-record", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.cmd == "claims":
        return _run_claims(args)
    if args.cmd == "screening":
        return _run_screening(args)
    if args.cmd == "manifest":
        return _run_manifest(args)
    if args.cmd == "validate":
        return _run_validate(args)
    if args.cmd == "seeds":
        seeds = new_seeds()
        write_seeds_file(args.out, seeds)
        print(f"wrote {args.out}")
        print(f"claims_id_seed commitment: {seed_commitment(seeds.claims_id_seed, seeds.salt)}")
        return 0

    findings, notes = _audit(args.path, args.kind, args.key)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
