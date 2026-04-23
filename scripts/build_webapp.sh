#!/usr/bin/env bash
# data/*.json → webapp/data/ 복사 (GitHub Pages 배포용)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_SRC="${PROJECT_DIR}/data"
DATA_DST="${PROJECT_DIR}/webapp/data"

mkdir -p "$DATA_DST"

for f in contests.json analyses.json artifacts.json; do
    if [[ -f "${DATA_SRC}/${f}" ]]; then
        cp "${DATA_SRC}/${f}" "${DATA_DST}/${f}"
        echo "Copied ${f}"
    else
        echo "Skip ${f} (not found)"
    fi
done

echo "build_webapp done: $(date)"
