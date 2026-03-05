# Render Docker 部署配置指南

## 背景
为了在Render上运行雪球爬虫（需要Selenium和Chrome），我们需要从Nixpacks切换到Docker部署。

## 配置步骤

### 1. 登录Render控制台
访问：https://dashboard.render.com

### 2. 找到你的服务
在Dashboard中找到 `market-watch-board` 服务，点击进入

### 3. 进入设置页面
点击左侧菜单的 **Settings** 按钮

### 4. 修改构建配置

#### 4.1 找到 "Build & Deploy" 部分
向下滚动找到 "Build & Deploy" 配置区域

#### 4.2 修改 Build Command
- 找到 **Build Command** 字段
- 输入：`echo "Building with Docker"`
- 原因：Render要求该字段不能为空，但Docker构建会忽略此命令

#### 4.3 修改 Start Command
- 找到 **Start Command** 字段
- 输入：`node server.js`
- 原因：指定容器启动命令

#### 4.4 确认Docker配置
- 找到 **Docker** 部分
- 确认 **Dockerfile Path** 为：`./Dockerfile`
- 如果没有这个字段，Render会自动检测到Dockerfile

### 5. 保存并部署

#### 5.1 保存设置
- 点击页面底部的 **Save Changes** 按钮

#### 5.2 触发重新部署
- 方式1：点击右上角的 **Manual Deploy** → **Deploy latest commit**
- 方式2：等待自动部署（Render检测到GitHub更新会自动部署）

### 6. 等待部署完成

#### 6.1 查看部署日志
- 点击顶部的 **Logs** 标签
- 观察构建过程，应该能看到：
  ```
  ==> Building with Dockerfile
  ==> Downloading base image
  ==> Installing Chrome
  ==> Installing Python dependencies
  ==> Installing Node.js dependencies
  ```

#### 6.2 预计时间
- 首次Docker构建：**5-10分钟**（需要下载Chrome等大型依赖）
- 后续构建：**2-3分钟**（使用缓存）

### 7. 验证部署

#### 7.1 检查服务状态
- 等待状态变为 **Live**（绿色）

#### 7.2 访问网站
- 打开：https://market-watch-board.onrender.com
- 检查是否有数据显示

#### 7.3 检查雪球功能
- 等待几分钟让爬虫运行
- 刷新页面，查看"雪球"区域是否有内容

#### 7.4 查看调试信息（可选）
- 访问：https://market-watch-board.onrender.com/api/debug
- 检查 `lastScrapeStatus` 是否为 `"success"`
- 检查 `articlesCount` 是否大于0

## 常见问题

### Q1: 部署失败，显示 "Out of memory"
**解决方案**：
- Render免费套餐内存有限（512MB）
- 可能需要升级到付费套餐（$7/月，512MB → 2GB）

### Q2: 部署成功但雪球区域仍然没有数据
**检查步骤**：
1. 访问 `/api/debug` 查看错误信息
2. 检查 `sources.json` 中是否配置了雪球用户
3. 等待15-30秒让爬虫完成首次运行

### Q3: Chrome启动失败
**可能原因**：
- 内存不足
- Chrome需要的系统库缺失

**解决方案**：
- 检查Dockerfile中的依赖包是否完整
- 升级到付费套餐获得更多内存

### Q4: 如何回退到Nixpacks部署？
如果Docker部署有问题，可以回退：
1. 删除仓库中的 `Dockerfile`
2. 在Render Settings中恢复原来的Build Command
3. 重新部署

## 部署后的系统架构

```
Render Docker容器
├── Python 3.10
├── Node.js 18
├── Google Chrome (headless)
├── Selenium WebDriver
├── 项目代码
│   ├── server.js (Node.js服务)
│   ├── scrapers/ (Python爬虫)
│   │   ├── cls_telegraph.py (财联社)
│   │   ├── webpage.py (同花顺)
│   │   └── xueqiu.py (雪球 - Selenium)
│   └── data/articles.json (数据存储)
└── 自动刷新机制 (每15秒)
```

## 预期结果

部署成功后，你的看板应该显示：
- ✅ 网页区域：财联社、同花顺的实时资讯
- ✅ 雪球区域：配置用户的最新帖子
- ✅ 自动刷新：每15秒更新一次数据

## 需要帮助？

如果遇到问题，可以：
1. 查看Render的部署日志（Logs标签）
2. 访问 `/api/debug` 查看系统状态
3. 检查GitHub仓库确认Dockerfile已推送

---

**创建时间**：2026-03-05  
**版本**：1.0
