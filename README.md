# 光伏组串IV扫描台

扫描员提交组串开路电压、短路电流与填充因子。写入后走 PostgreSQL 通知通道叫醒独立工人，工人不轮询空转。填充因子不低于 0.72 为合格，否则衰减。页面是 Vue 3。

## 黄金窗曲线册

逆变器刚启动后的十分钟叫黄金窗。顶栏点「黄金窗」进专页，分窗名区、在途轨迹区、查阅区，空着时显示"还没有曲线"。

- 有写权限的扫描员填册名后按「封存」，把此刻在途（待处理）各串读数抄进曲线册；观察员只能翻旧曲线，不能按封存。
- 册名和点列在同一次写入落库，缺一边整页不算完工（空册名或没有在途曲线都会报错且不留残册）。
- 封进册以后就算在线单再办结也刮不掉这本册：册内是当时的快照，旧册随时能翻开看到当时在途的各串。

接口：`GET /api/golden-window/books`（登录可查）、`POST /api/golden-window/seal`（仅扫描员，Body `{"name": "册名"}`）。

## 技术栈

- 后端：Litestar、Uvicorn、psycopg 同步写入
- 工人：`LISTEN/NOTIFY` 唤醒后认领
- 前端：Vue 3、Vite、nginx 反代 `/api`

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3202 |
| 接口 | http://localhost:8202 |
| PostgreSQL | localhost:54402（库名 `pvivscan`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| scanner | scan123456 | 可提交 |
| watcher | watch123456 | 只读 |

## 启动

```bash
cd projects/22-pv-string-iv-scan
docker compose up --build
```

健康检查：`GET http://localhost:8202/api/health`

## 种子

| 组串 | 填充因子 | 结论 |
|------|----------|------|
| 阵列A-串03 | 0.78 | 合格 |
| 阵列B-串11 | 0.61 | 衰减 |
