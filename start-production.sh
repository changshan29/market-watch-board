#!/bin/bash
# Railway/Render 启动脚本

echo "安装 Python 依赖..."
pip3 install -r requirements.txt

echo "启动服务器..."
node server.js
