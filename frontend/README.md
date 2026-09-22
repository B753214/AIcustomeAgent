# 智能客服控制台（React 18）

与旧版 `app/static/dashboard.html`（`/dashboard`）**并存**，互不替代。

| 前端 | 地址 | 说明 |
|------|------|------|
| 旧版 HTML | `http://127.0.0.1:8000/dashboard` | 原单页控制台 |
| React（开发） | `http://127.0.0.1:5173` | `npm run dev` |
| React（生产） | `http://127.0.0.1:8000/console/` | 先 `npm run build`，由 FastAPI 托管 |

页面右上角可互相跳转。

## 技术栈

- React 18
- TypeScript
- Vite 5

## 启动

```bash
# 后端 :8000
# 前端开发
cd frontend
npm install
npm run dev
```

## 构建并由后端托管

```bash
cd frontend
npm run build
# 然后访问 http://127.0.0.1:8000/console/
```
