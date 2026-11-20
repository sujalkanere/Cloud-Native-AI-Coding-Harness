"""
Unit tests for safe tarball extraction and Tarbomb / Traversal defense.

Adheres strictly to Spec §4:
- Rejects directory traversal (..)
- Rejects absolute paths (/ or \\)
- Rejects escaping symlinks (absolute and relative escaping target directory)
- Rejects hardlinks
- Rejects special device files and FIFOs
- Enforces maximum file count limit
- Enforces maximum decompressed size limit
- Enforces maximum compression ratio limit
- Verifies safe creation and round-trip extraction of legitimate archives
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from backend.app.application.archive import create_archive, extract_archive
from backend.app.domain.errors import TarbombError


def _make_tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """Helper to create a gzip tarball in memory from TarInfo objects."""
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return bio.getvalue()


def test_rejects_empty_archive(tmp_path: Path) -> None:
    with pytest.raises(TarbombError, match="Archive bytes are empty"):
        extract_archive(b"", tmp_path)


def test_rejects_corrupted_archive(tmp_path: Path) -> None:
    with pytest.raises(TarbombError, match="Failed to process archive"):
        extract_archive(b"this is not a valid tar", tmp_path)


def test_rejects_parent_directory_traversal(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="../escape.txt")
    data = b"malicious content"
    tar_bytes = _make_tar([(info, data)])

    with pytest.raises(TarbombError, match="contains directory traversal"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_nested_directory_traversal(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="sub/../../escape.txt")
    data = b"malicious content"
    tar_bytes = _make_tar([(info, data)])

    with pytest.raises(TarbombError, match="contains directory traversal"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_absolute_path_slash(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="/etc/passwd")
    data = b"root:x:0:0:root:/root:/bin/bash"
    tar_bytes = _make_tar([(info, data)])

    with pytest.raises(TarbombError, match="has absolute path"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_absolute_path_backslash(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="\\windows\\system32\\calc.exe")
    data = b"binary"
    tar_bytes = _make_tar([(info, data)])

    with pytest.raises(TarbombError, match="has absolute path"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_hardlinks(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="hardlink.txt")
    info.type = tarfile.LNKTYPE
    info.linkname = "target.txt"
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Hardlinks are forbidden"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_fifo_special_files(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="evil_fifo")
    info.type = tarfile.FIFOTYPE
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Special device or FIFO file forbidden"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_character_device_special_files(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="evil_chr")
    info.type = tarfile.CHRTYPE
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Special device or FIFO file forbidden"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_block_device_special_files(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="evil_blk")
    info.type = tarfile.BLKTYPE
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Special device or FIFO file forbidden"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_symlink_with_absolute_target(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="symlink_abs")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Symlink has absolute target"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_symlink_escaping_destination(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="sub/symlink_esc")
    info.type = tarfile.SYMTYPE
    info.linkname = "../../outside.txt"
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match="Symlink escapes destination directory"):
        extract_archive(tar_bytes, tmp_path)


def test_rejects_exceeding_max_file_count(tmp_path: Path) -> None:
    entries = []
    for i in range(15):
        info = tarfile.TarInfo(name=f"file_{i}.txt")
        entries.append((info, b"hello"))
    tar_bytes = _make_tar(entries)

    with pytest.raises(TarbombError, match="Archive exceeds maximum file count limit"):
        extract_archive(tar_bytes, tmp_path, max_files=10)


def test_rejects_exceeding_max_decompressed_size(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="large_file.bin")
    data = b"X" * 2000
    tar_bytes = _make_tar([(info, data)])

    with pytest.raises(TarbombError, match="Archive exceeds maximum decompressed size"):
        extract_archive(tar_bytes, tmp_path, max_bytes=1000)


def test_rejects_exceeding_compression_ratio(tmp_path: Path) -> None:
    info = tarfile.TarInfo(name="repetitive.txt")
    data = b"0" * 50000  # Compresses down to ~50 bytes in gzip
    tar_bytes = _make_tar([(info, data)])

    # Compression ratio will be ~1000x; set max_ratio=5.0
    with pytest.raises(TarbombError, match="Archive exceeds maximum compression ratio"):
        extract_archive(tar_bytes, tmp_path, max_ratio=5.0)


def test_extract_and_create_archive_roundtrip(tmp_path: Path) -> None:
    # Build legitimate directory structure
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("Hello from file 1", encoding="utf-8")
    sub = src_dir / "nested"
    sub.mkdir()
    (sub / "file2.py").write_text("print('hello')", encoding="utf-8")

    archive_bytes = create_archive(src_dir)
    assert len(archive_bytes) > 0

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    extract_archive(archive_bytes, dest_dir)

    assert (dest_dir / "file1.txt").read_text(encoding="utf-8") == "Hello from file 1"
    assert (dest_dir / "nested" / "file2.py").read_text(encoding="utf-8") == "print('hello')"


@pytest.mark.parametrize(
    "traversal_target",
    [
        "../foo",
        "l1/..",
        "a/b/../../c",
        "sub/../..",
    ],
)
def test_rejects_symlink_target_containing_parent_traversal(
    tmp_path: Path, traversal_target: str
) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()

    info = tarfile.TarInfo(name="evil_symlink")
    info.type = tarfile.SYMTYPE
    info.linkname = traversal_target
    tar_bytes = _make_tar([(info, None)])

    with pytest.raises(TarbombError, match=r"directory traversal '\.\.'"):
        extract_archive(tar_bytes, dest)


def test_rejects_relative_symlink_chain_traversal(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    outside_file = tmp_path / "pwned.txt"

    # Exploit payload:
    # 1. l1 -> .
    # 2. l2 -> l1/..
    # 3. l2/pwned.txt
    l1 = tarfile.TarInfo(name="l1")
    l1.type = tarfile.SYMTYPE
    l1.linkname = "."

    l2 = tarfile.TarInfo(name="l2")
    l2.type = tarfile.SYMTYPE
    l2.linkname = "l1/.."

    payload = tarfile.TarInfo(name="l2/pwned.txt")
    payload.type = tarfile.REGTYPE
    payload_data = b"PWNED_OUTSIDE!"

    tar_bytes = _make_tar([(l1, None), (l2, None), (payload, payload_data)])

    with pytest.raises(TarbombError):
        extract_archive(tar_bytes, dest)

    assert not outside_file.exists(), "Exploit succeeded: file written outside destination directory!"
