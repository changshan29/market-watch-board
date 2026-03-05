# Railway 部署指南

## 快速部署步骤

### 1. 访问 Railway
https://railway.app

### 2. 登录
- 点击右上角 "Login"
- 选择 "Login with GitHub"
- 授权 Railway 访问你的 GitHub 账号

### 3. 创建新项目
- 点击 "New Project"
- 选择 "Deploy from GitHub repo"
- 找到并选择 `changshan29/market-watch-board`
- 点击 "Deploy Now"

### 4. 等待部署完成
Railway 会自动：
- 检测 Node.js 项目
- 安装 Python 依赖
- 启动服务器
- 分配公开域名

部署时间：约 2-3 分钟

### 5. 获取访问链接
部署完成后：
- 点击项目
- 点击 "Settings" 标签
- 找到 "Domains" 部分
- 点击 "Generate Domain"
- 复制生成的链接，格式类似：
  ```
  https://market-watch-board-production.up.railway.app
  ```

### 6. 初始化数据
部署完成后需要运行一次爬取：

```bash
# 安装 Railway CLI
npm install -g @railway/cli

# 登录
railway login

# 连接到项目
railway link

# 运行初始爬取
railway run python3 run_cailianshe_2.py --no-kb --fast
```

或者在 Railway 网页控制台：
- 点击项目
- 点击 "Deployments" 标签
- 点击最新的部署
- 点击右上角 "..." → "View Logs"
- 等待服务启动后，在本地运行一次爬取脚本

---

## 访问测试

部署完成后，访问你的链接：
```
https://你的域名.up.railway.app
```

应该能看到"盯盘资讯看板"页面。

初始状态下没有数据，需要运行一次爬取脚本填充数据。

---

## 分享给朋友

使用 SHARE.md 中的文案，将链接替换为你的 Railway 域名即可。

---

## 常见问题

### Q: 部署失败？
A: 检查 Railway 日志，常见原因：
- Python 依赖安装失败
- 端口配置问题（Railway 会自动设置 PORT 环境变量）

### Q: 访问显示 404？
A: 等待 1-2 分钟，Railway 需要时间启动服务

### Q: 没有数据？
A: 需要手动运行一次爬取脚本初始化数据

### Q: 如何更新代码？
A:
```bash
git add .
git commit -m "更新说明"
git push
```
Railway 会自动重新部署
