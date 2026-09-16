import { systemMessage } from "../i18n";
import { createContext, useContext, useMemo, useState } from "react";

type Evidence = {
  field_path: string;
  source_text: string;
  page: number | null;
};

type FieldIssue = {
  rule_code: string;
  severity: "blocking" | "warning";
  field_path: string;
  message: string;
};

type JsonRecord = Record<string, unknown>;
const IssueContext = createContext<FieldIssue[]>([]);

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function textValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function atPath(document: JsonRecord, path: Array<string | number>): unknown {
  let current: unknown = document;
  for (const segment of path) {
    if (typeof segment === "number") {
      if (!Array.isArray(current)) return undefined;
      current = current[segment];
    } else {
      if (!isRecord(current)) return undefined;
      current = current[segment];
    }
  }
  return current;
}

function updatePath(
  document: JsonRecord,
  path: Array<string | number>,
  value: unknown,
): JsonRecord {
  const next = structuredClone(document);
  let current: JsonRecord | unknown[] = next;
  path.forEach((segment, index) => {
    const final = index === path.length - 1;
    if (final) {
      if (Array.isArray(current) && typeof segment === "number") {
        current[segment] = value;
      } else if (!Array.isArray(current) && typeof segment === "string") {
        current[segment] = value;
      }
      return;
    }
    const following = path[index + 1];
    if (Array.isArray(current) && typeof segment === "number") {
      if (
        !isRecord(current[segment]) &&
        !Array.isArray(current[segment])
      ) {
        current[segment] = typeof following === "number" ? [] : {};
      }
      current = current[segment] as JsonRecord | unknown[];
    } else if (!Array.isArray(current) && typeof segment === "string") {
      if (!isRecord(current[segment]) && !Array.isArray(current[segment])) {
        current[segment] = typeof following === "number" ? [] : {};
      }
      current = current[segment] as JsonRecord | unknown[];
    }
  });
  return next;
}

function evidencePath(path: Array<string | number>): string {
  return path.reduce<string>((result, segment) => {
    if (typeof segment === "number") return `${result}[${segment}]`;
    return result ? `${result}.${segment}` : segment;
  }, "");
}

function canonicalIssuePath(path: string): string {
  return path.replace(/\.(\d+)(?=\.|$)/g, "[$1]");
}

function EvidenceHint({
  fieldPath,
  evidence,
}: {
  fieldPath: string;
  evidence: Evidence[];
}) {
  const matches = evidence.filter((item) => item.field_path === fieldPath);
  if (!matches.length) {
    return <small className="field-evidence missing">无原文证据</small>;
  }
  return (
    <details className="field-evidence">
      <summary>
        来源： {matches[0].source_text}
        {matches.length > 1 ? ` (+${matches.length - 1})` : ""}
      </summary>
      {matches.map((item, index) => (
        <p key={`${item.field_path}-${index}`}>
          {item.page ? `Page ${item.page}: ` : ""}
          {item.source_text}
        </p>
      ))}
    </details>
  );
}

function Field({
  label,
  path,
  document,
  evidence,
  onValue,
  required = false,
  type = "text",
  readOnly = false,
}: {
  label: string;
  path: Array<string | number>;
  document: JsonRecord;
  evidence: Evidence[];
  onValue: (path: Array<string | number>, value: unknown) => void;
  required?: boolean;
  type?: "text" | "date";
  readOnly?: boolean;
}) {
  const value = textValue(atPath(document, path));
  const fieldPath = evidencePath(path);
  const inputId = `document-${fieldPath.replace(/[^a-zA-Z0-9]+/g, "-")}`;
  const issues = useContext(IssueContext).filter(
    (issue) => canonicalIssuePath(issue.field_path) === fieldPath,
  );
  const fieldSeverity = issues.some((issue) => issue.severity === "blocking")
    ? "blocking"
    : issues.length
      ? "warning"
      : "";
  return (
    <label
      className={`structured-field ${fieldSeverity}`}
      htmlFor={inputId}
    >
      <span>
        {label}
        {required && <b aria-label="必填">*</b>}
      </span>
      <input
        aria-label={label}
        id={inputId}
        name={fieldPath}
        type={type}
        value={value}
        readOnly={readOnly}
        onChange={(event) =>
          onValue(path, event.target.value || (required ? "" : null))
        }
      />
      <EvidenceHint fieldPath={fieldPath} evidence={evidence} />
      {issues.map((issue, index) => (
        <small
          className={`field-validation ${issue.severity}`}
          key={`${issue.rule_code}-${index}`}
        >
          {systemMessage(issue.message)}
        </small>
      ))}
    </label>
  );
}

export function StructuredDocumentEditor({
  editor,
  evidence,
  issues,
  onChange,
  readOnly = false,
}: {
  editor: string;
  evidence: Evidence[];
  issues: FieldIssue[];
  onChange: (value: string) => void;
  readOnly?: boolean;
}) {
  const [mode, setMode] = useState<"form" | "json">("form");
  const parsed = useMemo(() => {
    try {
      const value: unknown = JSON.parse(editor);
      return isRecord(value) ? value : null;
    } catch {
      return null;
    }
  }, [editor]);

  function setValue(path: Array<string | number>, value: unknown) {
    if (!parsed) return;
    onChange(JSON.stringify(updatePath(parsed, path, value), null, 2));
  }

  function items(): JsonRecord[] {
    if (!parsed || !Array.isArray(parsed.items)) return [];
    return parsed.items.filter(isRecord);
  }

  function addItem() {
    if (!parsed) return;
    const nextItems = [
      ...items(),
      {
        line_number: null,
        sku: null,
        description: "",
        quantity: "1",
        unit: null,
        unit_price: null,
        tax_amount: null,
        line_total: null,
      },
    ];
    setValue(["items"], nextItems);
  }

  function removeItem(index: number) {
    const nextItems = items().filter((_, itemIndex) => itemIndex !== index);
    setValue(["items"], nextItems);
  }

  return (
    <IssueContext.Provider value={issues}>
      <div className="structured-editor">
      <div className="editor-mode-tabs">
        <button
          className={mode === "form" ? "active" : ""}
          disabled={!parsed}
          onClick={() => setMode("form")}
          type="button"
        >
          结构化表单
        </button>
        <button
          className={mode === "json" ? "active" : ""}
          onClick={() => setMode("json")}
          type="button"
        >
          高级 JSON 编辑
        </button>
      </div>

      {!parsed && (
        <div className="error-banner">
          JSON 无效，请先在高级 JSON 编辑中修正，再返回表单。
        </div>
      )}

      {mode === "json" || !parsed ? (
        <textarea
          aria-label="结构化单据 JSON"
          className="json-editor"
          value={editor}
          readOnly={readOnly}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
        />
      ) : (
        <div className="structured-form">
          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">单据信息</span>
                <h4>单据基本信息</h4>
              </div>
            </div>
            <div className="field-grid three">
              <Field
                label="单据编号"
                path={["document_number"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                required
                readOnly={readOnly}
              />
              <Field
                label="单据日期"
                path={["document_date"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                type="date"
                readOnly={readOnly}
              />
              <Field
                label="采购订单号"
                path={["purchase_order_number"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                readOnly={readOnly}
              />
              <Field
                label="币种"
                path={["currency"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                required
                readOnly={readOnly}
              />
            </div>
          </section>

          {(["supplier", "location"] as const).map((party) => (
            <section className="form-section" key={party}>
              <div className="form-section-heading">
                <div>
                  <span className="eyebrow">{party.toUpperCase()}</span>
                  <h4>{party === "supplier" ? "供应商" : "收货地点"}</h4>
                </div>
              </div>
              <div className="field-grid">
                <Field
                  label="名称"
                  path={[party, "name"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                  readOnly={readOnly}
                />
                <Field
                  label="ABN / 企业注册号"
                  path={[party, "business_number"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                  readOnly={readOnly}
                />
                <Field
                  label="地址"
                  path={[party, "address"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                  readOnly={readOnly}
                />
              </div>
            </section>
          ))}

          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">商品明细</span>
                <h4>商品与数量</h4>
              </div>
              {!readOnly && (
                <button type="button" onClick={addItem}>
                  添加商品行
                </button>
              )}
            </div>
            <div className="line-editor-list">
              {items().map((item, index) => (
                <article className="line-editor-card" key={index}>
                  <div className="line-editor-heading">
                    <strong>商品行 {index + 1}</strong>
                    {!readOnly && (
                      <button
                        className="danger"
                        disabled={items().length <= 1}
                        onClick={() => removeItem(index)}
                        type="button"
                      >
                        移除
                      </button>
                    )}
                  </div>
                  <div className="field-grid line-fields">
                    <Field
                      label="SKU"
                      path={["items", index, "sku"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      readOnly={readOnly}
                    />
                    <Field
                      label="商品描述"
                      path={["items", index, "description"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      required
                      readOnly={readOnly}
                    />
                    <Field
                      label="数量"
                      path={["items", index, "quantity"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      required
                      readOnly={readOnly}
                    />
                    <Field
                      label="单位"
                      path={["items", index, "unit"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      readOnly={readOnly}
                    />
                    <Field
                      label="单价"
                      path={["items", index, "unit_price"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      readOnly={readOnly}
                    />
                    <Field
                      label="税额"
                      path={["items", index, "tax_amount"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      readOnly={readOnly}
                    />
                    <Field
                      label="行金额"
                      path={["items", index, "line_total"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      readOnly={readOnly}
                    />
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">金额汇总</span>
                <h4>财务金额</h4>
              </div>
            </div>
            <div className="field-grid three">
              <Field
                label="小计"
                path={["subtotal"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                readOnly={readOnly}
              />
              <Field
                label="GST / 税额合计"
                path={["tax_total"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                readOnly={readOnly}
              />
              <Field
                label="总额"
                path={["total"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                readOnly={readOnly}
              />
            </div>
          </section>
        </div>
      )}
      </div>
    </IssueContext.Provider>
  );
}
