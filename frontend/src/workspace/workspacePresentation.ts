import { label } from "../i18n";
import type { BlockingCode, DocumentDetail, DisplayStatus, MetricStatus, PreviewResult } from "./workspaceTypes";

export type ResultExplanation = {
  key: string;
  title: string;
  reason: string;
  impact: string;
  action: string;
};

const BLOCKING_EXPLANATIONS: Record<BlockingCode, Omit<ResultExplanation, "key">> = {
  EMPTY_ITEM_KEY: { title: "商品标识缺失", reason: "至少一个商品行既没有 SKU，也没有可用于关联的描述。", impact: "系统无法确定两边是否为同一商品。", action: "根据原件补充 SKU 或商品描述后重新核对。" },
  UNIT_UNVERIFIED: { title: "单位未核验", reason: "至少一个商品行缺少可识别的计量单位。", impact: "数量无法在相同单位下安全比较。", action: "根据原件补充或校正单位后重新核对。" },
  UNIT_CONFLICT: { title: "单位不一致", reason: "Invoice 与 Receive Note 的同一商品使用了不兼容的单位。", impact: "系统不能直接比较两边数量。", action: "校正提取字段，或先完成可靠的单位换算。" },
  SUPPLIER_UNVERIFIED: { title: "供应商未核验", reason: "单据缺少足够的供应商名称或 ABN。", impact: "系统无法证明两边属于同一供应商。", action: "根据原件补充供应商名称或 ABN。" },
  SUPPLIER_CONFLICT: { title: "供应商冲突", reason: "Invoice 与 Receive Note 的供应商身份不一致。", impact: "两张单据不能作为同一笔收货安全核对。", action: "检查单据选择及供应商字段，修正后重新关联。" },
  CURRENCY_CONFLICT: { title: "币种不一致", reason: "Invoice 与 Receive Note 使用不同币种。", impact: "金额和单价不能直接比较。", action: "检查是否选错收货单，并校正币种字段。" },
  UNSUPPORTED_CURRENCY: { title: "币种暂不支持", reason: "当前核对规则只支持 AUD。", impact: "系统不能按当前容差规则核验金额。", action: "确认单据币种；其他币种需进入后续业务范围。" },
  SOURCE_VOIDED: { title: "来源已作废", reason: "所选来源单据已经作废。", impact: "作废来源不能进入正式核对结果。", action: "移除该来源并选择有效的收货记录。" },
  VALIDATION_BLOCKED: { title: "单据校验未通过", reason: "单据关键字段缺失或未通过确定性校验。", impact: "当前数据不足以生成可确认的正式结果。", action: "按字段提示修正单据后重新核对。" },
  DUPLICATE_INVOICE: { title: "发票重复", reason: "同门店已有相同供应商和发票编号的记录。", impact: "继续确认可能造成重复入账。", action: "打开既有发票，或核实并校正本张发票编号。" },
  RECEIVING_IN_USE: { title: "收货单已被占用", reason: "所选 Receive Note 已进入另一张发票的正式结果。", impact: "当前版本不允许整张收货单被多张发票重复使用。", action: "检查关联；如原结果有误，先重开原发票。" },
};

export function displayStatusLabel(status: DisplayStatus): string {
  return label(status);
}

export function metricStatusLabel(status: MetricStatus): string {
  return label(status);
}

/** A confirmation is a user acknowledgement of the current server preview.
 * This is only a conservative UI affordance; the server rechecks every rule. */
export function canConfirm(detail: DocumentDetail): boolean {
  const summary = detail.document;
  const preview = detail.preview;
  return (
    summary.document_type === "invoice" &&
    summary.processing_status === "ready" &&
    summary.display_status !== "completed" &&
    summary.display_status !== "voided" &&
    detail.review_status !== "completed" &&
    detail.match_status === "selected" &&
    detail.current_revision !== null &&
    preview !== null &&
    !detail.preview_stale &&
    preview.result.outcome !== "blocked" &&
    preview.result.blocking_codes.length === 0 &&
    detail.confirmation === null
  );
}

export function canEdit(detail: DocumentDetail): boolean {
  const summary = detail.document;
  return (
    summary.source_kind === "upload" &&
    summary.processing_status === "ready" &&
    summary.display_status !== "completed" &&
    summary.display_status !== "voided" &&
    detail.review_status !== "completed" &&
    detail.current_revision !== null &&
    detail.confirmation === null
  );
}

export function canReopen(detail: DocumentDetail): boolean {
  return (
    detail.document.document_type === "invoice" &&
    detail.document.display_status === "completed" &&
    detail.document.processing_status === "ready" &&
    detail.confirmation !== null
  );
}

export function unverifiedSummary(result: PreviewResult): string {
  const dimensions = result.unverified_dimensions.map((dimension) => label(dimension));
  return dimensions.length > 0
    ? `未核验：${dimensions.join("、")}`
    : "未发现未核验维度";
}

export function unverifiedExplanations(result: PreviewResult): ResultExplanation[] {
  return result.unverified_dimensions.map((dimension) => {
    if (dimension === "document_total") return {
      key: dimension, title: "单据总额",
      reason: "Receive Note 通常不提供发票应付总额，系统不会用收货数量推算总额。",
      impact: "商品收货情况仍可核验，但最终应付总额没有另一方单据作为依据。",
      action: "查看 Invoice 原件中的总额；确认来源正确后可保留未核验并知情确认。",
    };
    if (dimension === "tax") return {
      key: dimension, title: "税额",
      reason: "Receive Note 通常不记录 GST，缺少可与 Invoice 税额比较的数据。",
      impact: "本次核对不能证明最终 GST 或含税付款金额正确。",
      action: "检查 Invoice 原件的 GST；若收货单本身不含税额，可保留未核验并知情确认。",
    };
    if (dimension === "price") {
      const multiple = result.lines.some((line) => line.price.reason_code === "MULTIPLE_PRICES" || line.reason_codes.includes("MULTIPLE_PRICES"));
      return {
        key: dimension, title: "单价",
        reason: multiple ? "同一商品汇总到了多个不同单价，系统不能选一个单价代表全部收货。" : "至少一个匹配商品缺少可比较的 Receive Note 单价。",
        impact: "数量仍可核验，但系统不能判断单价是否一致。",
        action: "若原件含单价，请校正字段；收货单本身不提供单价时，可保留未核验并知情确认。",
      };
    }
    if (dimension === "amount") return {
      key: dimension, title: "金额",
      reason: "至少一个匹配商品缺少可比较的行金额，且系统不会把缺值当作零。",
      impact: "数量仍可核验，但系统不能判断该商品金额是否一致。",
      action: "若原件含行金额，请校正字段；否则可保留未核验并知情确认。",
    };
    return {
      key: dimension, title: label(dimension), reason: "当前两边没有足够数据完成此维度核验。",
      impact: "该维度不会被当作一致或差异。", action: "检查原件和提取字段；确认确实无数据后可知情确认。",
    };
  });
}

export function blockingExplanations(result: PreviewResult): ResultExplanation[] {
  return result.blocking_codes.map((code) => ({ key: code, ...BLOCKING_EXPLANATIONS[code] }));
}

export function differenceExplanation(result: PreviewResult): ResultExplanation | null {
  if (result.outcome !== "difference") return null;
  return {
    key: "difference", title: "发现实际差异",
    reason: "至少一个商品的数量、单价或金额超出允许容差，或只出现在一边。",
    impact: "系统会保留原始差异，不能按完全一致的结果关闭。",
    action: "核实原件和收货情况，并在确认前填写差异处理说明。",
  };
}
