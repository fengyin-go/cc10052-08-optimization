"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import report_workflow, resource

# 专用路由必须在通用资源路由（含 /api/{module} 动态路径）之前注册，
# 否则 /api/report_dist/continuation 等固定路径会被动态路由抢先匹配。
ROUTERS = [report_workflow, resource]
