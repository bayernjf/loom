#!/usr/bin/env bash
# Q182：PITR（时点恢复）端到端演练。用一次性容器与命名卷在临时 docker 网络内：
#   起源库(开 WAL 归档)+MinIO → 造「恢复点前/后」数据并取目标时点 T →
#   pg_basebackup 基础备份 → WAL 与基础备份推 MinIO → 从 MinIO 拉回 →
#   起新库前滚到 T → 断言「前」数据在、「后」数据不在（证明时点恢复精确）→ 清理。
# 仅需本机 docker（同 rpo-rto-rehearsal.sh 先例）；不依赖常驻 compose 栈。
set -euo pipefail

ID="$$"
NET="loom-pitr-${ID}"
SRC="loom-pitr-src-${ID}"
RCV="loom-pitr-rcv-${ID}"
MINIO="loom-pitr-minio-${ID}"
V_WALARC="loom-pitr-walarc-${ID}"
V_BASE="loom-pitr-base-${ID}"
V_RBASE="loom-pitr-rbase-${ID}"
V_RDATA="loom-pitr-rdata-${ID}"
V_RARC="loom-pitr-rarc-${ID}"
V_MDATA="loom-pitr-mdata-${ID}"
BUCKET="loom-wal"
IMG_PG="pgvector/pgvector:pg16"
IMG_MC="quay.io/minio/mc:latest"
IMG_BB="busybox:latest"
IMG_MINIO="quay.io/minio/minio:latest"

cleanup() {
  docker rm -f "$SRC" "$RCV" "$MINIO" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  for v in "$V_WALARC" "$V_BASE" "$V_RBASE" "$V_RDATA" "$V_RARC" "$V_MDATA"; do
    docker volume rm "$v" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

wait_ready() {
  name=$1; user=$2
  for _ in $(seq 1 40); do
    if docker exec "$name" pg_isready -U "$user" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $name"; return 1
}

echo ">> network + volumes"
docker network create "$NET" >/dev/null
for v in "$V_WALARC" "$V_BASE" "$V_RBASE" "$V_RDATA" "$V_RARC" "$V_MDATA"; do
  docker volume create "$v" >/dev/null
done

echo ">> minio"
docker run --rm -v "$V_MDATA:/data" "$IMG_BB" chown 1000:1000 /data
docker run -d --name "$MINIO" --network "$NET" --network-alias minio \
  -v "$V_MDATA:/data" \
  "$IMG_MINIO" server /data --console-address ":9001" >/dev/null
for _ in $(seq 1 30); do
  docker run --rm --network "$NET" "$IMG_BB" sh -c 'wget -q -O- http://minio:9000/minio/health/live' >/dev/null 2>&1 && break
  sleep 1
done

echo ">> fix archive dir ownership (named volume defaults to root)"
docker run --rm -v "$V_WALARC:/wal-archive" "$IMG_BB" chown 999:999 /wal-archive

echo ">> source postgres (archiving on)"
docker run -d --name "$SRC" --network "$NET" \
  -e POSTGRES_PASSWORD=loom \
  -v "$V_WALARC:/wal-archive" \
  "$IMG_PG" \
  postgres -c archive_mode=on -c wal_level=replica -c archive_timeout=10 \
  -c "archive_command=test ! -f /wal-archive/%f && cp %p /wal-archive/%f" >/dev/null
wait_ready "$SRC" postgres

echo ">> allow replication connections in pg_hba"
# 官方镜像默认只写 host all（不匹配 replication 连接），显式追加并 reload。
docker exec "$SRC" sh -c 'echo "host replication all all trust" >> /var/lib/postgresql/data/pg_hba.conf && psql -U postgres -c "select pg_reload_conf()" >/dev/null'

echo ">> base backup (must precede recovery target T)"
docker run --rm --network "$NET" -e PGPASSWORD=loom -v "$V_BASE:/base" "$IMG_PG" \
  sh -c "mkdir -p /base/d && pg_basebackup -h $SRC -U postgres -D /base/d -Ft -z -X stream -c fast"

echo ">> seed data + recovery target time T"
docker exec "$SRC" psql -U postgres -c \
  "create table pitr(id serial primary key, tag text, created timestamptz default now())" >/dev/null
docker exec "$SRC" psql -U postgres -c "insert into pitr(tag) values('before')" >/dev/null
docker exec "$SRC" psql -U postgres -c "select pg_switch_wal()" >/dev/null
T=$(docker exec "$SRC" psql -U postgres -tAc "select now()")
sleep 2
docker exec "$SRC" psql -U postgres -c "insert into pitr(tag) values('after')" >/dev/null
docker exec "$SRC" psql -U postgres -c "select pg_switch_wal()" >/dev/null
echo "   recovery target T = $T"

echo ">> wait for WAL archive to land"
archived=0
for _ in $(seq 1 20); do
  n=$(docker run --rm -v "$V_WALARC:/w" "$IMG_BB" sh -c "ls /w | grep -c '^0000' || true")
  if [ "$n" -ge 2 ]; then archived=1; break; fi
  sleep 2
done
[ "$archived" = 1 ] || { echo "FAIL: WAL did not archive"; docker logs "$SRC" | tail -20; exit 1; }

echo ">> push base + WAL to MinIO"
docker run --rm --network "$NET" \
  -v "$V_BASE:/base" -v "$V_WALARC:/wal" \
  --entrypoint sh "$IMG_MC" \
  -c "mc alias set loom http://minio:9000 minioadmin minioadmin && mc mb -p loom/$BUCKET && mc cp --recursive /base/d/ loom/$BUCKET/base && mc cp --recursive /wal/ loom/$BUCKET/wal"

echo ">> pull base + WAL back from MinIO (simulate disaster)"
docker run --rm --network "$NET" \
  -v "$V_RBASE:/rbase" -v "$V_RARC:/rarc" \
  --entrypoint sh "$IMG_MC" \
  -c "mc alias set loom http://minio:9000 minioadmin minioadmin && mc cp --recursive loom/$BUCKET/base/ /rbase && mc cp --recursive loom/$BUCKET/wal/ /rarc"

echo ">> prepare recovery data dir"
docker run --rm -v "$V_RBASE:/rbase" -v "$V_RDATA:/data" -v "$V_RARC:/arc" "$IMG_BB" \
  sh -c "tar xzf /rbase/base.tar.gz -C /data && \
         if [ -f /rbase/pg_wal.tar.gz ]; then mkdir -p /data/pg_wal && tar xzf /rbase/pg_wal.tar.gz -C /data/pg_wal; fi && \
         touch /data/recovery.signal && \
         printf \"restore_command = 'cp /arc/%%f %%p'\nrecovery_target_time = '%s'\nrecovery_target_action = 'promote'\n\" '$T' >> /data/postgresql.auto.conf && \
         chown -R 999:999 /data /arc"

echo ">> recovery postgres (roll forward to T)"
docker run -d --name "$RCV" --network "$NET" \
  -v "$V_RDATA:/var/lib/postgresql/data" \
  -v "$V_RARC:/arc:ro" \
  "$IMG_PG" postgres >/dev/null

echo ">> wait for recovery to promote"
promoted=0
for _ in $(seq 1 45); do
  state=$(docker exec "$RCV" psql -U postgres -tAc "select pg_is_in_recovery()" 2>/dev/null || echo "")
  if [ "$state" = "f" ]; then promoted=1; break; fi
  sleep 2
done
[ "$promoted" = 1 ] || { echo "recovery did not finish/promote"; docker logs "$RCV" | tail -30; exit 1; }

echo ">> assert: 'before' present, 'after' absent"
before=$(docker exec "$RCV" psql -U postgres -tAc "select count(*) from pitr where tag='before'")
after=$(docker exec "$RCV" psql -U postgres -tAc "select count(*) from pitr where tag='after'")
echo "   before=$before after=$after"
[ "$before" = "1" ] || { echo "FAIL: pre-target row missing"; exit 1; }
[ "$after" = "0" ] || { echo "FAIL: post-target row present (PITR not precise)"; exit 1; }

echo ""
echo "PITR rehearsal OK: base backup + WAL restored from object storage, rolled forward to T exactly."
