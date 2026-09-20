// Q130：效果记录展示共用 helpers（metrics 七键固定顺序，缺席键显 "—" 绝不显 0）。
// 契约见 05 §1.1.1 / 11 §2.1（Q60）：六计数 + read_rate，稀疏存储。

export const METRIC_FIELDS = [
  "plays",
  "likes",
  "comments",
  "shares",
  "inquiries",
  "conversions",
  "read_rate",
] as const;

export function metricText(
  metrics: Record<string, number> | null,
  key: string,
): string {
  if (!metrics || !(key in metrics) || metrics[key] === null) return "—";
  const value = metrics[key];
  if (key === "read_rate") return String(Math.round(value * 1000) / 1000);
  return String(value);
}

export function capturedAtText(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "—";
}
