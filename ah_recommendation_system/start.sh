#!/bin/bash
# AH股推荐系统启动脚本 (Linux/Mac)
# ====================================

echo "启动AH股每日推荐系统..."

# 1. 检查Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python，请先安装Python 3.10+"
    exit 1
fi

# 2. 安装依赖
echo "[1/3] 安装依赖..."
cd "$(dirname "$0")/backend"
pip3 install -r requirements.txt -q

if [ $? -ne 0 ]; then
    echo "错误: 依赖安装失败"
    exit 1
fi

# 3. 启动服务
echo "[2/3] 启动后端服务..."
nohup python3 main.py > ../logs/app.log 2>&1 &

# 4. 等待启动
sleep 3

# 5. 打开浏览器
echo "[3/3] 打开浏览器..."
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:8000
elif command -v open &> /dev/null; then
    open http://localhost:8000
fi

echo ""
echo "系统已启动!"
echo "API文档: http://localhost:8000/docs"
echo "Web界面: http://localhost:8000"
