"""Object storage with write-once semantics (S3-compatible: Neon Object Storage in production, a local directory in tests/dev)."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path


class StoreError(RuntimeError):
    pass


class LocalDirStore:
    def __init__(self, root):
        self.root = Path(root)

    def _p(self, key):
        return self.root / key

    def exists(self, key):
        return self._p(key).is_file()

    def get(self, key) -> bytes:
        return self._p(key).read_bytes()

    def put(self, key, data: bytes):
        path = self._p(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

    def list(self, prefix):
        base = self._p(prefix)
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file()) if base.exists() else []


class S3Store:
    """boto3 S3 client (the same client the worker already builds for the lab bucket)."""
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def exists(self, key):
        head = getattr(self.client, "head_object", None)          # clients without HEAD (test doubles) fall back to a GET
        try:
            if head is not None:
                head(Bucket=self.bucket, Key=key)
            else:
                self.client.get_object(Bucket=self.bucket, Key=key)
            return True
        except KeyError:
            return False
        except Exception as error:                                  # botocore ClientError: 404 / NoSuchKey
            if any(token in str(error) for token in ("404", "Not Found", "NoSuchKey")):
                return False
            raise

    def get(self, key) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def put(self, key, data: bytes):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def list(self, prefix):
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix, **({"ContinuationToken": token} if token else {})}
            page = self.client.list_objects_v2(**kw)
            out += [o["Key"] for o in page.get("Contents", [])]
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated"):
                return sorted(out)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_new(store, key: str, data: bytes) -> str:
    """Write once. An existing key is never overwritten: identical content is accepted (idempotent), different content is an error."""
    if store.exists(key):
        if sha256(store.get(key)) == sha256(data):
            return "EXISTS_IDENTICAL"
        raise StoreError(f"IMMUTABLE_KEY_EXISTS_WITH_DIFFERENT_CONTENT: {key}")
    store.put(key, data)
    return "CREATED"


def dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8")


def parquet_bytes(rows: list[dict]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buf, compression="snappy")
    return buf.getvalue()


def read_parquet(data: bytes) -> list[dict]:
    import pyarrow.parquet as pq
    return pq.read_table(io.BytesIO(data)).to_pylist()
