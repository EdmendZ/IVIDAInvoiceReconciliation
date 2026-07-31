const LABELS: Record<string, string> = {
  uploaded: "已上传",
  parsing: "文档解析中",
  normalizing: "字段提取中",
  validating: "财务规则校验中",
  ready_for_review: "等待人工审核",
  failed: "处理失败",
  cancelled: "已取消",
};

export function presentTaskStatus(
  status: string,
  workerOnline: boolean,
): string {
  if (status === "queued") {
    return workerOnline ? "排队处理中" : "等待处理服务启动";
  }
  return LABELS[status] ?? status.replaceAll("_", " ");
}

export function canCancelRun(status: string): boolean {
  return ["queued", "submitting", "parsing", "normalizing", "validating"].includes(
    status,
  );
}
