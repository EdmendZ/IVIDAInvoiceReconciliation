# Taptouch Receiving 集成流程

## 业务目的

门店在 Taptouch 完成收货后，集成方把一份完整、带版本的 Receiving Snapshot
发送给本项目。本项目保存不可变版本，并把“当前最新且有效”的版本作为 Invoice
候选。该流程绕过 OCR 和人工审核，但不会绕过 Schema、身份和数据库约束。

## 接口与认证

```text
POST /api/integrations/taptouch/receiving-records
Authorization: Bearer <TAPTOUCH_INTEGRATION_TOKEN>
Content-Type: application/json
```

本地 `.env` 必须设置随机的 `TAPTOUCH_INTEGRATION_TOKEN`。未配置、缺少或错误
的 Token 都返回 401；Token 不应出现在日志、提交记录或错误响应中。

## 请求示例

```json
{
  "external_tenant_id": "tenant-au",
  "external_brand_id": "brand-pizza",
  "external_store_id": "store-sydney-cbd",
  "external_supplier_id": "supplier-fresh-foods",
  "external_receiving_id": "receiving-1001",
  "external_version": 1,
  "record_status": "active",
  "document_number": "GRN-1001",
  "received_at": "2026-08-07T14:30:00+10:00",
  "currency": "AUD",
  "purchase_order_number": "PO-7788",
  "supplier": {"name": "Fresh Foods"},
  "location": {"name": "Sydney CBD"},
  "items": [
    {
      "sku": "CHEESE-01",
      "description": "Mozzarella",
      "quantity": "2",
      "unit": "case",
      "unit_price": "10.00",
      "line_total": "20.00"
    }
  ],
  "upstream_updated_at": "2026-08-07T14:31:00+10:00"
}
```

时间戳必须携带时区；币种会统一转成大写；每个版本必须包含至少一条商品行。
作废也发送完整 Snapshot，而不是仅发送一个状态补丁。

## 幂等和版本规则

业务身份由以下字段组成：

```text
source_system + external_tenant_id + external_store_id
+ external_receiving_id + external_version
```

| 场景 | 结果 |
|---|---|
| 首次收到某版本 | 201，`created=true` |
| 完全相同的当前版本重放 | 200，`created=false`，返回原 version_id |
| 同版本号但内容不同 | 409，`external_version_conflict` |
| 版本号低于已保存最新版本 | 409，`stale_external_version` |
| 更高版本 | 201，新增不可变版本，旧版本保留 |
| Payload 不符合 Schema | 422 |

同一 Receiving 的较新 `voided` 版本会阻止它以及所有旧 `active` 版本继续参与
候选匹配。历史对账结果仍然是创建时的不可变快照，不会被追溯改写。

## 本地调用

```powershell
$headers = @{ Authorization = "Bearer $env:TAPTOUCH_INTEGRATION_TOKEN" }
$body = Get-Content .\examples\taptouch-receiving.json -Raw
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8200/api/integrations/taptouch/receiving-records `
  -Headers $headers `
  -ContentType application/json `
  -Body $body
```

示例中的 JSON 路径可替换为调用方自己的测试文件；不要把真实 Token 写进命令
历史、文档或仓库。

## 数据与审计边界

导入结果直接形成：

- `status=approved`；
- `source_kind=taptouch_receiving`；
- `trust_method=upstream_authoritative`；
- `approved_by=null`；
- `approved_at` 为本地导入时间。

它不会创建 Extraction Task、Extraction Run、Document Draft、人工 Reviewer 或
Review Action。上游身份、版本、更新时间和完整 Snapshot 就是这条路径的审计依据。
