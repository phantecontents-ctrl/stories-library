#!/usr/bin/env bash
# Uso: scripts/notion_upload.sh <upload_url> <valore header authorization> <file>
# Carica un file su Notion dopo notion-create-file-upload (max 20 MiB).
set -euo pipefail
for i in 1 2 3; do
  code=$(curl -s -m 180 -o /dev/null -w '%{http_code}' -X POST "$1" -H "authorization: $2" -F "file=@$3") || code=000
  [ "$code" = 200 ] && { echo "upload ok"; exit 0; }
  echo "upload tentativo $i: HTTP $code" >&2; sleep 10
done
exit 1
