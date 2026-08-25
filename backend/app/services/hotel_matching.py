from __future__ import annotations

import unicodedata


def normalize_hotel_name(name: str) -> str:
    """规范化酒店名称，用于严格名称匹配。"""
    normalized = unicodedata.normalize("NFKC", name).lower()
    return "".join(
        character
        for character in normalized
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


def match_hotel(left_name: str, right_name: str) -> bool:
    """仅当两个非空规范化酒店名称完全相等时匹配。"""
    left = normalize_hotel_name(left_name)
    right = normalize_hotel_name(right_name)
    return bool(left and right and left == right)
