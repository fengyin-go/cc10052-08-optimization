# 实验指标分析与归因评估平台

支撑AB实验分组、指标口径计算、显著性检验、归因分析与报告分发的实验评估平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8022/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5202/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8022`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 事件接入 | `event_stream` | 事件定义 | 事件编码、事件名称、属性字段 |
| 实验设计 | `exp_design` | 实验方案 | 实验编码、实验名称、分组策略 |
| 分组分配器 | `variant_assign` | 分组结果 | 分配批次、用户标识、实验编码 |
| 指标口径中心 | `metric_catalog` | 指标定义 | 指标编码、指标名称、计算口径 |
| 指标计算作业 | `metric_compute` | 计算作业 | 作业名称、指标编码、计算窗口 |
| 显著性检验 | `significance_test` | 检验结果 | 检验批次、实验编码、指标编码 |
| 归因分析器 | `attr_analysis` | 归因结果 | 归因批次、实验编码、贡献因子 |
| 人群圈选器 | `cohort_builder` | 人群包 | 人群编码、人群名称、圈选条件 |
| 报告生成器 | `report_gen` | 分析报告 | 报告编码、实验编码、报告模板 |
| 报告分发 | `report_dist` | 分发记录 | 分发批次、报告编码、接收方 |
| 窗口调度器 | `window_scheduler` | 调度计划 | 计划名称、指标编码、窗口粒度 |
| 数据时效监控 | `data_freshness` | 时效记录 | 监控对象、数据域、最新水位 |
| 指标异常检测 | `anomaly_metric` | 异常事件 | 异常编号、指标编码、基线区间 |
| 实验归档库 | `exp_archive` | 归档实验 | 实验编码、结束时间、结论摘要 |
| 样本量核对 | `sample_ratio` | 核对结果 | 核对批次、实验编码、计划比例 |
| AA预检器 | `aa_check` | AA检验 | 检验编码、实验编码、检验窗口 |
| 切片分析器 | `segment_slice` | 切片结果 | 切片批次、实验编码、切片维度 |
| 曝光日志接入 | `exposure_log` | 曝光记录 | 日志批次、实验编码、用户标识 |
| 结论评审队列 | `conclusion_review` | 评审记录 | 记录编号、实验编码、评审结论 |
| 指标查询服务 | `metric_api` | 查询接口 | 接口编码、指标编码、服务对象 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 报告分发续做与评审证据（`report_dist` / `conclusion_review`）

`报告分发·续做工作台`（`/report_dist`）与`结论评审·证据领用`（`/conclusion_review`）
是两个专用页面，配套路由在 `backend/app/routers/report_workflow.py`，规则如下：

- **续做不重建投递**：断线重发按「报告版次 + 接收方」去重；失败/拒收记录推进到
  「续做中」复用原记录，值班员只处理确实未送达的收件人（`GET /api/report_dist/continuation`）。
- **唯一有效签收**：同一「报告版次 + 接收方 + 分发渠道」只有一份有效签收，存于
  `dist_receipt` 表；重复送达幂等返回原回执，材料只送达一次。
- **版次互不阻断**：同一接收方的不同报告版次（如 R-v1、R-v2）分别送达、分别查证，
  重发不会因名字或旧版次状态阻断新版。
- **部分送达可独立引用**：整组批量分发中途失败时，已送达部分立即形成有效回执，
  未送达人留在续做清单可继续办理。
- **代领资格可追溯**：续做期间可登记/撤换代领资格（`dist_proxy` 表），实际签收时
  把使用的资格编号写在回执上；撤换只影响后续，历史回执仍能看出当时用了哪份资格。
  本人地址仍有效且选择本人办理时，本人优先于代领资格。
- **投递详情分区**：`GET /api/report_dist/{id}/detail` 把「可续办（未送达）」与
  「已签收」分开，并附代领资格沿革。
- **评审按版次领用**：评审人员从对应版次选择已送达证据
  （`GET /api/conclusion_review/evidence/versions`），不必等整组全部完成；
  只有实际签收人（含代领人）的有效回执能被领用（`.../claim`），证据明细按报告版本
  列出实际送达的人；未领用证据的评审记录不能通过。

端到端规则验证（含 R-v2 的 A 已签收、B 拒收续做、代领冲突、分版次评审全链路）：

```bash
cd backend
PYTHONPATH=. .venv/bin/python tests/e2e_report_workflow.py
```

领域：数据工程
子方向：数据分析与数据应用
