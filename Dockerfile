FROM python:3.10-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 直接下载Chrome deb包
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN apt-get update
RUN apt-get install -y ./google-chrome-stable_current_amd64.deb
RUN rm google-chrome-stable_current_amd64.deb
RUN rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY package*.json ./
COPY requirements.txt ./

# 安装Node.js依赖
RUN npm install

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有项目文件
COPY . .

# 创建数据目录
RUN mkdir -p data

# 暴露端口
EXPOSE 3220

# 验证Python安装
RUN python3 --version && which python3 && ls -la /app/run_cailianshe_2.py

# 启动命令
CMD ["node", "server.js"]
