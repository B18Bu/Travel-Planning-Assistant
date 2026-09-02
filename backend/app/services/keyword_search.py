from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Sequence
import re
from typing import Literal
from uuid import UUID

from app.models.documents import DocumentChunk
from app.services.chroma_store import ChromaSearchHit


# 预置常用中国城市与热门旅游目的地，用于城市名敏感的关键词检索。
CITIES = frozenset({
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 河北
    "石家庄", "唐山", "秦皇岛", "邯郸", "保定", "承德", "廊坊", "沧州", "张家口",
    # 山西
    "太原", "大同", "晋中", "临汾", "运城", "平遥", "忻州",
    # 内蒙古
    "呼和浩特", "包头", "鄂尔多斯", "呼伦贝尔", "赤峰", "乌兰察布",
    # 辽宁
    "沈阳", "大连", "鞍山", "抚顺", "丹东", "锦州", "营口", "盘锦", "葫芦岛",
    # 吉林
    "长春", "吉林", "延吉", "松原", "四平", "通化",
    # 黑龙江
    "哈尔滨", "齐齐哈尔", "大庆", "牡丹江", "佳木斯", "黑河", "漠河",
    # 江苏
    "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城",
    "扬州", "镇江", "泰州", "宿迁", "昆山",
    # 浙江
    "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山",
    "台州", "丽水", "义乌",
    # 安徽
    "合肥", "芜湖", "蚌埠", "马鞍山", "安庆", "黄山", "阜阳", "滁州", "六安",
    "亳州", "池州", "宣城",
    # 福建
    "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德",
    "武夷山", "鼓浪屿",
    # 江西
    "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春",
    "抚州", "上饶", "婺源", "庐山",
    # 山东
    "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安",
    "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽", "曲阜",
    # 河南
    "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
    "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店",
    # 湖北
    "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州",
    "黄冈", "咸宁", "随州", "恩施", "神农架",
    # 湖南
    "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳",
    "郴州", "永州", "怀化", "娄底", "凤凰", "韶山",
    # 广东
    "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门",
    "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山",
    "潮州", "揭阳", "云浮",
    # 广西
    "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林",
    "百色", "贺州", "河池", "来宾", "崇左", "阳朔",
    # 海南
    "海口", "三亚", "儋州", "琼海", "万宁", "陵水",
    # 四川
    "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江",
    "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳",
    "阿坝", "甘孜", "凉山", "西昌", "九寨沟", "峨眉山", "都江堰", "康定",
    # 贵州
    "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "凯里", "荔波", "西江",
    # 云南
    "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "大理",
    "楚雄", "红河", "文山", "西双版纳", "德宏", "香格里拉", "泸沽湖",
    # 西藏
    "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里",
    # 陕西
    "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康",
    "商洛",
    # 甘肃
    "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉",
    "庆阳", "定西", "陇南", "敦煌", "临夏", "甘南",
    # 青海
    "西宁", "海东", "海北", "黄南", "果洛", "玉树", "海西", "德令哈", "格尔木",
    # 宁夏
    "银川", "石嘴山", "吴忠", "固原", "中卫",
    # 新疆
    "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "巴音郭楞", "阿克苏",
    "喀什", "和田", "伊犁", "塔城", "阿勒泰", "喀纳斯",
    # 港澳台
    "香港", "澳门", "台北", "高雄", "台中", "台南", "新竹", "基隆", "嘉义",
    "花莲", "台东", "屏东",
})

# 省、自治区与台湾（直辖市与港澳已含于 CITIES），用于省份级查询/文档的省域判定。
PROVINCES = frozenset({
    "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽",
    "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "四川",
    "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆", "台湾",
})

# 城市 → 省份 映射；城市硬过滤在省域层级执行，使「云南」可召回省内各城市内容。
CITY_TO_PROVINCE = {
    # 直辖市 → 自身
    "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
    # 河北
    "石家庄": "河北", "唐山": "河北", "秦皇岛": "河北", "邯郸": "河北",
    "保定": "河北", "承德": "河北", "廊坊": "河北", "沧州": "河北", "张家口": "河北",
    # 山西
    "太原": "山西", "大同": "山西", "晋中": "山西", "临汾": "山西", "运城": "山西",
    "平遥": "山西", "忻州": "山西",
    # 内蒙古
    "呼和浩特": "内蒙古", "包头": "内蒙古", "鄂尔多斯": "内蒙古", "呼伦贝尔": "内蒙古",
    "赤峰": "内蒙古", "乌兰察布": "内蒙古",
    # 辽宁
    "沈阳": "辽宁", "大连": "辽宁", "鞍山": "辽宁", "抚顺": "辽宁", "丹东": "辽宁",
    "锦州": "辽宁", "营口": "辽宁", "盘锦": "辽宁", "葫芦岛": "辽宁",
    # 吉林
    "长春": "吉林", "吉林": "吉林", "延吉": "吉林", "松原": "吉林", "四平": "吉林",
    "通化": "吉林",
    # 黑龙江
    "哈尔滨": "黑龙江", "齐齐哈尔": "黑龙江", "大庆": "黑龙江", "牡丹江": "黑龙江",
    "佳木斯": "黑龙江", "黑河": "黑龙江", "漠河": "黑龙江",
    # 江苏
    "南京": "江苏", "无锡": "江苏", "徐州": "江苏", "常州": "江苏", "苏州": "江苏",
    "南通": "江苏", "连云港": "江苏", "淮安": "江苏", "盐城": "江苏", "扬州": "江苏",
    "镇江": "江苏", "泰州": "江苏", "宿迁": "江苏", "昆山": "江苏",
    # 浙江
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "湖州": "浙江",
    "绍兴": "浙江", "金华": "浙江", "衢州": "浙江", "舟山": "浙江", "台州": "浙江",
    "丽水": "浙江", "义乌": "浙江",
    # 安徽
    "合肥": "安徽", "芜湖": "安徽", "蚌埠": "安徽", "马鞍山": "安徽", "安庆": "安徽",
    "黄山": "安徽", "阜阳": "安徽", "滁州": "安徽", "六安": "安徽", "亳州": "安徽",
    "池州": "安徽", "宣城": "安徽",
    # 福建
    "福州": "福建", "厦门": "福建", "莆田": "福建", "三明": "福建", "泉州": "福建",
    "漳州": "福建", "南平": "福建", "龙岩": "福建", "宁德": "福建", "武夷山": "福建",
    "鼓浪屿": "福建",
    # 江西
    "南昌": "江西", "景德镇": "江西", "萍乡": "江西", "九江": "江西", "新余": "江西",
    "鹰潭": "江西", "赣州": "江西", "吉安": "江西", "宜春": "江西", "抚州": "江西",
    "上饶": "江西", "婺源": "江西", "庐山": "江西",
    # 山东
    "济南": "山东", "青岛": "山东", "淄博": "山东", "枣庄": "山东", "东营": "山东",
    "烟台": "山东", "潍坊": "山东", "济宁": "山东", "泰安": "山东", "威海": "山东",
    "日照": "山东", "临沂": "山东", "德州": "山东", "聊城": "山东", "滨州": "山东",
    "菏泽": "山东", "曲阜": "山东",
    # 河南
    "郑州": "河南", "开封": "河南", "洛阳": "河南", "平顶山": "河南", "安阳": "河南",
    "鹤壁": "河南", "新乡": "河南", "焦作": "河南", "濮阳": "河南", "许昌": "河南",
    "漯河": "河南", "三门峡": "河南", "南阳": "河南", "商丘": "河南", "信阳": "河南",
    "周口": "河南", "驻马店": "河南",
    # 湖北
    "武汉": "湖北", "黄石": "湖北", "十堰": "湖北", "宜昌": "湖北", "襄阳": "湖北",
    "鄂州": "湖北", "荆门": "湖北", "孝感": "湖北", "荆州": "湖北", "黄冈": "湖北",
    "咸宁": "湖北", "随州": "湖北", "恩施": "湖北", "神农架": "湖北",
    # 湖南
    "长沙": "湖南", "株洲": "湖南", "湘潭": "湖南", "衡阳": "湖南", "邵阳": "湖南",
    "岳阳": "湖南", "常德": "湖南", "张家界": "湖南", "益阳": "湖南", "郴州": "湖南",
    "永州": "湖南", "怀化": "湖南", "娄底": "湖南", "凤凰": "湖南", "韶山": "湖南",
    # 广东
    "广州": "广东", "深圳": "广东", "珠海": "广东", "汕头": "广东", "佛山": "广东",
    "韶关": "广东", "湛江": "广东", "肇庆": "广东", "江门": "广东", "茂名": "广东",
    "惠州": "广东", "梅州": "广东", "汕尾": "广东", "河源": "广东", "阳江": "广东",
    "清远": "广东", "东莞": "广东", "中山": "广东", "潮州": "广东", "揭阳": "广东",
    "云浮": "广东",
    # 广西
    "南宁": "广西", "柳州": "广西", "桂林": "广西", "梧州": "广西", "北海": "广西",
    "防城港": "广西", "钦州": "广西", "贵港": "广西", "玉林": "广西", "百色": "广西",
    "贺州": "广西", "河池": "广西", "来宾": "广西", "崇左": "广西", "阳朔": "广西",
    # 海南
    "海口": "海南", "三亚": "海南", "儋州": "海南", "琼海": "海南", "万宁": "海南",
    "陵水": "海南",
    # 四川
    "成都": "四川", "自贡": "四川", "攀枝花": "四川", "泸州": "四川", "德阳": "四川",
    "绵阳": "四川", "广元": "四川", "遂宁": "四川", "内江": "四川", "乐山": "四川",
    "南充": "四川", "眉山": "四川", "宜宾": "四川", "广安": "四川", "达州": "四川",
    "雅安": "四川", "巴中": "四川", "资阳": "四川", "阿坝": "四川", "甘孜": "四川",
    "凉山": "四川", "西昌": "四川", "九寨沟": "四川", "峨眉山": "四川",
    "都江堰": "四川", "康定": "四川",
    # 贵州
    "贵阳": "贵州", "六盘水": "贵州", "遵义": "贵州", "安顺": "贵州", "毕节": "贵州",
    "铜仁": "贵州", "凯里": "贵州", "荔波": "贵州", "西江": "贵州",
    # 云南
    "昆明": "云南", "曲靖": "云南", "玉溪": "云南", "保山": "云南", "昭通": "云南",
    "丽江": "云南", "普洱": "云南", "临沧": "云南", "大理": "云南", "楚雄": "云南",
    "红河": "云南", "文山": "云南", "西双版纳": "云南", "德宏": "云南",
    "香格里拉": "云南", "泸沽湖": "云南",
    # 西藏
    "拉萨": "西藏", "日喀则": "西藏", "昌都": "西藏", "林芝": "西藏", "山南": "西藏",
    "那曲": "西藏", "阿里": "西藏",
    # 陕西
    "西安": "陕西", "铜川": "陕西", "宝鸡": "陕西", "咸阳": "陕西", "渭南": "陕西",
    "延安": "陕西", "汉中": "陕西", "榆林": "陕西", "安康": "陕西", "商洛": "陕西",
    # 甘肃
    "兰州": "甘肃", "嘉峪关": "甘肃", "金昌": "甘肃", "白银": "甘肃", "天水": "甘肃",
    "武威": "甘肃", "张掖": "甘肃", "平凉": "甘肃", "酒泉": "甘肃", "庆阳": "甘肃",
    "定西": "甘肃", "陇南": "甘肃", "敦煌": "甘肃", "临夏": "甘肃", "甘南": "甘肃",
    # 青海
    "西宁": "青海", "海东": "青海", "海北": "青海", "黄南": "青海", "果洛": "青海",
    "玉树": "青海", "海西": "青海", "德令哈": "青海", "格尔木": "青海",
    # 宁夏
    "银川": "宁夏", "石嘴山": "宁夏", "吴忠": "宁夏", "固原": "宁夏", "中卫": "宁夏",
    # 新疆
    "乌鲁木齐": "新疆", "克拉玛依": "新疆", "吐鲁番": "新疆", "哈密": "新疆",
    "昌吉": "新疆", "巴音郭楞": "新疆", "阿克苏": "新疆", "喀什": "新疆",
    "和田": "新疆", "伊犁": "新疆", "塔城": "新疆", "阿勒泰": "新疆", "喀纳斯": "新疆",
    # 港澳台
    "香港": "香港", "澳门": "澳门",
    "台北": "台湾", "高雄": "台湾", "台中": "台湾", "台南": "台湾", "新竹": "台湾",
    "基隆": "台湾", "嘉义": "台湾", "花莲": "台湾", "台东": "台湾", "屏东": "台湾",
}

# 用户意图分类 → 领域关键词；城市为硬过滤，分类关键词用于针对性计分。
INTENT_KEYWORDS = {
    "route": frozenset({
        "路线", "行程", "线路", "攻略", "安排", "计划", "玩法", "怎么玩",
        "路线图", "行程安排",
    }),
    "food": frozenset({
        "美食", "小吃", "餐厅", "饭店", "火锅", "烧烤", "菜系", "饮食",
        "餐馆", "味道", "特色菜", "吃",
    }),
    "sightseeing": frozenset({
        "景点", "景区", "打卡", "门票", "游览", "观光", "必去", "名胜",
        "博物馆", "公园", "网红",
    }),
}

# 去除后不参与关键词计分的高频词；城市名与「市」后缀单独处理。
STOPWORDS = ("推荐", "一下", "怎么样", "请问", "我想", "要去", "哪些", "吗", "呢", "吧")

TRAVEL_MODIFIERS = (
    "亲子", "儿童", "老人", "情侣", "室内", "雨天", "避暑", "慢游",
    "自驾", "徒步", "夜游", "摄影", "露营", "文化", "历史",
)


@dataclass(frozen=True)
class ParsedQuery:
    """从用户查询解析出的城市、省域、意图分类与关键词计分片段。"""

    query: str
    city: str | None
    region: str | None
    categories: frozenset[str]
    significant_terms: tuple[str, ...]


@dataclass(frozen=True)
class KeywordHit:
    """关键词检索命中。"""

    chunk_id: UUID
    document_id: UUID
    score: float


@dataclass(frozen=True)
class RankedHit:
    """混合检索融合后的命中。"""

    chunk_id: UUID
    document_id: UUID
    matched_by: Literal["semantic", "keyword", "both"]


def parse_query(query: str) -> ParsedQuery:
    """从查询中提取城市与省域（最长优先、等长取先出现）与意图分类。"""
    city = _match_city(query)
    region = CITY_TO_PROVINCE.get(city) if city is not None else _match_province(query)
    categories = frozenset(
        name
        for name, keywords in INTENT_KEYWORDS.items()
        if any(keyword in query for keyword in keywords)
    )
    return ParsedQuery(
        query=query,
        city=city,
        region=region,
        categories=categories,
        significant_terms=_significant_terms(query, city),
    )


def city_from_document_name(document_name: str) -> str | None:
    """从文档名提取城市（如《成都旅游攻略.docx》→ 成都），未命中返回 None。"""
    return _match_city(document_name)


def region_from_document_name(document_name: str) -> str | None:
    """从文档名提取省域（城市归省、省份直判），未命中返回 None。"""
    city = _match_city(document_name)
    if city is not None:
        return CITY_TO_PROVINCE.get(city, city)
    return _match_province(document_name)


def _match_province(text: str) -> str | None:
    best: str | None = None
    best_length = -1
    best_index: int | None = None
    for name in PROVINCES:
        index = text.find(name)
        if index < 0:
            continue
        if len(name) > best_length or (
            len(name) == best_length
            and best_index is not None
            and index < best_index
        ):
            best = name
            best_length = len(name)
            best_index = index
    return best


def search_chunks(
    chunks: Sequence[DocumentChunk],
    parsed: ParsedQuery,
    *,
    document_ids: Sequence[UUID] = (),
    limit: int = 5,
) -> tuple[KeywordHit, ...]:
    """按城市硬过滤 + 分类/查询词计分，返回关键词检索命中。"""
    _validate_limit(limit)
    wanted = {UUID(str(document_id)) for document_id in document_ids}
    hits: list[KeywordHit] = []
    for chunk in chunks:
        if wanted and UUID(str(chunk.document_id)) not in wanted:
            continue
        score = _score_chunk(chunk, parsed)
        if score > 0:
            hits.append(
                KeywordHit(
                    chunk_id=UUID(str(chunk.id)),
                    document_id=UUID(str(chunk.document_id)),
                    score=score,
                )
            )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return tuple(hits[:limit])


def merge_ranked_hits(
    semantic: Sequence[ChromaSearchHit],
    keyword: Sequence[KeywordHit],
    *,
    region_of_chunk: Callable[[UUID], str | None],
    query_region: str | None,
    limit: int = 5,
) -> tuple[RankedHit, ...]:
    """RRF 融合语义与关键词命中；查询含城市/省域时硬过滤到目标省域。"""
    _validate_limit(limit)
    rrf: dict[UUID, float] = {}
    document_of_chunk: dict[UUID, UUID] = {}
    semantic_ids: set[UUID] = set()
    keyword_ids: set[UUID] = set()
    for index, hit in enumerate(semantic):
        chunk_id = UUID(str(hit.chunk_id))
        document_id = UUID(str(hit.document_id))
        document_of_chunk[chunk_id] = document_id
        semantic_ids.add(chunk_id)
        rrf[chunk_id] = rrf.get(chunk_id, 0.0) + 1.0 / (60.0 + index)
    for index, hit in enumerate(keyword):
        chunk_id = UUID(str(hit.chunk_id))
        document_id = UUID(str(hit.document_id))
        document_of_chunk[chunk_id] = document_id
        keyword_ids.add(chunk_id)
        rrf[chunk_id] = rrf.get(chunk_id, 0.0) + 1.0 / (60.0 + index)
    if query_region is not None:
        rrf = {
            chunk_id: score
            for chunk_id, score in rrf.items()
            if region_of_chunk(chunk_id) == query_region
        }
    ranked = sorted(rrf.items(), key=lambda item: item[1], reverse=True)[:limit]
    hits: list[RankedHit] = []
    for chunk_id, _score in ranked:
        if chunk_id in semantic_ids and chunk_id in keyword_ids:
            matched_by: Literal["semantic", "keyword", "both"] = "both"
        elif chunk_id in semantic_ids:
            matched_by = "semantic"
        else:
            matched_by = "keyword"
        hits.append(
            RankedHit(
                chunk_id=chunk_id,
                document_id=document_of_chunk[chunk_id],
                matched_by=matched_by,
            )
        )
    return tuple(hits)


def _match_city(text: str) -> str | None:
    best: str | None = None
    best_length = -1
    best_index: int | None = None
    for name in CITIES:
        index = text.find(name)
        if index < 0:
            continue
        if len(name) > best_length or (
            len(name) == best_length
            and best_index is not None
            and index < best_index
        ):
            best = name
            best_length = len(name)
            best_index = index
    return best


def _significant_terms(query: str, city: str | None) -> tuple[str, ...]:
    cleaned = query
    if city is not None:
        index = cleaned.find(city)
        if index >= 0:
            cleaned = cleaned[:index] + cleaned[index + len(city):]
    if cleaned.startswith("市"):
        cleaned = cleaned[1:]
    if cleaned.endswith("市"):
        cleaned = cleaned[:-1]
    for stopword in STOPWORDS:
        cleaned = cleaned.replace(stopword, "")
    modifiers = [modifier for modifier in TRAVEL_MODIFIERS if modifier in cleaned]
    raw_terms = re.findall(r"[一-鿿]+", cleaned)
    return tuple(dict.fromkeys((*modifiers, *raw_terms)))


def _score_chunk(chunk: DocumentChunk, parsed: ParsedQuery) -> float:
    if parsed.region is not None and region_from_document_name(chunk.document_name) != parsed.region:
        return 0.0
    score = 0.0
    for category in parsed.categories:
        for keyword in INTENT_KEYWORDS[category]:
            if keyword in chunk.content:
                score += 2.0
    for term in parsed.significant_terms:
        if term and term in chunk.content:
            score += 1.0
    return score


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit 必须为正整数")
