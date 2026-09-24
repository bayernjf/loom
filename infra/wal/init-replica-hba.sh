#!/bin/sh
# Q182：数据库首次初始化后，为 pg_basebackup 追加 replication 连接的 pg_hba 条目。
# 官方镜像 pg_setup_hba_conf 默认只写 `host all all all`，而 database 字段 all
# 不匹配 replication 连接；此处用与普通连接一致的认证方法补上（仅首次初始化执行）。
set -eu

auth="$(postgres -C password_encryption)"
echo "host replication all all ${auth}" >> "${PGDATA}/pg_hba.conf"

# Q185 修正：归档卷属主不在此处理。官方镜像把 /docker-entrypoint-initdb.d 下的
# .sh 以 **postgres（uid 999）** 身份执行，而非 Q182 注释所假设的 root；空命名卷
# 挂载点默认 root:root，故此处 chown 与 chmod 退路会双双 EPERM，被 set -e 打死、
# postgres 容器 exit 1（全新卷的 `docker compose up` 必挂）。卷属主改由 compose 里
# 的 wal-archive-init 一次性 root 容器负责。
