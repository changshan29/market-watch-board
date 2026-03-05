#!/bin/bash
# 财联社项目二 - 一键启动脚本

PROJECT_DIR="/Users/liu/cailianshe-p2"
PORT=3220

cd "$PROJECT_DIR" || exit 1

echo "=== 财联社项目二启动 ==="
echo "项目目录: $PROJECT_DIR"
echo "端口: $PORT"
echo ""

# 检查端口是否被占用
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "✓ 服务器已在运行"
    PID=$(lsof -Pi :$PORT -sTCP:LISTEN -t)
    echo "  进程ID: $PID"
else
    echo "启动服务器..."
    nohup node server.js > /tmp/cailianshe_p2_server.log 2>&1 &
    sleep 2
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo "✓ 服务器启动成功"
    else
        echo "✗ 服务器启动失败，请查看日志: /tmp/cailianshe_p2_server.log"
        exit 1
    fi
fi

echo ""
echo "=== 打开浏览器 ==="
open "http://localhost:$PORT"

echo ""
echo "✓ 财联社项目二已启动"
echo "  看板地址: http://localhost:$PORT"
echo "  管理后台: http://localhost:$PORT/admin"
echo "  日志文件: /tmp/cailianshe_p2_server.log"
echo ""
echo "提示："
echo "  - 点击「暂停」按钮可停止自动刷新"
echo "  - 在管理后台可调整刷新频率和添加来源"
