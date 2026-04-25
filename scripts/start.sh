#!/usr/bin/env bash
# ============================================================
# InsightLens — 一键启动脚本
# 启动 MCP Server，通过 stdio 提供工具的 MCP 接口。
#
# 直接运行（stdin/stdout 模式）：
#   bash scripts/start.sh
#
# 注册到 OpenClaw：
#   openclaw mcp set insightlens "bash $(pwd)/scripts/start.sh"
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "[InsightLens] 启动中..." >&2
echo "[InsightLens] 工作目录: $PROJECT_DIR" >&2

# 进入项目目录
cd "$PROJECT_DIR"

# 检查 Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[InsightLens] ❌ 未找到 Python 3" >&2
    exit 1
fi

# 检查依赖
echo "[InsightLens] 检查依赖..." >&2
$PYTHON -c "import bs4; import lxml; import httpx" 2>/dev/null || {
    echo "[InsightLens] ⚠️  部分依赖未安装，尝试安装..." >&2
    $PYTHON -m pip install -r "$PROJECT_DIR/requirements.txt" -q 2>&1 | tail -1
}

echo "[InsightLens] ✅ 就绪" >&2

# 启动 MCP Server（stdin/stdout 模式）
exec $PYTHON -m mcp_server
