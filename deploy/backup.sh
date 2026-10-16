#!/usr/bin/env bash
# Postgres backup with rotation. Cron example (daily 03:00):
#   0 3 * * * cd /path/to/lead_gen_app && ./deploy/backup.sh >> backups/backup.log 2>&1
# Restore:
#   gunzip -c backups/leadgen-YYYYmmdd-HHMM.sql.gz | docker compose exec -T db psql -U leadgen leadgen
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups
file="backups/leadgen-$(date +%Y%m%d-%H%M).sql.gz"
docker compose exec -T db pg_dump -U leadgen --clean --if-exists leadgen | gzip > "$file"
find backups -name 'leadgen-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') backup ok: $file ($(du -h "$file" | cut -f1))"
