# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

- 锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`，出胶只看峰值，与清灰单无关。
- 「冷锅」改成「熬煮中」前，该锅必须挂着一张**未核销的灶膛清灰单**；没有则服务端中文挡住（锅位抽屉和清灰专页同一接口，都拦）。
- 清灰单字段：锅、单号（正整数）、清灰人、清灰时刻、核销时刻（可空）。同一锅未核销单最多一张，由部分唯一索引 `ux_ash_ticket_open_per_kettle` 在库内兜底，并发交单只入库一张。
- 操作工可在「清灰单」专页开单、核销，并按锅筛选未核销单。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
