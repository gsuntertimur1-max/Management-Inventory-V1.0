import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "management_inventory_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

from backend.marketplace_integration import (
    MarketplaceAccountBody,
    NormalizedMarketplaceEvent,
    NormalizedMarketplaceItem,
    _provider_key,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Shopee", "SHOPEE"),
        ("Tokopedia & Shop", "TOKOPEDIA_SHOP"),
        ("tokopedia-shop", "TOKOPEDIA_SHOP"),
        ("TikTok Shop", "TIKTOK_SHOP"),
    ],
)
def test_provider_key_is_stable_for_gateway_paths(value, expected):
    assert _provider_key(value) == expected


def test_marketplace_account_never_requires_secret_in_request_body():
    body = MarketplaceAccountBody(provider="Shopee", shopName="Toko A", shopId="shop-1")
    data = body.model_dump()
    assert "secret" not in data
    assert "token" not in data
    assert data["connectionMode"] == "API"


def test_normalized_marketplace_event_requires_positive_item_quantity():
    with pytest.raises(ValidationError):
        NormalizedMarketplaceEvent(
            eventId="evt-1",
            eventType="ORDER_CREATED",
            accountId="acc-1",
            orderNo="ORD-1",
            items=[NormalizedMarketplaceItem(marketplaceSku="SKU-1", qty=0)],
        )


def test_normalized_marketplace_event_supports_multi_sku_order():
    event = NormalizedMarketplaceEvent(
        eventId="evt-2",
        eventType="ORDER_CREATED",
        accountId="acc-1",
        orderNo="ORD-2",
        items=[
            NormalizedMarketplaceItem(marketplaceSku="SKU-A", qty=2),
            NormalizedMarketplaceItem(marketplaceSku="SKU-B", qty=3),
        ],
    )
    assert len(event.items) == 2
    assert sum(item.qty for item in event.items) == 5
