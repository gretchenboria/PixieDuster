"""Loading writing samples from arbitrary files and folders."""

from __future__ import annotations

from pathlib import Path

import pytest

from pixieduster import sources


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "essay.txt").write_text("I start in the middle, usually.", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n\nShort, declarative.", encoding="utf-8")
    (tmp_path / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00" * 64)
    (tmp_path / "ignored.exe").write_bytes(b"MZ")
    (tmp_path / "empty.txt").write_text("   \n", encoding="utf-8")
    hidden = tmp_path / ".secretdir"
    hidden.mkdir()
    (hidden / "private.txt").write_text("should never be read", encoding="utf-8")
    return tmp_path


def test_text_becomes_samples_and_binaries_become_files(tree):
    samples, files = sources.load([tree])
    assert {s.origin for s in samples} == {"essay.txt", "notes.md"}
    assert {name for name, _, _ in files} == {"scan.png", "paper.pdf"}
    assert all(s.kind == "file" for s in samples)


def test_mimetypes_are_right(tree):
    _, files = sources.load([tree])
    types = {name: mt for name, mt, _ in files}
    assert types["scan.png"] == "image/png"
    assert types["paper.pdf"] == "application/pdf"


def test_unsupported_and_empty_are_skipped(tree):
    samples, files = sources.load([tree])
    names = {s.origin for s in samples} | {n for n, _, _ in files}
    assert "ignored.exe" not in names
    assert "empty.txt" not in names


def test_hidden_directories_are_never_read(tree):
    samples, _ = sources.load([tree])
    assert all("should never be read" not in s.text for s in samples)
    assert "private.txt" not in {s.origin for s in samples}


def test_a_single_file_works(tree):
    samples, files = sources.load([tree / "essay.txt"])
    assert len(samples) == 1 and not files


def test_missing_path_is_an_error(tmp_path):
    with pytest.raises(sources.SourceError, match="No such file"):
        sources.load([tmp_path / "nope.txt"])


def test_unsupported_single_file_is_an_error(tree):
    with pytest.raises(sources.SourceError, match="unsupported file type"):
        sources.load([tree / "ignored.exe"])


def test_empty_folder_is_an_error(tmp_path):
    (tmp_path / "sub").mkdir()
    with pytest.raises(sources.SourceError, match="no readable writing samples"):
        sources.load([tmp_path / "sub"])


def test_oversized_binary_is_reported_not_silently_dropped(tmp_path):
    (tmp_path / "huge.pdf").write_bytes(b"%PDF" + b"\x00" * 2048)
    with pytest.raises(sources.SourceError, match="over the"):
        sources.load([tmp_path], max_bytes=1024)


def test_duplicate_paths_are_collapsed(tree):
    samples, _ = sources.load([tree / "essay.txt", tree / "essay.txt"])
    assert len(samples) == 1


def test_max_files_caps_the_upload(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text(f"sample {i}", encoding="utf-8")
    assert len(sources.expand([tmp_path], max_files=5)) == 5


def test_describe_never_includes_file_bytes(tree):
    _, files = sources.load([tree])
    for line in sources.describe(files):
        assert "PNG" not in line and "%PDF" not in line
        assert "cannot be scanned" in line


# --------------------------------------------------------------------------- #
# load_triaged: the relevance-aware entry point
#
# The failure this guards against: point the tool at a real Documents folder
# and it uploads a bank statement as a "writing sample".
# --------------------------------------------------------------------------- #

ESSAY = """\
I have been thinking about the year we moved, and how little of it I can
actually remember. My mother says I cried for a week. I do not think that's
true, but she is the one who was awake for it, so who am I to argue?

What I do remember is the smell of the hallway. Wet coats, mostly. I used to
sit on the stairs and wait for my father to come home, and I would count the
cars going past to pass the time. Was that every night, or just once? I
honestly could not tell you now.
"""

STATEMENT = """\
MONTHLY ACCOUNT STATEMENT
Statement Period: 01 March 2025 to 31 March 2025
Account Number: ****4417
Routing Number: ****0021

Beginning balance                                 1402.19
03/02  CARD PURCHASE  GROCERY MART                 -84.22
03/04  DIRECT DEPOSIT PAYROLL                     2100.00
Ending balance                                    3237.69
"""


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    (tmp_path / "essay.txt").write_text(ESSAY, encoding="utf-8")
    (tmp_path / "statement.txt").write_text(STATEMENT, encoding="utf-8")
    (tmp_path / "IMG_4821.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (tmp_path / "invoice_march.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00" * 64)
    return tmp_path


def test_load_triaged_keeps_writing_and_rejects_paperwork(documents):
    kept, rejected = sources.load_triaged([documents])
    assert {i.origin for i in kept} == {"essay.txt", "IMG_4821.png"}
    assert {i.origin for i in rejected} == {"statement.txt", "invoice_march.pdf"}


def test_load_triaged_gives_every_file_a_plain_reason(documents):
    kept, rejected = sources.load_triaged([documents])
    for item in kept + rejected:
        assert item.reason and item.reason[0].islower()
        assert item.verdict in {"keep", "unsure", "drop"}


def test_load_triaged_loses_nothing(documents):
    samples, files = sources.load([documents])
    kept, rejected = sources.load_triaged([documents])
    assert len(kept) + len(rejected) == len(samples) + len(files)


def test_unpack_returns_the_shape_load_returns(documents):
    kept, _ = sources.load_triaged([documents])
    samples, files = sources.unpack(kept)
    assert [s.origin for s in samples] == ["essay.txt"]
    assert [name for name, _, _ in files] == ["IMG_4821.png"]
    assert all(isinstance(s.text, str) for s in samples)


def test_unpack_of_an_empty_selection_is_empty():
    assert sources.unpack([]) == ([], [])


def test_load_triaged_honors_the_character_budget(documents):
    kept, rejected = sources.load_triaged([documents], budget_chars=1)
    # Binaries do not spend the character budget, so the image stays.
    assert {i.origin for i in kept} == {"essay.txt", "IMG_4821.png"}
    assert len(rejected) == 2


def test_load_still_returns_everything_for_existing_callers(documents):
    """load() is unchanged: other callers rely on it sending what it finds."""
    samples, files = sources.load([documents])
    assert {s.origin for s in samples} == {"essay.txt", "statement.txt"}
    assert {n for n, _, _ in files} == {"IMG_4821.png", "invoice_march.pdf"}


def test_load_triaged_reports_a_missing_path_like_load(tmp_path):
    with pytest.raises(sources.SourceError, match="No such file"):
        sources.load_triaged([tmp_path / "nope.txt"])
