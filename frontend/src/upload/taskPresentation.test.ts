import { describe, expect, it } from "vitest";

import { canCancelRun, presentTaskStatus } from "./taskPresentation";

describe("task presentation", () => {
  it("explains why a queued task is not moving", () => {
    expect(presentTaskStatus("queued", false)).toBe("等待处理服务启动");
    expect(presentTaskStatus("queued", true)).toBe("排队处理中");
  });

  it("only offers cancellation for active processing states", () => {
    expect(canCancelRun("queued")).toBe(true);
    expect(canCancelRun("parsing")).toBe(true);
    expect(canCancelRun("normalizing")).toBe(true);
    expect(canCancelRun("ready_for_review")).toBe(false);
    expect(canCancelRun("failed")).toBe(false);
    expect(canCancelRun("cancelled")).toBe(false);
  });
});
