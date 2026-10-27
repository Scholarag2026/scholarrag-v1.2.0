"""The shipped sentences about what each prompt was developed on must state the record."""

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BANNED = {
    "evaluation/README.md": [
        "fixed before the runs reported",
        "disjoint from the three reported reviews",
        "held-out check",
        "pass criterion",
        "development set",
        "journal revision",
        "earlier implementation",
        "title-only pass",
        "0.822",
        "screener run",
        "the revision design",
        "built for this revision",
        "prompt-v2",
    ],
    "CHANGELOG.md": ["evaluated and reported side by side"],
    "backend/app/agents/relevance_screener_agent.py": ["the held-out set (``Fong_2021``"],
    "evaluation/screening/summarize.py": ["Development history"],
    "demo/README.md": ["the revised body, at"],
}


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_false_provenance_sentences_are_gone():
    for rel, phrases in BANNED.items():
        text = _read(rel)
        for p in phrases:
            assert p not in text, (rel, p)
    assert "fixed beforehand" not in _read("evaluation/README.md")


def test_readme_states_the_development_provenance():
    t = " ".join(_read("evaluation/README.md").split())  # wrap-insensitive
    for s in [
        "Neither prompt was fixed on held-out data.",
        "developed on two other published reviews, `Fong_2021` and `van_Dis_2020`.",
        "No reported screening or claim figure is a held-out result",
        "run rows of all three reported reviews",
        "I4, E9 and E11",
    ]:
        assert s in t


def test_protocol_readme_records_development_exposure():
    t = _read("evaluation/screening/protocols/README.md")
    sec = t.split("### Development exposure by dataset", 1)[1].split("\n## ", 1)[0]
    for ds in ["Fong_2021", "van_Dis_2020", "Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017"]:
        assert f"`{ds}`" in sec
    rows = {
        ds: next(line for line in sec.splitlines() if line.startswith(f"| `{ds}`"))
        for ds in ["Fong_2021", "van_Dis_2020", "Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017"]
    }
    assert "Development set" in rows["van_Dis_2020"] and "Development set" in rows["Fong_2021"]
    for ds in ["Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017"]:
        assert "Reported" in rows[ds] and "run rows" in rows[ds], ds
    assert "I4, E9 and E11" in rows["Smid_2020"]
    assert "not held-out results" in sec
    assert not re.search(r"20\d\d-\d\d-\d\d", sec)


def test_protocol_files_are_byte_identical_to_the_runs_of_record():
    expected = {
        "Nagtegaal_2019": "1ae48c142315",
        "Smid_2020": "5ff574cb49e8",
        "van_de_Schoot_2017": "e271b929c830",
        "van_Dis_2020": "5d6b603ae579",
        "Fong_2021": "bd28c18aa6a9",
    }
    for ds, sha in expected.items():
        raw = (REPO_ROOT / "evaluation/screening/protocols" / f"{ds}.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest()[:12] == sha, ds
