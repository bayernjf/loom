// 可签发的内部角色（与后端 INTERNAL_STAFF_ROLES 对齐，不含客户角色 whitelist_owner）。
// 角色码为系统标识，按 docs/18 原样直出，不进消息表翻译。
//
// 本文件刻意不加 "use server"：STAFF_ROLE_CODES 需被 client 岛（issue-staff-island.tsx）
// 直接导入做勾选渲染，若放在 "use server" 模块里导出，client bundle 只会拿到 Server
// Reference 代理（运行时非数组，.map 即崩）。常量放本模块、Server Action 留在 actions.ts，
// 双方各自 import。
export const STAFF_ROLE_CODES = [
  "operations",
  "platform_admin",
  "product_reviewer",
  "dictionary_admin",
  "internal_compliance",
] as const;

export type StaffRoleCode = (typeof STAFF_ROLE_CODES)[number];
