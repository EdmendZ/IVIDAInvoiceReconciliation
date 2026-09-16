/** 仅翻译系统标签及已知系统消息，不翻译供应商、商品、证据和用户填写的数据。 */
const labels: Record<string, string> = {
  admin: "管理员", reviewer: "审核员", invoice: "发票", receive_note: "收货单",
  draft: "草稿", approved: "已批准", rejected: "已驳回", ready_for_review: "待审核",
  exact: "完全匹配", within_tolerance: "容差内", mismatch: "不匹配",
  invoice_only: "仅发票存在", receive_note_only: "仅收货单存在",
  recommended: "建议采用", inconclusive: "证据不足", model_error: "模型错误",
  acceptable_variant: "可接受的表达差异", reviewer_correction_error: "人工修订错误",
  business_context_update: "业务信息更新", error_type: "错误类型", business_scenario: "业务场景",
  schema_failure: "结构校验失败", schema_valid_rate: "结构校验通过率",
};
export function label(value: string): string { return labels[value] ?? value; }

const messages: Record<string, string> = {
  "Quantity differs": "数量不一致", "Unit price differs": "单价不一致", "Amount differs": "金额不一致",
  "Item exists only on receive note": "商品仅存在于收货单", "Item exists only on invoice": "商品仅存在于发票",
  "Purchase order number is missing": "缺少采购订单号",
  "Line total does not equal quantity multiplied by unit price": "行金额不等于数量乘以单价",
  "GST-free line contains a non-zero tax amount": "免 GST 商品行存在非零税额",
  "Subtotal does not equal the sum of line totals": "小计与各行金额之和不一致",
  "Tax total does not equal the sum of line tax amounts": "税额合计与各行税额之和不一致",
  "Total does not equal subtotal plus tax": "总额与小计加税额不一致",
  "Invalid credentials": "用户名或密码错误", "Authentication required": "请先登录",
  "No invoice items overlap with this receive note": "发票与此收货单没有相同商品",
  "Document date is missing on one or both documents": "一张或两张单据缺少日期",
  "Invoice and Receive Note have the same document number; verify that the document type was classified correctly": "发票与收货单编号相同，请核实单据分类是否正确",
};
export function systemMessage(value: string): string {
  if (messages[value]) return messages[value];
  const identity = value.match(/^(Purchase order|Supplier|Location) (matches: |differs: |is missing on one or both documents)(.*)$/);
  if (identity) return ({"Purchase order":"采购订单",Supplier:"供应商",Location:"收货地点"}[identity[1]] ?? identity[1]) + ({"matches: ":"一致：","differs: ":"不一致：","is missing on one or both documents":"信息缺失"}[identity[2]] ?? "") + identity[3];
  return value.replace(/^Currency matches: /, "币种一致：")
    .replace(/^Currency differs: /, "币种不一致：")
    .replace(/^Document dates are (\d+) day\(s\) apart$/, "单据日期相隔 $1 天")
    .replace(/^(\d+) item\(s\) overlap \((.+) of invoice items\)$/, "$1 项商品相同（占发票商品的 $2）")
    .replace(/^Request failed \((\d+)\)$/, "请求失败（$1）")
    .replace(/^Upload failed \((\d+)\)$/, "上传失败（$1）")
    .replace(/^Download failed \((\d+)\)$/, "下载失败（$1）");
}
