#!/bin/sh
# Q182：数据库首次初始化后，为 pg_basebackup 追加 replication 连接的 pg_hba 条目。
# 官方镜像 pg_setup_hba_conf 默认只写 `host all all all`，而 database 字段 all
# 不匹配 replication 连接；此处用与普通连接一致的认证方法补上（仅首次初始化执行）。
set -eu

auth="$(postgres -C password_encryption)"
echo "host replication all all ${auth}" >> "${PGDATA}/pg_hba.conf"

# Q182：归档卷挂载点默认属 root（postgres 无法写入），改为 postgres 所有。
# 本脚本在 initdb 阶段以 root 运行；chown 不可用时退化为 0777。
chown postgres:postgres /wal-archive 2>/dev/null || chmod 0777 /wal-archive
