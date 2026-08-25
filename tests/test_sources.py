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
