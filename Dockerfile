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

# 安装Chrome（使用现代GPG密钥管理方式）
  RUN wget -q -O /tmp/google-chrome-key.pub
  https://dl-ssl.google.com/linux/linux_signing_key.pub \
      && gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg
  /tmp/google-chrome-key.pub \
      && echo "deb [arch=amd64
  signed-by=/usr/share/keyrings/google-chrome-keyring.gpg]
  http://dl.google.com/linux/chrome/deb/ stable main" >
  /etc/apt/sources.list.d/google-chrome.list \
      && apt-get update \
      && apt-get install -y google-chrome-stable \
      && rm -rf /var/lib/apt/lists/* /tmp/google-chrome-key.pub

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

# 启动命令
CMD ["node", "server.js"]
