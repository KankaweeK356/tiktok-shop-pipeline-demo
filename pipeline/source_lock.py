"""Version-locked Source resolution and verification.

Every monthly Source ZIP is verified *before* anything is written to ER1/Neon:

1. ZIP SHA-256 equals the approved lock (when a lock version is active),
2. exactly the 21 contract CSVs + ``source_manifest.json`` are present,
3. embedded manifest month/batch/table set/column contract match,
4. each CSV header matches the contract,
5. when the embedded manifest carries per-file SHA-256 / row counts they must
   equal the bytes actually shipped.

The module is pure (no network, no database) so the Vercel worker, the CLI and
tests all run the very same verification for "Run Next Step" and "Run All".
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

from .schema import ROOT

LEGACY_VERSION = "classroom-source-v1"
LOCK_FILES = {
    "classroom_v2_2026_11_16": ROOT / "dashboard" / "data" / "source_lock_classroom_v2.json",
}
CONTRACT_PATH = ROOT / "dashboard" / "data" / "classroom_source_contract.json"
MANIFEST_NAME = "source_manifest.json"
BATCH_LABELS = ("initial",) + tuple(f"incremental_{i:02d}" for i in range(1, 10))


class SourceLockError(ValueError):
    """Carries a stable machine-readable code (first token of the message)."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def active_version() -> str:
    return os.environ.get("CLASSROOM_SOURCE_VERSION", LEGACY_VERSION).strip() or LEGACY_VERSION


def month_for_batch(batch: str) -> str:
    if batch not in BATCH_LABELS:
        raise SourceLockError("SOURCE_BATCH_INVALID", batch)
    return f"2026-{BATCH_LABELS.index(batch) + 1:02d}"


def load_lock(version: str) -> dict | None:
    """Return the approved lock for ``version`` or None for the legacy source."""
    if version == LEGACY_VERSION:
        return None
    path = LOCK_FILES.get(version)
    if not path or not path.is_file():
        raise SourceLockError("SOURCE_VERSION_UNKNOWN", version)
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("source_version") != version or len(lock.get("months", {})) != 10:
        raise SourceLockError("SOURCE_LOCK_INVALID", version)
    return lock


def zip_name(month: str, lock: dict | None = None) -> str:
    template = (lock or {}).get("zip_filename_template", "classroom-source-{month}.zip")
    return template.format(month=month)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def verify_source_zip(data: bytes, batch: str, *, version: str | None = None,
                      uri: str = "", origin: str = "RELEASE") -> dict:
    """Verify ``data`` and return the Source Identity. Raises SourceLockError."""
    version = version or active_version()
    month = month_for_batch(batch)
    lock = load_lock(version)
    zip_sha = sha256_bytes(data)
    lock_status = "UNLOCKED_LEGACY"
    if lock is not None:
        entry = lock["months"].get(month)
        if not entry or entry.get("batch") != batch:
            raise SourceLockError("SOURCE_LOCK_BATCH_MISMATCH", f"{month}/{batch}")
        if zip_sha != entry["zip_sha256"]:
            raise SourceLockError("SOURCE_HASH_MISMATCH", f"{month}")
        lock_status = "LOCKED_SHA256_VERIFIED"
    contract = _contract()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise SourceLockError("SOURCE_ZIP_INVALID") from error
    with archive:
        names = archive.namelist()
        expected = sorted([f"{t}.csv" for t in contract["source_tables"]] + [MANIFEST_NAME])
        if sorted(names) != expected:
            raise SourceLockError("SOURCE_TABLE_SET_MISMATCH")
        for item in archive.infolist():  # no path tricks
            if item.filename != Path(item.filename).name:
                raise SourceLockError("SOURCE_ZIP_UNSAFE_PATH", item.filename)
        manifest = json.loads(archive.read(MANIFEST_NAME))
        if manifest.get("month") != month or manifest.get("batch") != batch:
            raise SourceLockError("SOURCE_MONTH_MISMATCH", f"{manifest.get('month')}/{manifest.get('batch')}")
        if manifest.get("source_tables") != contract["source_tables"]:
            raise SourceLockError("SOURCE_ER_CONTRACT_MISMATCH")
        if manifest.get("columns") not in (None, contract["columns"]):
            raise SourceLockError("SOURCE_ER_CONTRACT_MISMATCH", "columns")
        file_hashes = manifest.get("file_sha256") or {}
        row_counts = manifest.get("file_row_counts") or {}
        files = {}
        for table in contract["source_tables"]:
            name = f"{table}.csv"
            raw = archive.read(name)
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
            if (rows[0] if rows else []) != contract["columns"].get(table):
                raise SourceLockError("SOURCE_COLUMNS_MISMATCH", table)
            digest = sha256_bytes(raw)
            if name in file_hashes and file_hashes[name] != digest:
                raise SourceLockError("SOURCE_MANIFEST_FILE_HASH_MISMATCH", name)
            data_rows = max(len(rows) - 1, 0)
            if name in row_counts and int(row_counts[name]) != data_rows:
                raise SourceLockError("SOURCE_MANIFEST_ROWCOUNT_MISMATCH", name)
            files[name] = {"sha256": digest, "rows": data_rows}
    return {
        "source_version": version, "lock_status": lock_status, "origin": origin,
        "uri": uri, "batch": batch, "month": month,
        "zip_sha256": zip_sha, "zip_bytes": len(data),
        "dataset_version": manifest.get("dataset_version"),
        "manifest_verified_files": bool(file_hashes),
        "files": files,
    }


def unpack_verified(data: bytes, target: Path) -> None:
    """Write the already verified ZIP members into ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            (target / name).write_bytes(archive.read(name))


def identity_path(source_root: Path, batch: str) -> Path:
    return Path(source_root) / f"{batch}.source_identity.json"


def write_identity(source_root: Path, identity: dict) -> None:
    identity_path(source_root, identity["batch"]).write_text(
        json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")


def read_identity(source_root: Path, batch: str) -> dict | None:
    path = identity_path(source_root, batch)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def verify_package(directory: Path, version: str = "classroom_v2_2026_11_16") -> list[dict]:
    """Verify all ten monthly ZIPs in ``directory`` (used by tests and the CLI)."""
    lock = load_lock(version)
    identities = []
    for month, entry in sorted(lock["months"].items()):
        data = (Path(directory) / zip_name(month, lock)).read_bytes()
        identities.append(verify_source_zip(data, entry["batch"], version=version,
                                            uri=str(Path(directory) / zip_name(month, lock)),
                                            origin="LOCAL_DIRECTORY"))
    return identities


if __name__ == "__main__":  # python -m pipeline.source_lock <dir>
    import sys
    for ident in verify_package(Path(sys.argv[1])):
        print(ident["month"], ident["batch"], ident["zip_sha256"], ident["lock_status"])
