import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.work_time_costs import handling_fee, holiday_from_settings, work_split

WIB = timezone(timedelta(hours=7))


def dt(hour, minute):
    return datetime(2026, 9, 21, hour, minute, tzinfo=WIB)


def test_work_before_cutoff_is_normal():
    split = work_split(dt(15, 0), dt(15, 55), 25)
    assert split == {"regularQty": 25.0, "overtimeQty": 0.0, "workStatus": "NORMAL"}


def test_work_starting_after_cutoff_is_full_overtime():
    split = work_split(dt(16, 1), dt(16, 45), 20)
    assert split == {"regularQty": 0.0, "overtimeQty": 20.0, "workStatus": "LEMBUR_PENUH"}


def test_cross_cutoff_requires_and_uses_manual_split():
    with pytest.raises(HTTPException, match="pukul 16.00"):
        work_split(dt(15, 30), dt(16, 40), 25)

    split = work_split(dt(15, 30), dt(16, 40), 25, normal_before_cutoff=10)
    assert split == {"regularQty": 10.0, "overtimeQty": 15.0, "workStatus": "LEMBUR_PARSIAL"}


def test_partial_overtime_fee_applies_base_to_all_and_overtime_only_to_remainder():
    product = {
        "loadingFeeLabor": 100,
        "loadingOvertimeLabor": 30,
        "loadingFeeDaily": 0,
        "loadingFeeWarehouse": 0,
        "loadingFeeChargeMode": "PENGAMBIL",
    }
    fee = handling_fee(product, 25, 15, dt(16, 40), "loading", "PENGAMBIL")
    assert fee["labor"] == 2950
    assert fee["total"] == 2950
    assert fee["chargeable"] == 2950
    assert fee["regularQty"] == 10
    assert fee["overtimeQty"] == 15
    assert fee["workStatus"] == "LEMBUR_PARSIAL"


def test_split_rejects_normal_quantity_above_total():
    with pytest.raises(HTTPException, match="antara 0 dan 25"):
        work_split(dt(15, 30), dt(16, 40), 25, normal_before_cutoff=26)


def test_master_weekday_holiday():
    weekday = datetime(2026, 12, 25, 15, 0, tzinfo=WIB)
    assert holiday_from_settings(weekday, [{"date": "2026-12-25", "active": True}]) is True


def test_inactive_master_holiday():
    weekday = datetime(2026, 12, 24, 15, 0, tzinfo=WIB)
    assert holiday_from_settings(weekday, [{"date": "2026-12-24", "active": False}]) is False
