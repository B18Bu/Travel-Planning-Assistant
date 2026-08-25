from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Mapping


TOP_HOTEL_METHOD = "alitrip.btrip.hotel.distribution.search.low.price"


def build_top_params(
    *, app_key: str, timestamp: datetime, business_payload: Mapping[str, object]
) -> dict[str, str]:
    """构造固定飞猪酒店 TOP 公共参数和紧凑业务 JSON。"""

    business_json = json.dumps(
        business_payload, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "method": TOP_HOTEL_METHOD,
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "app_key": app_key,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "param_hotel_search_list_r_q": business_json,
    }


def sign_top_request(params: Mapping[str, object], secret: str) -> str:
    """按 TOP MD5 规则生成大写签名，不修改参数或暴露密钥。"""

    if "sign" in params:
        raise ValueError("签名参数不得包含已有 sign")
    try:
        keys = sorted(params, key=lambda item: str(item).encode("ascii"))
    except UnicodeEncodeError as error:
        raise ValueError("签名参数名必须为 ASCII") from error
    content = secret + "".join(f"{key}{params[key]}" for key in keys) + secret
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=True).hexdigest().upper()
