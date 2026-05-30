# 部署说明

当前项目先按静态网站部署，产品名为 `hk-ipo`，入口文件是 `hk-ipo.html`。旧 `数据检查.html` 只保留为跳转兼容页。

## 推荐首发

1. 把项目推到 GitHub。
2. 在 Vercel 新建项目并导入该仓库。
3. Framework 选择 `Other` 或默认静态站。
4. Build Command 留空。
5. Output Directory 留空。
6. 部署完成后访问 Vercel 给出的域名。

当前生产地址：

- https://hk-ipo-dashboard-zhoujianzhi91-commits-projects.vercel.app/hk-ipo

## 需要部署的静态资源

- `index.html`
- `hk-ipo.html`
- `数据检查.html`（旧入口跳转页）
- `data/*.js`
- `data/*.xlsx`
- `vendor/lightweight-charts.standalone.production.js`
- `vercel.json`

`.vercelignore` 会排除爬虫原始文件、脚本、日志、PDF/TXT 缓存和实验产物，避免首次部署包过大。

## 后续维护

页面和数据更新仍然在仓库里完成。提交到 GitHub 后，Vercel 会自动重新部署。没有 Codex 订阅时，网站仍会继续运行；只是以后改代码需要用 VS Code、GitHub 网页、其他 AI 工具或找开发者处理。

## 自动更新

`Update IPO data` GitHub Actions 会每 15 分钟运行一次。脚本只处理活跃新股候选：

- 开启招股。
- 申购结束 / 待暗盘。
- 今日暗盘。
- 今日上市。
- 暗盘结束 / 待上市。

已上市历史股票和延迟上市 / 特殊情况股票不进入自动刷新；这些内容通过手动修正、提交和部署维护。

自动更新流程：

1. 运行 `scripts/run_official_update.py`。
2. 如果 `data/*.js` 有有效变化，自动提交 `Update IPO data snapshot`。
3. 如果有数据变化、手动运行时选择 `force_deploy=true`，或直接 push 到 `main`，自动部署到 Vercel。
4. 部署前通过 Vercel CLI 生成静态输出并发布。

GitHub Actions 需要以下 Secrets：

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Vercel 项目不要开启 SSO 部署保护；否则免费域名会显示登录保护页，自动部署也可能返回异常状态。当前项目已关闭 SSO 保护。
