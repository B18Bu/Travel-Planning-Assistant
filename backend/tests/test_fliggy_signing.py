from datetime import datetime

import pytest

from app.errors import FliggyHotelNotConfigured, FliggyHotelUpstreamError
from app.services.fliggy_signing import build_top_params, sign_top_request


def test_top_params_contain_compact_business_json_and_fixed_method():
    params = build_top_params(
        app_key="app",
        timestamp=datetime(2026, 8, 25, 12, 0, 0),
        business_payload={"city_name": "杭州", "order": 2},
    )

    assert params["method"] == "alitrip.btrip.hotel.distribution.search.low.price"
    assert params["format"] == "json"
    assert params["v"] == "2.0"
    assert params["sign_method"] == "md5"
    assert params["timestamp"] == "2026-08-25 12:00:00"
    assert '"city_name":"杭州"' in params["param_hotel_search_list_r_q"]
    assert " " not in params["param_hotel_search_list_r_q"]


def test_md5_signature_uses_secret_wrapping_and_uppercase_hex():
    params = {"app_key": "app", "method": "demo", "timestamp": "2026-08-25 12:00:00"}

    assert sign_top_request(params, "secret") == "7ED4D301D64B06F075FF4DFA15525302"


def test_signature_does_not_mutate_params_or_expose_secret_in_result():
    params = {"app_key": "app", "method": "demo"}
    original = params.copy()

    signature = sign_top_request(params, "secret")

    assert params == original
    assert "secret" not in signature.lower()


def test_errors_expose_only_controlled_fields():
    assert str(FliggyHotelNotConfigured("secret")) == "飞猪酒店查询服务尚未配置"
    error = FliggyHotelUpstreamError(
        code="UPSTREAM_ERROR", provider_code="E401", retryable=False
    )
    assert error.code == "UPSTREAM_ERROR"
    assert error.provider_code == "E401"
    assert error.retryable is False
    assert "secret" not in repr(error)


def test_upstream_error_rejects_unknown_or_long_sensitive_codes():
    with pytest.raises(ValueError):
        FliggyHotelUpstreamError(
            code="secret-token", provider_code="provider failure with details", retryable=False
        )


def test_upstream_error_rejects_unicode_provider_codes():
    with pytest.raises(ValueError):
        FliggyHotelUpstreamError(
            code="UPSTREAM_ERROR", provider_code="错误码", retryable=False
        )


def test_upstream_error_requires_real_bool_retryable():
    with pytest.raises(TypeError):
        FliggyHotelUpstreamError(
            code="UPSTREAM_ERROR", provider_code="E401", retryable=1
        )


def test_signature_rejects_existing_sign_and_non_ascii_keys():
    with pytest.raises(ValueError):
        sign_top_request({"app_key": "app", "sign": "old"}, "secret")
    with pytest.raises(ValueError):
        sign_top_request({"应用": "value"}, "secret")
