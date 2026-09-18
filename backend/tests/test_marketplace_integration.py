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
    _connection_env_status,
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


def test_connection_status_exposes_only_boolean_secret_readiness(monkeypatch):
    monkeypatch.setenv("MARKETPLACE_SHOPEE_APP_ID", "app-123")
    monkeypatch.setenv("MARKETPLACE_SHOPEE_APP_SECRET", "super-secret")
    monkeypatch.setenv("MARKETPLACE_SHOPEE_ACCESS_TOKEN", "token-value")
    monkeypatch.setenv("MARKETPLACE_WEBHOOK_KEY_SHOPEE", "hook-secret")
    status = _connection_env_status("Shopee")
    assert status["clientConfigured"] is True
    assert status["secretConfigured"] is True
    assert status["tokenConfigured"] is True
    assert status["gatewayConfigured"] is True
    serialized = str(status)
    assert "super-secret" not in serialized
    assert "token-value" not in serialized
    assert "hook-secret" not in serialized


from backend.marketplace_oauth import (
    _credential_key,
    _decrypt_token_bundle,
    _encrypt_token_bundle,
    _shopee_signature,
    _tiktok_sign,
)


def test_tokopedia_and_tiktok_share_credential_family():
    assert _credential_key("Tokopedia & Shop") == "TIKTOK_SHOP"
    assert _credential_key("TikTok Shop") == "TIKTOK_SHOP"
    assert _credential_key("Shopee") == "SHOPEE"


def test_marketplace_tokens_are_encrypted_at_rest():
    bundle = {"access_token": "access-secret", "refresh_token": "refresh-secret", "expire_in": 3600}
    encrypted = _encrypt_token_bundle(bundle)
    assert "access-secret" not in encrypted
    assert "refresh-secret" not in encrypted
    assert _decrypt_token_bundle(encrypted) == bundle


def test_shopee_signature_is_stable_and_secret_not_returned():
    signature = _shopee_signature("12345", "partner-secret", "/api/v2/auth/token/get", 1700000000)
    assert len(signature) == 64
    assert signature == _shopee_signature("12345", "partner-secret", "/api/v2/auth/token/get", 1700000000)
    assert "partner-secret" not in signature


def test_tiktok_signature_changes_with_body():
    query = {"app_key": "abc", "timestamp": 1700000000, "shop_cipher": "cipher"}
    first = _tiktok_sign("/event/202309/webhooks", query, '{"event_type":"ORDER_STATUS_CHANGE"}', "secret")
    second = _tiktok_sign("/event/202309/webhooks", query, '{"event_type":"PACKAGE_UPDATE"}', "secret")
    assert len(first) == 64
    assert first != second
