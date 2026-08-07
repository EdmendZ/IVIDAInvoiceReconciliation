import { describe, expect, it } from "vitest";

import { canEnterGold, formatCost } from "./experimentPresentation";

describe("experiment presentation", () => {
  it("does not render unknown cost as zero", () => {
    expect(formatCost(null)).toBe("Not configured");
  });

  it("enables Gold only for model errors", () => {
    expect(canEnterGold("model_error")).toBe(true);
    expect(canEnterGold("acceptable_variant")).toBe(false);
    expect(canEnterGold("business_context_update")).toBe(false);
  });
});
