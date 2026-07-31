import { describe, expect, it } from "vitest";
import {
  presentCost,
  presentLatency,
  presentTokens,
} from "./modelRunPresentation";

describe("model run presentation", () => {
  it("does not present an unknown cost as zero", () => {
    expect(presentCost(null)).toBe("Rate not configured");
  });

  it("formats latency and partial token usage honestly", () => {
    expect(presentLatency(71683)).toBe("71.7 s");
    expect(presentTokens(1200, null)).toBe("1200 input / ? output");
  });
});
