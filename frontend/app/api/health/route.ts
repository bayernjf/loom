// 静态健康探针端点：容器 healthcheck 与 watchdog 均打这里。
//
// 根因背景（2026-11-13 修复）：这两个探针此前都打 `http://frontend:3000/`
// 根路径，且都在拿到响应头/状态码后立即断开、不消费 body。根路径是 React
// Server Components 流式页面，探针提前断连会截断 RSC 流，触发 Node 内部
// `TransformStream` 的 `controller[kState].transformAlgorithm is not a function`，
// 进而破坏客户端水合、页面永久卡在 loading 骨架屏（详见 handoff 2026-11-11）。
//
// 本端点返回纯静态 JSON、不经过 React 渲染/streaming，探针即使不消费 body
// 也不存在可被截断的流，从根上消除该故障。
export function GET() {
  return Response.json({ status: "ok" });
}
