#!/bin/sh
# Q182：把归档的 WAL 段与完成的基础备份推送到对象存储（S3/MinIO）。
# 运行于 minio/mc 镜像（compose wal-archiver，entrypoint 已覆盖为 /bin/sh）。
# 显式 `mc alias set` 注册端点（不依赖 MC_HOST_ 环境变量的隐式加载）。
set -eu

ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
ACCESS="${S3_ACCESS_KEY:-minioadmin}"
SECRET="${S3_SECRET_KEY:-minioadmin}"
BUCKET="${WAL_BUCKET:-loom-wal}"
INTERVAL="${WAL_ARCHIVE_INTERVAL_SECONDS:-60}"
WAL_DIR=/wal-archive
BASE_DIR=/basebackups

mc alias set loom "$ENDPOINT" "$ACCESS" "$SECRET"
mc mb -p "loom/$BUCKET"

while true; do
  # 归档 WAL 段（含 timeline history）；推送成功后删除本地副本。
  for f in "$WAL_DIR"/0000*; do
    [ -e "$f" ] || continue
    name=$(basename "$f")
    if mc cp "$f" "loom/$BUCKET/wal/$name"; then
      rm -f "$f"
    fi
  done

  # 基础备份目录（带 .done 标记）；递归推送后清理本地副本。
  for d in "$BASE_DIR"/*; do
    [ -d "$d" ] || continue
    [ -f "$d/.done" ] || continue
    ts=$(basename "$d")
    if mc cp --recursive "$d"/ "loom/$BUCKET/base/$ts/"; then
      rm -rf "$d"
    fi
  done

  sleep "$INTERVAL"
done
