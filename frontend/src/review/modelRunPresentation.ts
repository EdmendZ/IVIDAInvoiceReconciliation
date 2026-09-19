export type ModelRun = {
  run_id: string;
  parser_provider: string | null;
  parser_model: string | null;
  normalizer_provider: string | null;
  normalizer_model: string | null;
  prompt_version: string | null;
  normalization_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_aud: string | null;
};

export function presentLatency(milliseconds: number | null): string {
  if (milliseconds === null) return "未记录";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  return `${(milliseconds / 1000).toFixed(1)} s`;
}

export function presentTokens(
  input: number | null,
  output: number | null,
): string {
  if (input === null && output === null) return "未提供";
  return `${input ?? "?"} 输入 / ${output ?? "?"} 输出`;
}

export function presentCost(cost: string | null): string {
  return cost === null ? "未配置费率" : `AUD ${cost}`;
}
