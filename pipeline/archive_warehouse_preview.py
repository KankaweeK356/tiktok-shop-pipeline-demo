"""Publish real preview rows from the ALREADY archived DuckDB Warehouse.

This non-destructive job downloads the verified private DuckDB file, checks its
SHA256 and reconciles paid item count/Net Revenue against live Neon, then
queries each physical Warehouse table/view and uploads a small JSON preview.

It NEVER regenerates, overwrites, resets, or mutates Source/Analytics data.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, date, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import duckdb
import psycopg

from .schema import ROOT
from .archive_recovery import (
    ORIGINAL_GITHUB_RUN, BUCKET, _start_session, _upload_once, _api_call,
    _source_total,
)


def _safe_cell(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return "<binary>"
    if hasattr(value, "item"):
        return _safe_cell(value.item())
    return value


def _table_name(name):
    if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError("Unsafe Warehouse identifier")
    return '"' + name + '"'


def main():
    database_url=os.environ.get("NEON_DEMO_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Protected Neon demo Database Secret is required")
    with psycopg.connect(database_url) as conn:
        if _source_total(conn)!=(900,1147,"417092.85"):
            raise AssertionError("Neon no longer matches validated archive")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT artifact_uri,content_sha256,size_bytes
                  FROM demo_control.pipeline_artifacts
                 WHERE artifact_type='WAREHOUSE'
                   AND artifact_uri LIKE %s
                 ORDER BY created_at DESC LIMIT 1
            """,(f"neon-storage://{BUCKET}/recovery/cycle-1/github-{ORIGINAL_GITHUB_RUN}/%",))
            saved=cur.fetchone()
            if not saved:
                raise RuntimeError("The existing permanent DuckDB archive is missing")
            uri,expected_digest,expected_size=saved
            cur.execute("""
                SELECT COUNT(*) FROM demo_control.pipeline_artifacts
                 WHERE artifact_type='REPORT' AND artifact_uri LIKE %s
            """,(f"neon-storage://{BUCKET}/recovery/cycle-1/github-{ORIGINAL_GITHUB_RUN}/%/warehouse_preview.json",))
            if cur.fetchone()[0]>0:
                print("Warehouse preview already archived; no duplicate upload")
                return
        shared_prefix=f"recovery/cycle-1/github-{ORIGINAL_GITHUB_RUN}/"
        token,run_id=_start_session(conn,shared_prefix)

    path_prefix=f"neon-storage://{BUCKET}/"
    if not uri.startswith(path_prefix):
        raise RuntimeError("Archived URI is outside private storage")
    key=uri[len(path_prefix):]
    ticket=_api_call(token,key,"download")
    request=urllib.request.Request(ticket["url"],method="GET")
    dest=ROOT/"output"/"warehouse_preview"/"er2.duckdb"
    dest.parent.mkdir(parents=True,exist_ok=True)
    try:
        with urllib.request.urlopen(request,timeout=120) as response:
            data=response.read()
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Private DuckDB download HTTP {err.code}") from None
    if len(data)!=int(expected_size) or hashlib.sha256(data).hexdigest()!=expected_digest:
        raise AssertionError("Downloaded DuckDB content did not match Neon artifact SHA256")
    dest.write_bytes(data)

    conn=duckdb.connect(str(dest),read_only=True)
    try:
        count, net=conn.execute(
            'SELECT COUNT(*),ROUND(SUM("Net_Revenue"),2) FROM "Fact_Sales_Order_Item"'
        ).fetchone()
        if int(count)!=1147 or abs(float(net)-417092.85)>0.011:
            raise AssertionError("Warehouse content disagrees with current Neon totals")
        tables=[]
        refs=conn.execute("""
            SELECT table_name,table_type
              FROM information_schema.tables WHERE table_schema='main'
             ORDER BY table_type,table_name
        """).fetchall()
        for name,typ in refs:
            quoted=_table_name(name)
            count=conn.execute("SELECT COUNT(*) FROM "+quoted).fetchone()[0]
            cursor=conn.execute("SELECT * FROM "+quoted+" LIMIT 5")
            columns=[col[0] for col in cursor.description]
            rows=[
                {col:_safe_cell(val) for col,val in zip(columns,row)}
                for row in cursor.fetchall()
            ]
            tables.append({"name":name,"type":typ,"rows":int(count),
                           "columns":columns,"preview":rows})
    finally:
        conn.close()
    payload={
        "classification":"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "source":"ALREADY_ARCHIVED_RECONSTRUCTED_DUCKDB",
        "source_archive_sha256":expected_digest,
        "original_github_run":ORIGINAL_GITHUB_RUN,
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "warehouse_paid_items":1147,
        "warehouse_net_revenue":417092.85,
        "warehouse_table_previews":tables,
        "note":"Queried the exact preserved DuckDB bytes from private Neon Object Storage; this Warehouse was reconstructed after the original run."
    }
    result=dest.parent/"warehouse_preview.json"
    result.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    new_key=shared_prefix+uuid4().hex+"/warehouse_preview.json"
    digest,size=_upload_once(result,token,new_key)
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO demo_control.pipeline_artifacts
                  (run_id,stage_name,artifact_type,artifact_uri,content_sha256,records_count,size_bytes)
                VALUES (%s,'load','REPORT',%s,%s,%s,%s)
            """,(run_id,f"neon-storage://{BUCKET}/{new_key}",digest,len(tables),size))
            cur.execute("UPDATE demo_control.upload_sessions SET revoked=TRUE WHERE token_sha256=%s",
                        (hashlib.sha256(token.encode("ascii")).hexdigest(),))
    print(json.dumps({"status":"ARCHIVED_PREVIEW","warehouse_tables":len(tables),
                      "warehouse_paid_items":1147,"source":"EXISTING_PRIVATE_DUCKDB_BYTES"}))


if __name__=="__main__":
    main()
