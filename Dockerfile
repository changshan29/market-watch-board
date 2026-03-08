FROM python:3.10-slim

# 安装系统依赖 + Chromium（apt 安装，版本自动匹配 chromium-driver，无需外网下载）
RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libatspi2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libwayland-client0 libxcomposite1 libxdamage1 \
    libxfixes3 libxkbcommon0 libxrandr2 xdg-utils curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
COPY requirements.txt ./

RUN npm install
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

# Railway 动态端口，不写死 EXPOSE
CMD ["node", "server.js"]
