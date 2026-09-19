import { describe, expect, it } from "vitest";
import { label, systemMessage } from "./i18n";

describe("Chinese presentation with English business data", () => {
  it("translates system labels while preserving unknown business values", () => {
    expect(label("invoice")).toBe("发票");
    expect(label("Pizza Flour 12.5 kg")).toBe("Pizza Flour 12.5 kg");
    expect(systemMessage("Supplier matches: English Foods Pty Ltd")).toBe("供应商一致：English Foods Pty Ltd");
    expect(systemMessage("Original supplier evidence in English")).toBe("Original supplier evidence in English");
  });
});
