// 时间展示契约（docs/02：UTC 存储、Asia/Shanghai 展示，Intl.*）。
// 后端所有时间戳均为 UTC ISO 串；展示层统一转 Asia/Shanghai，绝不直出 UTC 字符串。
// 输入用途（datetime-local 转 ISO 提交、查询参数）不走本函数。
export function formatDateTimeLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    // 非法串回退原样截断，不抛异常（与旧实现同口径）。
    return iso.slice(0, 16).replace("T", " ");
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(parsed)
    .replace(/\//g, "-");
}
