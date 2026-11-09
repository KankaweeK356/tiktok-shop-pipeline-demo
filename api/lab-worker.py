"""Temporary isolated Vercel compute probe for the real classroom pipeline."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb

from pipeline.orchestrator import run_batch


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if os.getenv("VERCEL_ENV") != "preview" or parse_qs(urlsplit(self.path).query).get("probe") != ["1"]:
            self.send_error(404)
            return
        # This probe uses only bundled synthetic CSVs and temporary local files.
        # It must never connect to the 900-order Neon lab.
        os.environ.pop("NEON_DEMO_DATABASE_URL", None)
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="classroom-vercel-probe-") as temp:
                workspace = Path(temp) / "workspace"
                first = run_batch(workspace, "initial")
                second = run_batch(workspace, "incremental")
                with sqlite3.connect(workspace / "er1.sqlite") as source:
                    orders = source.execute('SELECT COUNT(*) FROM "Fact_Orders"').fetchone()[0]
                with duckdb.connect(str(workspace / "er2.duckdb"), read_only=True) as warehouse:
                    paid_items = warehouse.execute('SELECT COUNT(*) FROM "Fact_Sales_Order_Item"').fetchone()[0]
                result = {
                    "isolated": True,
                    "initial": first["status"],
                    "incremental": second["status"],
                    "initial_pipeline_seconds": first["elapsed_seconds"],
                    "incremental_pipeline_seconds": second["elapsed_seconds"],
                    "orders_after_run2": orders,
                    "warehouse_paid_items": paid_items,
                    "total_seconds": round(time.perf_counter() - started, 3),
                }
                if first["status"] != "SUCCESS" or second["status"] != "SUCCESS" or orders != 900:
                    raise RuntimeError("Isolated pipeline validation failed")
            body = json.dumps(result).encode()
            self.send_response(200)
        except Exception as error:
            body = json.dumps({"error": type(error).__name__}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

