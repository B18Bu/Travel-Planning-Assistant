# 飞猪酒店最低价查询设计

- 日期：2026-08-25
- 状态：已确认设计，待书面规格审阅
- 范围：仅实现飞猪 API 56180 酒店最低价查询，不包含下单、支付、预订、房型详情、图片或库存承诺。

## 1. 目标与边界

新增独立接口 `POST /api/fliggy/hotels/search`，按城市、入住日期和离店日期查询飞猪酒店最低价列表。现有高德住宿 POI 推荐保持不变；酒店商品查询不复用或伪装为 POI 推荐，也不将模型/RAG 结果作为实时商品数据。

首期不实现：酒店下单、支付、预订、库存承诺、房型详情、图片、取消规则，以及 56179/56181 的接入。低价结果不缓存。

## 2. 外部接口

目标接口：

```text
alitrip.btrip.hotel.distribution.search.low.price
```

HTTPS 网关：

```text
https://eco.taobao.com/router/rest
```

业务参数通过 `param_hotel_search_list_r_q` 以 JSON 形式传递。首期使用：

- `check_in`：入住日期，`YYYY-MM-DD`，必填；
- `check_out`：离店日期，`YYYY-MM-DD`，必填；
- `city_name`：城市名称，首期必填；
- `sub_channel`：服务端配置，必填；
- `order`、`dir`、`page_no`、`page_size`：排序与分页参数。首期固定 `order=2`（价格）和 `dir=1`（升序），由服务端控制，不接收前端透传。

首期不接收前端传入 `sub_channel`，也不额外增加城市编码查询。若后续需要使用 `city_code`，在适配器内部扩展，不改变外部接口合同。

## 2.1 推荐规则

首期推荐定义为“飞猪低价优先推荐”，只使用 API 56180 返回的数据：

1. 请求飞猪按最低价升序返回；
2. 服务端过滤缺失或非正数价格；
3. 按最低价升序做确定性排序；
4. 价格相同时保持飞猪原始返回顺序；
5. 页面标注“飞猪低价优先推荐”，不声称综合性价比、距离、评分、星级或服务质量。

现有高德住宿 POI 不参与飞猪结果排序，模型/RAG 也不生成酒店推荐理由。后续接入 56179/56181 并确认字段授权后，才扩展星级、位置、评分或取消规则等排序维度。

## 3. API 请求合同

请求示例：

```json
{
  "city_name": "杭州",
  "check_in": "2026-09-01",
  "check_out": "2026-09-02",
  "page_no": 1,
  "page_size": 20
}
```

校验规则：

- `city_name` 必填且去除首尾空白后非空；
- 日期格式为 `YYYY-MM-DD`；
- 入住日期早于离店日期；
- 入住日期不得早于服务端当前日期；
- `page_no >= 1`；
- `1 <= page_size <= 50`；
- 未知请求字段拒绝接受，避免把未审核的供应商参数透传。

`sub_channel`、AppKey、AppSecret 和网关地址全部由服务端配置提供。

## 4. 推荐架构

采用独立飞猪酒店适配器：

```text
Fliggy hotel router
  -> HotelSearchService
    -> FliggyHotelClient
      -> TOP 参数组装与签名
      -> HTTPS 请求
      -> 供应商响应解析
```

### Router

只负责 HTTP 请求/响应、项目统一错误转换和 trace/request 上下文，不实现签名或供应商字段映射。

### HotelSearchService

负责调用适配器、规范化价格和结果元数据，并将供应商异常转换为项目服务错误。查询失败不降级为高德住宿 POI。

### FliggyHotelClient

负责固定 method、公共 TOP 参数、HMAC/MD5 签名、嵌套业务 JSON、HTTPS 请求、超时和供应商响应解析。AppSecret 只用于签名。

## 5. 配置与安全

新增配置项：

```text
FLIGGY_APP_KEY
FLIGGY_APP_SECRET
FLIGGY_SUB_CHANNEL
FLIGGY_API_URL=https://eco.taobao.com/router/rest
FLIGGY_HOTEL_ENABLED=false
```

默认关闭真实请求。开关关闭或必需配置缺失时返回“酒店查询未配置”的服务错误，且不得发起外部请求。

安全要求：

- AppSecret 不进入响应、异常消息或日志；
- 签名原文、完整请求参数和完整供应商原始响应不得记录；
- 日志最多记录 request/trace ID、固定 method、耗时和供应商错误码；
- 仅使用 HTTPS 网关；
- 不缓存实时最低价结果。

## 6. 响应合同

成功响应仅输出已确认的低价结果字段：

```json
{
  "status": "realtime",
  "source": {
    "provider": "fliggy",
    "retrieved_at": "2026-08-25T12:00:00Z"
  },
  "hotels": [
    {
      "hotel_id": "10076614",
      "name": "杭州中洲大酒店",
      "low_price": 180.0,
      "currency": "CNY",
      "supplier": "飞猪"
    }
  ],
  "total": 100,
  "page_no": 1,
  "page_size": 20,
  "trace_id": "..."
}
```

供应商 `low_price` 单位为分，内部先按整数处理，再转换为人民币元；不得使用二进制浮点累积计算。酒店 ID 统一以字符串对外输出，避免大整数序列化差异。无酒店结果返回空列表和供应商给出的总数，不伪造降级数据。

## 7. 错误处理

- 请求校验失败：HTTP 422；
- 功能关闭或配置缺失：HTTP 503；
- 飞猪认证、权限或渠道错误：HTTP 502，保留可排查的供应商错误码；
- 超时、连接失败或供应商 5xx：HTTP 502；
- 响应结构不符合合同：HTTP 502；
- 不向调用方暴露签名、AppSecret 或完整供应商响应。

供应商错误应使用项目现有统一错误响应机制，并携带 request/trace ID。

## 8. 测试验收

必须覆盖：

1. 日期格式、入住早于离店、不可查询过去日期和分页上下界；
2. TOP HMAC/MD5 签名的参数排序、拼接和编码；
3. `param_hotel_search_list_r_q` JSON 组装及服务端注入 `sub_channel`；
4. 成功响应映射、分到元转换、酒店 ID 字符串化和空结果；
5. 认证失败、权限/渠道失败、超时、连接失败、供应商错误和结构异常；
6. 默认关闭或配置缺失时不发出外部请求；
7. AppSecret 不出现在日志、错误和响应；
8. 现有高德住宿 POI 测试继续通过，且两种查询合同没有交叉污染。

## 9. 明确前置条件

代码可以先通过 Mock 和契约测试实现，但真实联调前必须由部署环境提供：

- 已开通 API 56180 的 TOP 应用；
- 有效 AppKey/AppSecret；
- 对应的有效 `sub_channel`；
- 价格字段面向本项目终端用户展示的授权确认。

这些条件不能由 API 文档本身推断或绕过。
