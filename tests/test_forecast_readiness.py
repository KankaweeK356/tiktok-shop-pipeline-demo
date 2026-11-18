"""Server-side readiness: an official forecast needs five consecutive PUBLISHED months read from the runs."""
from pipeline import neon_control


class FakeCursor:
    def __init__(self, batches):
        self.batches = batches

    def execute(self, *_args):
        return None

    def fetchall(self):
        return [(b,) for b in self.batches]


def test_published_month_count_is_consecutive_from_the_first_delivery():
    names = neon_control.BATCH_BY_INDEX
    assert neon_control.published_month_count(FakeCursor([]), 1) == 0
    assert neon_control.published_month_count(FakeCursor(names[:4]), 1) == 4
    assert neon_control.published_month_count(FakeCursor(names[:5]), 1) == 5
    assert neon_control.published_month_count(FakeCursor([names[0], names[1], names[3], names[4], names[5]]), 1) == 2   # gap breaks the chain
    assert neon_control.published_month_count(FakeCursor([None, names[0]]), 1) == 1


def test_worker_refuses_to_generate_below_the_threshold():
    source = open("api/lab-worker.py", encoding="utf-8").read()
    assert "LAB_FORECAST_INSUFFICIENT_HISTORY" in source and "MIN_HISTORY_MONTHS" in source
    assert neon_control.MIN_HISTORY_MONTHS == 5
