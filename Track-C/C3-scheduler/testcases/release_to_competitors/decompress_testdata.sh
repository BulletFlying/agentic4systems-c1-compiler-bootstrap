#!/bin/bash
# 解压 C3.5 测试数据中的 .npy.gz 文件为 .npy
# 使用方法：bash decompress_testdata.sh

set -e

cd "$(dirname "$0")"

echo "Decompressing testdata ..."
find testdata -name "*.npy.gz" -type f | while read -r gz; do
  npy="${gz%.gz}"
  if [ -f "$npy" ]; then
    echo "  skip (exists): $npy"
  else
    echo "  decompress: $gz -> $npy"
    gunzip -c "$gz" > "$npy"
  fi
done

echo "Done."
