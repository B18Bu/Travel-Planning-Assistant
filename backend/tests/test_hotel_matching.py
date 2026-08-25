import pytest

from app.services.hotel_matching import match_hotel, normalize_hotel_name


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("  杭州，西湖酒店！  ", "杭州西湖酒店"),
        (" Hotel, Hangzhou! ", "hotelh​​angzhou".replace("​", "")),
        ("杭州　西湖酒店", "杭州西湖酒店"),
        ("ＡＢＣ　Hotel", "abchotel"),
    ],
)
def test_normalize_hotel_name_normalizes_spaces_punctuation_and_case(raw_name, expected):
    assert normalize_hotel_name(raw_name) == expected


def test_normalize_hotel_name_removes_unicode_punctuation():
    assert normalize_hotel_name("杭州·西湖（精品）酒店—旗舰店") == "杭州西湖精品酒店旗舰店"


def test_match_hotel_requires_exact_normalized_equality():
    assert match_hotel("杭州，西湖酒店", " 杭州西湖酒店 ") is True
    assert match_hotel("Grand Hotel", "grand hotel") is True
    assert match_hotel("酒店", "大酒店") is False
    assert match_hotel("杭州酒店A", "杭州酒店AB") is False


@pytest.mark.parametrize("left, right", [("", "酒店"), ("  ", "酒店"), ("！！！", "酒店"), ("酒店", "")])
def test_match_hotel_rejects_empty_normalized_names(left, right):
    assert match_hotel(left, right) is False
