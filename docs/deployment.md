# 部署说明

当前项目先按静态网站部署，入口是 `数据检查.html`，根路径 `/` 会跳到这个页面。

## 推荐首发

1. 把项目推到 GitHub。
2. 在 Vercel 新建项目并导入该仓库。
3. Framework 选择 `Other` 或默认静态站。
4. Build Command 留空。
5. Output Directory 留空。
6. 部署完成后访问 Vercel 给出的域名。

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
