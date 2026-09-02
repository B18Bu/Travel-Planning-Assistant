from uuid import UUID, uuid4

import pytest

from app.models.documents import DocumentChunk
from app.services.chroma_store import ChromaSearchHit
from app.services.keyword_search import (
    KeywordHit,
    city_from_document_name,
    merge_ranked_hits,
    parse_query,
    region_from_document_name,
    search_chunks,
)


def make_chunk(content, *, document_name="成都旅游攻略.docx", chunk_id=None, document_id=None):
    return DocumentChunk(
        id=str(chunk_id or uuid4()),
        document_id=str(document_id or uuid4()),
        content=content,
        chunk_type="text",
        document_name=document_name,
    )


def semantic_hit(chunk, score):
    return ChromaSearchHit(
        chunk_id=UUID(str(chunk.id)),
        document_id=UUID(str(chunk.document_id)),
        score=score,
    )


def keyword_hit(chunk, score):
    return KeywordHit(
        chunk_id=UUID(str(chunk.id)),
        document_id=UUID(str(chunk.document_id)),
        score=score,
    )


# ---- parse_query ----

def test_parse_query_extracts_city_and_food_category():
    parsed = parse_query("成都美食推荐")
    assert parsed.city == "成都"
    assert parsed.categories == frozenset({"food"})
    assert parsed.significant_terms == ("美食",)


def test_parse_query_extracts_sightseeing_category():
    parsed = parse_query("三亚景点推荐")
    assert parsed.city == "三亚"
    assert parsed.categories == frozenset({"sightseeing"})
    assert parsed.significant_terms == ("景点",)


def test_parse_query_extracts_route_category():
    parsed = parse_query("西安游玩路线")
    assert parsed.city == "西安"
    assert "route" in parsed.categories
    assert parsed.significant_terms == ("游玩路线",)


def test_parse_query_without_city_or_category():
    parsed = parse_query("有什么好玩的")
    assert parsed.city is None
    assert parsed.categories == frozenset()
    assert parsed.significant_terms == ("有什么好玩的",)


def test_parse_query_matches_longest_city_name():
    parsed = parse_query("哈尔滨美食")
    assert parsed.city == "哈尔滨"


def test_parse_query_removes_city_suffix_shi():
    parsed = parse_query("成都市美食")
    assert parsed.city == "成都"
    assert "美食" in parsed.significant_terms


def test_parse_query_is_deterministic_for_multi_city_queries():
    parsed = parse_query("从北京到成都怎么走")
    assert parsed.city == "北京"


def test_search_chunks_prioritizes_travel_modifier_over_generic_intent_match():
    generic = make_chunk("成都博物馆展览介绍", document_name="成都玩法.docx")
    family = make_chunk("成都亲子互动博物馆活动", document_name="成都玩法.docx")

    hits = search_chunks(
        [generic, family],
        parse_query("成都适合亲子的博物馆"),
        limit=2,
    )

    assert [hit.chunk_id for hit in hits] == [UUID(str(family.id)), UUID(str(generic.id))]


# ---- city_from_document_name ----

def test_city_from_document_name_extracts_city_from_filename():
    assert city_from_document_name("成都旅游攻略.docx") == "成都"
    assert city_from_document_name("三亚三日游.pdf") == "三亚"
    assert city_from_document_name("西安美食指南") == "西安"


def test_city_from_document_name_returns_none_without_city():
    assert city_from_document_name("2026暑期亲子游指南.docx") is None


def test_parse_query_detects_province_region():
    parsed = parse_query("云南美食推荐")
    assert parsed.city is None
    assert parsed.region == "云南"


def test_parse_query_maps_city_to_province_region():
    parsed = parse_query("三亚景点推荐")
    assert parsed.city == "三亚"
    assert parsed.region == "海南"


def test_region_from_document_name_detects_province():
    assert region_from_document_name("贵州旅游攻略.pdf") == "贵州"
    assert region_from_document_name("云南旅游攻略.pdf") == "云南"


def test_region_from_document_name_maps_city_to_province():
    assert region_from_document_name("海南三亚旅游攻略.pdf") == "海南"
    assert region_from_document_name("昆明旅游攻略.pdf") == "云南"
    assert region_from_document_name("成都旅游攻略.pdf") == "四川"


def test_region_from_document_name_returns_none_without_region():
    assert region_from_document_name("2026暑期亲子游指南.docx") is None


def test_search_chunks_excludes_other_province_content():
    yunnan = make_chunk("云南过桥米线美食推荐", document_name="云南旅游攻略.pdf")
    sanya = make_chunk("三亚海鲜烧烤美食推荐", document_name="海南三亚旅游攻略.pdf")
    hits = search_chunks([yunnan, sanya], parse_query("云南美食推荐"))
    assert [hit.chunk_id for hit in hits] == [UUID(str(yunnan.id))]


def test_search_chunks_includes_city_chunks_of_same_province():
    guizhou = make_chunk("贵阳酸汤鱼美食推荐", document_name="贵州旅游攻略.pdf")
    kaili = make_chunk("凯里苗寨美食", document_name="凯里美食攻略.pdf")
    hits = search_chunks([guizhou, kaili], parse_query("贵州美食推荐"))
    assert len(hits) == 2


def test_merge_ranked_hits_filters_other_province_content():
    yunnan = make_chunk("云南美食", document_name="云南旅游攻略.pdf")
    sanya = make_chunk("三亚海鲜", document_name="海南三亚旅游攻略.pdf")
    merged = merge_ranked_hits(
        [semantic_hit(yunnan, 0.8), semantic_hit(sanya, 0.9)],
        (),
        region_of_chunk=lambda chunk_id: "云南" if chunk_id == UUID(str(yunnan.id)) else "海南",
        query_region="云南",
        limit=5,
    )
    assert [hit.chunk_id for hit in merged] == [UUID(str(yunnan.id))]


# ---- search_chunks ----

def test_search_chunks_excludes_other_city_chunks_when_query_names_city():
    chengdu = make_chunk("成都火锅与美食推荐", document_name="成都美食攻略.docx")
    sanya = make_chunk("三亚海鲜烧烤攻略", document_name="三亚玩法.docx")
    hits = search_chunks([chengdu, sanya], parse_query("成都美食推荐"))
    assert [hit.chunk_id for hit in hits] == [UUID(str(chengdu.id))]


def test_search_chunks_ranks_category_matching_chunks_higher():
    many = make_chunk("成都火锅 成都小吃 成都餐厅推荐", document_name="成都美食攻略.docx")
    few = make_chunk("成都火锅", document_name="成都美食攻略.docx")
    hits = search_chunks([few, many], parse_query("成都美食推荐"), limit=2)
    assert [hit.chunk_id for hit in hits] == [UUID(str(many.id)), UUID(str(few.id))]


def test_search_chunks_returns_empty_for_bare_city_query():
    chengdu = make_chunk("成都美食攻略", document_name="成都美食攻略.docx")
    hits = search_chunks([chengdu], parse_query("成都"))
    assert hits == ()


def test_search_chunks_honors_document_ids_filter():
    a = make_chunk("成都美食推荐", document_name="成都美食.docx", document_id=uuid4())
    b = make_chunk("成都美食推荐", document_name="成都美食.docx", document_id=uuid4())
    hits = search_chunks(
        [a, b],
        parse_query("成都美食推荐"),
        document_ids=(UUID(str(a.document_id)),),
    )
    assert [hit.chunk_id for hit in hits] == [UUID(str(a.id))]


def test_search_chunks_rejects_invalid_limit():
    with pytest.raises(ValueError):
        search_chunks([], parse_query("成都美食推荐"), limit=0)


# ---- merge_ranked_hits ----

def test_merge_ranked_hits_marks_both_single_source_and_orders_by_rrf():
    a = make_chunk("成都美食", document_name="成都美食.docx")
    b = make_chunk("成都火锅", document_name="成都美食.docx")
    c = make_chunk("成都小吃", document_name="成都美食.docx")
    merged = merge_ranked_hits(
        [semantic_hit(a, 0.9), semantic_hit(b, 0.7)],
        [keyword_hit(b, 3.0), keyword_hit(c, 2.0)],
        region_of_chunk=lambda chunk_id: "四川",
        query_region="四川",
        limit=3,
    )
    by_id = {hit.chunk_id: hit for hit in merged}
    assert by_id[UUID(str(a.id))].matched_by == "semantic"
    assert by_id[UUID(str(b.id))].matched_by == "both"
    assert by_id[UUID(str(c.id))].matched_by == "keyword"
    assert len(merged) == 3


def test_merge_ranked_hits_filters_other_cities_when_query_names_city():
    chengdu = make_chunk("成都美食", document_name="成都美食.docx")
    sanya = make_chunk("三亚海鲜", document_name="三亚玩法.docx")
    merged = merge_ranked_hits(
        [semantic_hit(chengdu, 0.8), semantic_hit(sanya, 0.9)],
        (),
        region_of_chunk=lambda chunk_id: "四川" if chunk_id == UUID(str(chengdu.id)) else "海南",
        query_region="四川",
        limit=5,
    )
    assert [hit.chunk_id for hit in merged] == [UUID(str(chengdu.id))]


def test_merge_ranked_hits_returns_empty_when_city_filter_excludes_everything():
    sanya = make_chunk("三亚海鲜", document_name="三亚玩法.docx")
    merged = merge_ranked_hits(
        [semantic_hit(sanya, 0.9)],
        (),
        region_of_chunk=lambda chunk_id: "海南",
        query_region="四川",
        limit=5,
    )
    assert merged == ()


def test_merge_ranked_hits_rejects_invalid_limit():
    a = make_chunk("成都美食", document_name="成都美食.docx")
    with pytest.raises(ValueError):
        merge_ranked_hits(
            [semantic_hit(a, 0.9)],
            (),
            region_of_chunk=lambda chunk_id: "四川",
            query_region="四川",
            limit=0,
        )


def test_search_chunks_honors_serialized_document_ids_filter():
    """API 请求模型将 UUID 规范为字符串，关键词检索仍必须命中指定文档。"""
    selected = make_chunk("成都美食推荐", document_name="成都美食.docx", document_id=uuid4())
    excluded = make_chunk("成都美食推荐", document_name="成都美食.docx", document_id=uuid4())

    hits = search_chunks(
        [selected, excluded],
        parse_query("成都美食推荐"),
        document_ids=(str(selected.document_id),),
    )

    assert [hit.chunk_id for hit in hits] == [UUID(str(selected.id))]
