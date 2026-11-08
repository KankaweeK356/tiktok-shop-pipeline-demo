"""Neon optional pipeline adapter contracts; no live secrets or DB writes."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from pipeline.neon_source import (
    _ordered_source_tables, _convert_insert, _convert_extract, _quoted
)


def test_neon_foreign_key_safe_order():
    names = [t.name for t in _ordered_source_tables()]
    assert len(names) == len(set(names)) == 25
    assert names.index("Dim_Product_Group") < names.index("Dim_SKU")
    assert names.index("Fact_Orders") < names.index("Fact_Order_Items")
    assert names.index("Fact_Order_Items") < names.index("Fact_FIFO_Allocation")


def test_typed_values_roundtrip():
    assert _convert_insert(1, "boolean") is True
    assert _convert_insert("2026-11-08", "date") == date(2026, 11, 8)
    assert _convert_insert("2026-11-08 10:20:30", "datetime") == datetime(2026, 11, 8, 10, 20, 30)
    assert _convert_insert("25.12", "decimal") == Decimal("25.12")
    assert _convert_extract(date(2026, 11, 8)) == "2026-11-08"
    assert _convert_extract(Decimal("25.12")) == 25.12
    assert _convert_extract(True) == 1


def test_no_arbitrary_sql_identifier():
    assert _quoted("Fact_Orders") == '"Fact_Orders"'
    with pytest.raises(ValueError):
        _quoted('Fact_Orders"; DROP TABLE x')
