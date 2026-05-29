# 部署说明

当前项目先按静态网站部署，入口是 `数据检查.html`，根路径 `/` 会跳到这个页面。

## 推荐首发

1. 把项目推到 GitHub。
2. 在 Vercel 新建项目并导入该仓库。
3. Framework 选择 `Other` 或默认静态站。
4. Build Command 留空。
5. Output Directory 留空。
6. 部署完成后访问 Vercel 给出的域名。

当前生产地址：

- https://hk-ipo-dashboard-zhoujianzhi91-commits-projects.vercel.app/数据检查

## 需要部署的静态资源

- `index.html`
- `数据检查.html`
- `data/*.js`
- `data/*.xlsx`
- `vendor/lightweight-charts.standalone.production.js`
- `vercel.json`

`.vercelignore` 会排除爬虫原始文件、脚本、日志、PDF/TXT 缓存和实验产物，避免首次部署包过大。

## 后续维护

页面和数据更新仍然在仓库里完成。提交到 GitHub 后，Vercel 会自动重新部署。没有 Codex 订阅时，网站仍会继续运行；只是以后改代码需要用 VS Code、GitHub 网页、其他 AI 工具或找开发者处理。

## 自动更新

`Update IPO data` GitHub Actions 会定时运行：

- 港股交易日 09:00-12:45：跟踪招股中的认购倍数、招股资料。
- 港股交易日 16:15-18:45：跟踪暗盘窗口。
- 港股交易日 21:00-23:45：跟踪配发结果公告。
- 周二至周六 00:00-00:45：补抓深夜发布的配发结果。

自动更新流程：

1. 运行 `scripts/run_official_update.py`。
2. 如果 `data/*.js` 有有效变化，自动提交 `Update IPO data snapshot`。
3. 如果有数据变化，或手动运行时选择 `force_deploy=true`，自动部署到 Vercel。

GitHub Actions 需要以下 Secrets：

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Vercel 项目不要开启 SSO 部署保护；否则免费域名会显示登录保护页，自动部署也可能返回异常状态。当前项目已关闭 SSO 保护。
