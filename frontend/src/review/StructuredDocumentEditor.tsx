import { useMemo, useState } from "react";

type Evidence = {
  field_path: string;
  source_text: string;
  page: number | null;
};

type JsonRecord = Record<string, unknown>;

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

function EvidenceHint({
  fieldPath,
  evidence,
}: {
  fieldPath: string;
  evidence: Evidence[];
}) {
  const matches = evidence.filter((item) => item.field_path === fieldPath);
  if (!matches.length) {
    return <small className="field-evidence missing">No source evidence</small>;
  }
  return (
    <details className="field-evidence">
      <summary>
        Source: {matches[0].source_text}
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
}: {
  label: string;
  path: Array<string | number>;
  document: JsonRecord;
  evidence: Evidence[];
  onValue: (path: Array<string | number>, value: unknown) => void;
  required?: boolean;
  type?: "text" | "date";
}) {
  const value = textValue(atPath(document, path));
  const fieldPath = evidencePath(path);
  const inputId = `document-${fieldPath.replace(/[^a-zA-Z0-9]+/g, "-")}`;
  return (
    <label className="structured-field" htmlFor={inputId}>
      <span>
        {label}
        {required && <b aria-label="required">*</b>}
      </span>
      <input
        id={inputId}
        name={fieldPath}
        type={type}
        value={value}
        onChange={(event) =>
          onValue(path, event.target.value || (required ? "" : null))
        }
      />
      <EvidenceHint fieldPath={fieldPath} evidence={evidence} />
    </label>
  );
}

export function StructuredDocumentEditor({
  editor,
  evidence,
  onChange,
}: {
  editor: string;
  evidence: Evidence[];
  onChange: (value: string) => void;
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
    <div className="structured-editor">
      <div className="editor-mode-tabs">
        <button
          className={mode === "form" ? "active" : ""}
          disabled={!parsed}
          onClick={() => setMode("form")}
          type="button"
        >
          Structured form
        </button>
        <button
          className={mode === "json" ? "active" : ""}
          onClick={() => setMode("json")}
          type="button"
        >
          Advanced JSON
        </button>
      </div>

      {!parsed && (
        <div className="error-banner">
          JSON is invalid. Correct it in Advanced JSON before returning to the
          structured form.
        </div>
      )}

      {mode === "json" || !parsed ? (
        <textarea
          aria-label="Structured document JSON"
          className="json-editor"
          value={editor}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
        />
      ) : (
        <div className="structured-form">
          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">DOCUMENT</span>
                <h4>Document identity</h4>
              </div>
            </div>
            <div className="field-grid three">
              <Field
                label="Document number"
                path={["document_number"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                required
              />
              <Field
                label="Document date"
                path={["document_date"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                type="date"
              />
              <Field
                label="Purchase order"
                path={["purchase_order_number"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
              />
              <Field
                label="Currency"
                path={["currency"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
                required
              />
            </div>
          </section>

          {(["supplier", "location"] as const).map((party) => (
            <section className="form-section" key={party}>
              <div className="form-section-heading">
                <div>
                  <span className="eyebrow">{party.toUpperCase()}</span>
                  <h4>{party === "supplier" ? "Supplier" : "Delivery location"}</h4>
                </div>
              </div>
              <div className="field-grid">
                <Field
                  label="Name"
                  path={[party, "name"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                />
                <Field
                  label="ABN / business number"
                  path={[party, "business_number"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                />
                <Field
                  label="Address"
                  path={[party, "address"]}
                  document={parsed}
                  evidence={evidence}
                  onValue={setValue}
                />
              </div>
            </section>
          ))}

          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">LINE ITEMS</span>
                <h4>Products and quantities</h4>
              </div>
              <button type="button" onClick={addItem}>
                Add line
              </button>
            </div>
            <div className="line-editor-list">
              {items().map((item, index) => (
                <article className="line-editor-card" key={index}>
                  <div className="line-editor-heading">
                    <strong>Line {index + 1}</strong>
                    <button
                      className="danger"
                      disabled={items().length <= 1}
                      onClick={() => removeItem(index)}
                      type="button"
                    >
                      Remove
                    </button>
                  </div>
                  <div className="field-grid line-fields">
                    <Field
                      label="SKU"
                      path={["items", index, "sku"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                    />
                    <Field
                      label="Description"
                      path={["items", index, "description"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      required
                    />
                    <Field
                      label="Quantity"
                      path={["items", index, "quantity"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                      required
                    />
                    <Field
                      label="Unit"
                      path={["items", index, "unit"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                    />
                    <Field
                      label="Unit price"
                      path={["items", index, "unit_price"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                    />
                    <Field
                      label="Tax"
                      path={["items", index, "tax_amount"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                    />
                    <Field
                      label="Line total"
                      path={["items", index, "line_total"]}
                      document={parsed}
                      evidence={evidence}
                      onValue={setValue}
                    />
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="form-section">
            <div className="form-section-heading">
              <div>
                <span className="eyebrow">TOTALS</span>
                <h4>Financial totals</h4>
              </div>
            </div>
            <div className="field-grid three">
              <Field
                label="Subtotal"
                path={["subtotal"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
              />
              <Field
                label="GST / tax total"
                path={["tax_total"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
              />
              <Field
                label="Total"
                path={["total"]}
                document={parsed}
                evidence={evidence}
                onValue={setValue}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
