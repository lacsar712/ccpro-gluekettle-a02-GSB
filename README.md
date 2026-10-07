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

- 锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`，出胶只看峰值。
- 冷锅改成「熬煮中」前，该锅必须挂着一张**未核销的灶膛清灰单**，否则中文挡住；清灰单不掺进出胶判断。
- 灶膛清灰单字段：锅、单号（正整数）、清灰人、清灰时刻、核销时刻（可空）。同一锅未核销单最多一张，由 `ash_tickets` 上的部分唯一索引 `(kettle_id) WHERE redeemed_at IS NULL` 在数据库层兜底（含并发抢开）。
- 操作工可在「灶膛清灰单」专页开单、核销、按锅筛选；种子数据中冷锅零单。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
