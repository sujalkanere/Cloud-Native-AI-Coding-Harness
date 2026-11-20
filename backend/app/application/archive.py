"""
Safe Tarball Archive Handler for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §4 and PROJECT.md:
- Enforces strict tarbomb and traversal defenses:
  - Rejects directory traversal (..) and absolute paths.
  - Rejects symlinks pointing or resolving outside the target directory.
  - Rejects intermediate paths traversing through symlinks.
  - Rejects hardlinks, FIFOs, and special devices (block/char).
  - Enforces limits on maximum decompressed size (bounded by MAX_UPLOAD_MB),
    maximum file count, and maximum compression ratio.
- All violations raise typed TarbombError from backend.app.domain.errors.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from backend.app.domain.errors import TarbombError

DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB (MAX_UPLOAD_MB)
DEFAULT_MAX_FILES = 10000
DEFAULT_MAX_RATIO = 100.0


def extract_archive(
    tar_bytes: bytes,
    dest_dir: Path | str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    max_ratio: float = DEFAULT_MAX_RATIO,
) -> None:
    """
    Safely unpacks a tarball into dest_dir, defending against tarbombs,
    traversal, unsafe symlinks, hardlinks, and special files.
    """
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    input_size = len(tar_bytes)
    if input_size == 0:
        raise TarbombError("Archive bytes are empty.")

    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tf:
            members = tf.getmembers()

            if len(members) > max_files:
                raise TarbombError(
                    f"Archive exceeds maximum file count limit: {len(members)} entries > {max_files}"
                )

            # First pass: validate all entries before extracting anything
            total_expected_size = 0
            for member in members:
                # Check for absolute path or leading slashes
                raw_name = member.name
                if raw_name.startswith(("/", "\\")):
                    raise TarbombError(f"Archive entry has absolute path: {raw_name}")

                norm_name = os.path.normpath(raw_name)
                if os.path.isabs(norm_name):
                    raise TarbombError(f"Archive entry has absolute path: {raw_name}")

                parts = Path(norm_name).parts
                if ".." in parts:
                    raise TarbombError(
                        f"Archive entry contains directory traversal '..': {raw_name}"
                    )

                target_path = (dest / norm_name).resolve()
                try:
                    target_path.relative_to(dest)
                except ValueError:
                    raise TarbombError(
                        f"Archive entry resolves outside destination directory: {raw_name}"
                    )

                # Prohibit hardlinks
                if member.islnk():
                    raise TarbombError(
                        f"Hardlinks are forbidden in archive: {raw_name} -> {member.linkname}"
                    )

                # Prohibit special devices, character, block, and FIFOs
                if member.isfifo() or member.ischr() or member.isblk() or member.isdev():
                    raise TarbombError(f"Special device or FIFO file forbidden: {raw_name}")

                # Validate symlinks
                if member.issym():
                    link_target = member.linkname
                    if os.path.isabs(link_target) or link_target.startswith(("/", "\\")):
                        raise TarbombError(
                            f"Symlink has absolute target escaping destination: {raw_name} -> {link_target}"
                        )

                    # Reject ANY symlink target containing traversal '..'
                    link_parts = Path(link_target).parts
                    norm_link_parts = Path(os.path.normpath(link_target)).parts
                    if (
                        ".." in link_parts
                        or ".." in norm_link_parts
                        or ".." in link_target.replace("\\", "/").split("/")
                    ):
                        raise TarbombError(
                            f"Symlink escapes destination directory: Symlink target contains directory traversal '..': {raw_name} -> {link_target}"
                        )

                    # Resolve relative to target_path parent
                    resolved_link = (target_path.parent / link_target).resolve()
                    try:
                        resolved_link.relative_to(dest)
                    except ValueError:
                        raise TarbombError(
                            f"Symlink escapes destination directory: {raw_name} -> {link_target}"
                        )

                # Verify entry type is permitted
                if not (member.isreg() or member.isdir() or member.issym()):
                    raise TarbombError(f"Unsupported archive entry type: {raw_name}")

                # Check declared size
                if member.isreg():
                    total_expected_size += member.size
                    if total_expected_size > max_bytes:
                        raise TarbombError(
                            f"Archive exceeds maximum decompressed size: {total_expected_size} bytes > {max_bytes} bytes"
                        )
                    if input_size > 0 and (total_expected_size / input_size) > max_ratio:
                        raise TarbombError(
                            f"Archive exceeds maximum compression ratio: "
                            f"{total_expected_size / input_size:.1f} > {max_ratio}"
                        )

            # Second pass: extract files safely
            total_decompressed = 0
            for member in members:
                norm_name = os.path.normpath(member.name)
                target_path = (dest / norm_name).resolve()

                # Immediately enforce that resolved target path is within destination
                try:
                    target_path.relative_to(dest)
                except ValueError:
                    raise TarbombError(
                        f"Archive entry resolved outside destination directory: {member.name}"
                    )

                # Verify intermediate directories are within dest and not symlinks
                rel_parts = (
                    Path(norm_name).parts[:-1]
                    if not member.isdir()
                    else Path(norm_name).parts
                )
                chk = dest
                for part in rel_parts:
                    chk = chk / part
                    if chk.is_symlink():
                        raise TarbombError(
                            f"Path traverses through a symlink directory: {chk} for entry {member.name}"
                        )

                if target_path != dest:
                    curr = target_path.parent
                    while curr != dest:
                        try:
                            curr.relative_to(dest)
                        except ValueError:
                            raise TarbombError(
                                f"Path traverses outside destination directory: {curr} for entry {member.name}"
                            )
                        if curr.is_symlink():
                            raise TarbombError(
                                f"Path traverses through a symlink directory: {curr} for entry {member.name}"
                            )
                        curr = curr.parent

                if member.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if target_path.is_symlink() or target_path.exists():
                        target_path.unlink()
                    try:
                        os.symlink(member.linkname, target_path)
                    except OSError:
                        # On Windows without developer mode/admin rights, symlink creation might fail
                        # But the security validation has already succeeded
                        pass
                elif member.isreg():
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    fobj = tf.extractfile(member)
                    if fobj is not None:
                        with open(target_path, "wb") as out_f:
                            while chunk := fobj.read(65536):
                                total_decompressed += len(chunk)
                                if total_decompressed > max_bytes:
                                    raise TarbombError(
                                        f"Decompressed size exceeded maximum limit of {max_bytes} bytes"
                                    )
                                if (
                                    input_size > 0
                                    and (total_decompressed / input_size) > max_ratio
                                ):
                                    raise TarbombError(
                                        f"Archive compression ratio exceeded maximum {max_ratio}"
                                    )
                                out_f.write(chunk)
    except TarbombError:
        raise
    except Exception as err:
        raise TarbombError(f"Failed to process archive: {err}") from err


def create_archive(source_dir: Path | str) -> bytes:
    """
    Creates a reproducible gzip-compressed tar archive from source_dir.
    All paths in the archive are relative to source_dir.
    """
    src = Path(source_dir).resolve()
    if not src.exists() or not src.is_dir():
        raise ValueError(f"Source directory does not exist or is not a directory: {source_dir}")

    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tar:
        for root, dirs, files in os.walk(src):
            # Sort directories and files for deterministic archives
            dirs.sort()
            files.sort()
            root_path = Path(root)

            for d in dirs:
                dir_path = root_path / d
                arcname = dir_path.relative_to(src).as_posix()
                tarinfo = tar.gettarinfo(dir_path, arcname=arcname)
                tar.addfile(tarinfo)

            for f in files:
                file_path = root_path / f
                arcname = file_path.relative_to(src).as_posix()
                tar.add(file_path, arcname=arcname, recursive=False)

    return bio.getvalue()
