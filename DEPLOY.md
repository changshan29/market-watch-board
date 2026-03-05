# 财联社项目二 - 云部署指南

## 方案选择：Railway（推荐）

**优势**：
- ✓ 免费额度：500小时/月（够用）
- ✓ 自动部署：连接 GitHub 自动部署
- ✓ 支持 Node.js + Python
- ✓ 提供免费域名

---

## 部署步骤

### 1. 准备 GitHub 仓库

```bash
cd /Users/liu/cailianshe-p2

# 初始化 Git（如果还没有）
git init
git add .
git commit -m "Initial commit"

# 创建 GitHub 仓库（在 GitHub 网站上创建）
# 然后推送代码
git remote add origin https://github.com/你的用户名/cailianshe-p2.git
git branch -M main
git push -u origin main
```

### 2. 部署到 Railway

1. 访问 https://railway.app
2. 使用 GitHub 账号登录
3. 点击 "New Project" → "Deploy from GitHub repo"
4. 选择 `cailianshe-p2` 仓库
5. Railway 会自动检测并部署

### 3. 配置环境变量（可选）

在 Railway 项目设置中添加：
- `PORT`: 3220（默认）
- `NODE_ENV`: production

### 4. 获取访问链接

部署完成后，Railway 会提供一个公开 URL：
```
https://你的项目名.up.railway.app
```

---

## 方案二：Render（备选）

### 部署步骤

1. 访问 https://render.com
2. 使用 GitHub 登录
3. 点击 "New +" → "Web Service"
4. 连接 GitHub 仓库
5. 配置：
   - **Name**: cailianshe-p2
   - **Environment**: Node
   - **Build Command**: `pip3 install -r requirements.txt`
   - **Start Command**: `node server.js`
   - **Plan**: Free

---

## 访问控制说明

### 外部用户（试用）
- ✓ 可访问：看板首页（`/`）
- ✓ 可访问：文章列表 API（`/api/articles`）
- ✓ 可访问：概念筛选 API（`/api/ai-filter`）
- ✗ 不可访问：后台管理（`/admin`）
- ✗ 不可访问：配置修改接口

### 本地管理员（你）
- ✓ 完全访问权限
- ✓ 通过 SSH 隧道访问后台：
  ```bash
  ssh -L 3220:localhost:3220 你的服务器
  # 然后访问 http://localhost:3220/admin
  ```

---

## 初始数据配置

部署后，你需要通过 SSH 或 Railway CLI 配置初始数据：

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

---

## 监控和维护

### 查看日志
```bash
railway logs
```

### 手动触发爬取
```bash
railway run python3 run_cailianshe_2.py --no-kb --fast
```

### 更新代码
```bash
git add .
git commit -m "更新说明"
git push
# Railway 会自动重新部署
```

---

## 成本估算

### Railway 免费套餐
- 500 小时/月（约 20 天 24 小时运行）
- 100GB 出站流量
- 512MB RAM
- 1GB 磁盘

**预计消耗**：
- 运行时间：~720 小时/月（需要付费或优化）
- 流量：~5GB/月（够用）

**优化建议**：
- 使用 Railway 的 Sleep 功能（无访问时自动休眠）
- 或升级到 Hobby 套餐（$5/月，无限时长）

---

## 分享试用链接

部署完成后，分享给朋友：

```
试用链接：https://你的项目名.up.railway.app

说明：
- 这是一个财经资讯聚合看板
- 自动抓取财联社、同花顺、雪球等平台的最新资讯
- 支持按来源、主题、概念筛选
- 每 15 秒自动更新
```

---

## 常见问题

### Q: 部署后无数据？
A: 需要手动运行一次爬取：
```bash
railway run python3 run_cailianshe_2.py --no-kb --fast
```

### Q: 如何修改爬取源？
A: 通过 SSH 隧道访问后台管理页面

### Q: Railway 免费额度用完了？
A:
1. 升级到 Hobby 套餐（$5/月）
2. 或迁移到 Render（免费但有限制）
3. 或使用 Vercel + Serverless（需要改造）

### Q: 如何备份数据？
A:
```bash
railway run cat data/articles.json > backup.json
```
