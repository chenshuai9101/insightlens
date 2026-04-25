#!/usr/bin/env bash
# ============================================================
# InsightLens — 构建打包脚本
# 打包为 pip 可安装的 wheel，或直接压缩
#
# 用法:
#   bash scripts/build-skill.sh        # 打包 tar.gz
#   bash scripts/build-skill.sh wheel  # 构建 pip wheel
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"
VERSION="0.1.0"
DATE_TAG="$(date +%Y%m%d)"

echo "🔨 InsightLens Builder v$VERSION"
echo "=============================="

cd "$PROJECT_DIR"

# 创建输出目录
mkdir -p "$BUILD_DIR" "$DIST_DIR"

MODE="${1:-tarball}"

if [ "$MODE" = "wheel" ]; then
    # ---------- pip wheel 模式 ----------
    echo "📦 构建 pip wheel..."

    # 创建 setup.py
    cat > "$BUILD_DIR/setup.py" << 'SETUPEOF'
from setuptools import setup, find_packages

setup(
    name="insightlens",
    version="0.1.0",
    description="Agent-native web extractor: extract, search, subscribe, and recall",
    author="InsightLabs",
    author_email="chenshuai9101@gmail.com",
    url="https://github.com/chenshuai9101/insightlens",
    packages=find_packages(include=["insightlens*"]),
    python_requires=">=3.9",
    install_requires=[
        "beautifulsoup4>=4.9.0",
        "lxml>=4.6.0",
        "httpx>=0.24.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
SETUPEOF

    # 复制代码到 build 目录中的 insightlens 包
    mkdir -p "$BUILD_DIR/insightlens"
    cp -r "$PROJECT_DIR"/{lens_engine,extractor,searcher,subscriber,recaller,models,mcp_server}.py "$BUILD_DIR/insightlens/"
    cp "$PROJECT_DIR/requirements.txt" "$BUILD_DIR/insightlens/"

    # 构建 wheel
    cd "$BUILD_DIR"
    python3 -m pip wheel . --no-deps -w "$DIST_DIR" 2>&1 | tail -3 || {
        echo "⚠️  pip wheel 失败，回退到 tarball" >&2
        cd "$PROJECT_DIR"
        MODE="tarball"
    }

    cd "$PROJECT_DIR"
fi

if [ "$MODE" = "tarball" ]; then
    # ---------- tar.gz 模式 ----------
    echo "📦 打包 tar.gz..."
    TAR_NAME="insightlens-${VERSION}-${DATE_TAG}.tar.gz"

    tar -czf "$DIST_DIR/$TAR_NAME" \
        --exclude=".git" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        --exclude=".DS_Store" \
        --exclude="build" \
        -C "$PROJECT_DIR" \
        SKILL.md lens_engine.py extractor.py searcher.py subscriber.py \
        recaller.py models.py mcp_server.py requirements.txt \
        scripts/ assets/

    echo "✅ 打包完成: $DIST_DIR/$TAR_NAME"
fi

echo ""
echo "📊 文件清单:"
find "$DIST_DIR" -type f -ls

echo ""
echo "🎉 构建完成!"
