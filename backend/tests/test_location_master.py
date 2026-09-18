import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.server import SettingsBody, resolve_location_config
from backend.outbound_flow import loading_units_from_items


def _settings():
    return SettingsBody().model_dump()


def test_default_location_groups_match_operational_rules():
    settings = _settings()
    loc_19 = resolve_location_config(settings, "19/A02")
    assert loc_19["loadingGroup"] == "GRUP 1 - GBB 17-20"
    assert loc_19["unloadingGroup"] == "MANDOR 1 - GBB 17-20"

    loc_mp1 = resolve_location_config(settings, "MP1/B03")
    assert loc_mp1["loadingGroup"] == "GRUP 2 - MP1/21-24"
    assert loc_mp1["unloadingGroup"] == "MANDOR 2 - MP1/GBB 21-24"

    loc_rtr = resolve_location_config(settings, "RTR")
    assert loc_rtr["loadingGroup"] == "GRUP 3 - RTR"
    assert loc_rtr["unloadingGroup"] == ""
    assert loc_rtr["unloadingCostEnabled"] is False


def test_location_lookup_accepts_name_and_rejects_unknown():
    settings = _settings()
    assert resolve_location_config(settings, "GBB 17")["code"] == "17"
    assert resolve_location_config(settings, "Gudang Bazar")["code"] == "BAZAR"
    assert resolve_location_config(settings, "99/A01") is None


def test_loading_queue_supports_future_master_warehouse_codes():
    label, prefix = loading_units_from_items([{"stackCode": "25/A01"}])
    assert label == "Unit 25"
    assert prefix == "25"

    label, prefix = loading_units_from_items([{"stackCode": "25/A01"}, {"stackCode": "26/B02"}])
    assert label == "Unit 25 / Unit 26"
    assert prefix == "M"
