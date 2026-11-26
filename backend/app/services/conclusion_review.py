"""结论评审队列领域服务：管理实验结论的评审流转、证据领用签收与办结归档。

数据链路位置：评审治理层，是实验结论进入业务决策前的最后一道人工关，消费
报告分发与异常处置的评审请求，把通过结论推送归档。

评审证据规则（评审要点）：
- 评审人员从对应报告版次选择「已送达」证据，不必等整组全部完成即可领用签收。
- 领用签收只认有效回执；同一版次+接收方+渠道只有一份有效签收，证据不会重复。
- 实际复核时按投递批次采纳当前报告版次的真实回执，证据明细按报告版本列出实际送达的人。
- 同一接收方的不同报告版次分别查证：R-v1 在自己的评审中单独查证，不与 R-v2 混用。
- 只有实际签收人（含生效代领人）签收的那份材料才能作为本轮评审证据。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.report_dist import _next_id, _now, _version_of
from app.store import store


class ConclusionReviewService(BaseModuleService):
    MODULE = "conclusion_review"
    ENTITY = "评审记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["记录编号", "实验编码", "评审结论", "评审角色", "评审时间"]
    REQUIRED_FIELDS = ["记录编号", "实验编码", "评审结论"]
    STATUS_ORDER = ["待评审", "已通过", "已驳回"]
    ACTION_RULES = {"通过记录": "已通过", "驳回记录": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回记录"]

    # ---- 评审证据：按报告版次采纳真实送达回执 ----

    def evidence_versions(self, report_code: str | None = None) -> list[dict[str, Any]]:
        """按报告版次汇总可引用的有效签收：评审人员从对应版次选已送达证据。"""
        receipt_rows = store.rows("dist_receipt")
        grouped: dict[str, dict[str, Any]] = {}
        for receipt in receipt_rows:
            if receipt.get("签收状态") != "有效":
                continue
            if report_code and str(receipt.get("报告编码", "")) != report_code:
                continue
            version = str(receipt.get("报告版次", ""))
            bucket = grouped.setdefault(version, {
                "报告版次": version,
                "报告编码": receipt.get("报告编码", ""),
                "有效签收数": 0,
                "实际送达的人": [],
                "投递批次": set(),
            })
            bucket["有效签收数"] += 1
            bucket["实际送达的人"].append({
                "接收方": receipt.get("接收方", ""),
                "实际签收人": receipt.get("实际签收人", ""),
                "分发渠道": receipt.get("分发渠道", ""),
                "是否代领": receipt.get("是否代领", False),
                "使用代领资格": receipt.get("使用代领资格", ""),
                "回执编号": receipt.get("回执编号", ""),
                "分发批次": receipt.get("分发批次", ""),
                "送达时间": receipt.get("送达时间", ""),
            })
            bucket["投递批次"].add(str(receipt.get("分发批次", "")))
        result = []
        for version, bucket in grouped.items():
            bucket["投递批次"] = sorted(b for b in bucket.pop("投递批次") if b)
            result.append(bucket)
        return sorted(result, key=lambda item: item["报告版次"])

    def available_evidence(self, report_version: str) -> dict[str, Any]:
        """列出某版次当前所有有效签收证据；整组未全部完成时已送达部分也可独立引用。"""
        receipts = [
            r for r in store.rows("dist_receipt")
            if r.get("签收状态") == "有效" and str(r.get("报告版次", "")) == report_version
        ]
        if not receipts:
            return {
                "ok": True,
                "报告版次": report_version,
                "可领用": False,
                "message": "该版次暂无有效签收，等待送达后再领用",
                "items": [],
            }
        return {
            "ok": True,
            "报告版次": report_version,
            "可领用": True,
            "message": f"该版次已有 {len(receipts)} 份有效签收，可独立领用，无需等整组完成",
            "items": [
                {
                    "回执编号": r.get("回执编号", ""),
                    "分发批次": r.get("分发批次", ""),
                    "接收方": r.get("接收方", ""),
                    "实际签收人": r.get("实际签收人", ""),
                    "分发渠道": r.get("分发渠道", ""),
                    "是否代领": r.get("是否代领", False),
                    "使用代领资格": r.get("使用代领资格", ""),
                    "送达时间": r.get("送达时间", ""),
                }
                for r in receipts
            ],
        }

    def claim_evidence(
        self,
        entry_id: int,
        report_version: str,
        receipt_id: int,
        reviewer: str,
    ) -> dict[str, Any]:
        """评审队列领用签收：把有效回执挂到评审记录上，并在回执侧登记领用。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        receipt = next(
            (r for r in store.rows("dist_receipt") if int(r.get("id", 0)) == receipt_id), None
        )
        if receipt is None or receipt.get("签收状态") != "有效":
            return {"ok": False, "message": "回执不存在或不是有效签收，不能领用"}
        if str(receipt.get("报告版次", "")) != report_version:
            return {"ok": False, "message": "回执版次与评审选择的报告版次不一致"}

        claimed = entry.setdefault("已领证据", [])
        # 同一评审记录对同一回执只领用一次
        if any(int(item.get("回执id", 0)) == receipt_id for item in claimed):
            return {"ok": False, "message": "该回执已被本评审记录领用，请勿重复签收"}

        claim = {
            "回执id": receipt_id,
            "回执编号": receipt.get("回执编号", ""),
            "报告版次": report_version,
            "分发批次": receipt.get("分发批次", ""),
            "接收方": receipt.get("接收方", ""),
            "实际签收人": receipt.get("实际签收人", ""),
            "分发渠道": receipt.get("分发渠道", ""),
            "是否代领": receipt.get("是否代领", False),
            "领用评审员": reviewer or "值班评审员",
            "领用时间": _now(),
        }
        claimed.append(claim)
        entry["证据版次"] = report_version
        entry["pending"] = True

        # 回执回写领用信息；代领资格的「已使用」在实际送达签收时已留痕，这里只做引用
        receipt["领用评审记录"] = entry.get("记录编号", "")
        return {
            "ok": True,
            "message": f"已领用 {report_version} 回执 {receipt.get('回执编号')}（实际签收人 {receipt.get('实际签收人')}）",
            "claim": claim,
        }

    def evidence_detail(self, entry_id: int) -> dict[str, Any]:
        """评审证据明细：按报告版本列出实际送达的人，供实际复核时核对。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in entry.get("已领证据", []):
            grouped.setdefault(str(claim.get("报告版次", "")), []).append({
                "回执编号": claim.get("回执编号", ""),
                "分发批次": claim.get("分发批次", ""),
                "接收方": claim.get("接收方", ""),
                "实际签收人": claim.get("实际签收人", ""),
                "分发渠道": claim.get("分发渠道", ""),
                "是否代领": claim.get("是否代领", False),
                "领用评审员": claim.get("领用评审员", ""),
                "领用时间": claim.get("领用时间", ""),
            })
        return {
            "ok": True,
            "记录编号": entry.get("记录编号", ""),
            "评审状态": entry.get("status", ""),
            "按版次证据": [
                {"报告版次": version, "实际送达的人": items}
                for version, items in sorted(grouped.items())
            ],
        }

    # ---- 业务扩展：评审流转与结论归档 ----

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """通用动作入口与专用接口采用同一套业务门槛，避免从工作台绕过证据要求。"""
        if action == "通过记录":
            out = self.approve(entry_id, "")
            if not out.get("ok"):
                return None, str(out.get("message", ""))
            return store.find(self.MODULE, entry_id), str(out.get("message", ""))
        if action == "驳回记录":
            # 通用入口无法携带原因，给出固定原因，仍走服务层联动停止分发
            out = self.reject(entry_id, "工作台通用驳回")
            if not out.get("ok"):
                return None, str(out.get("message", ""))
            return store.find(self.MODULE, entry_id), str(out.get("message", ""))
        return super().run_action(entry_id, action)

    def approve(self, entry_id: int, comment: str) -> dict[str, Any]:
        """通过评审记录并把结论推送到实验归档库；复核时按投递批次采纳当前版次真实回执。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待评审":
            return {"ok": False, "message": "仅待评审记录可通过"}
        if not entry.get("已领证据"):
            return {"ok": False, "message": "请先按报告版次领用有效送达证据，再通过评审"}
        entry["status"] = "已通过"
        entry["pending"] = False
        entry["评审时间"] = _now()
        entry["评审意见"] = comment or "同意采纳"
        archive_rows = store.rows("exp_archive")
        evidence_versions = sorted({c.get("报告版次", "") for c in entry.get("已领证据", [])})
        archive_rows.append({
            "id": _next_id(archive_rows),
            "实验编码": entry.get("实验编码", ""),
            "结束时间": _now(),
            "结论摘要": (
                f"评审通过：{entry.get('评审结论', '')}；"
                f"采纳版次 {','.join(v for v in evidence_versions if v)} 真实回执 "
                f"{len(entry.get('已领证据', []))} 份"
            ),
            "归档位置": f"review/{entry.get('记录编号', '')}",
            "保留等级": "标准",
            "status": "待归档",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": f"记录 {entry.get('记录编号')} 已通过并推送归档"}

    def reject(self, entry_id: int, reason: str) -> dict[str, Any]:
        """驳回评审记录并通知报告分发停止后续分发。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待评审":
            return {"ok": False, "message": "仅待评审记录可驳回"}
        if not reason.strip():
            return {"ok": False, "message": "驳回必须填写原因"}
        entry["status"] = "已驳回"
        entry["pending"] = False
        entry["abnormal"] = True
        entry["驳回原因"] = reason
        exp_code = str(entry.get("实验编码", ""))
        stalled = [
            r for r in store.rows("report_dist")
            if exp_code and exp_code in str(r.get("报告编码", "")) and r.get("status") == "排队中"
        ]
        for row in stalled:
            row["status"] = "送达失败"
            row["abnormal"] = True
            row["失败原因"] = "结论被驳回，停止分发"
        return {"ok": True, "message": f"记录已驳回，联动停止 {len(stalled)} 条分发"}

    def batch_approve(self) -> dict[str, Any]:
        """批量通过全部已领用证据的待评审记录。"""
        pending = [r for r in store.rows(self.MODULE) if r.get("status") == "待评审"]
        done, blocked = 0, 0
        for r in pending:
            if self.approve(int(r.get("id", 0)), "").get("ok"):
                done += 1
            else:
                blocked += 1
        return {"ok": True, "message": f"批量通过 {done} 条，缺证据未通过 {blocked} 条"}

    def consume_from_report_dist(self, exp_code: str) -> list[dict[str, Any]]:
        """读取报告分发的有效签收作为评审证据材料，按版次区分。"""
        return [
            {
                "报告版次": r.get("报告版次", ""),
                "报告编码": r.get("报告编码", ""),
                "接收方": r.get("接收方", ""),
                "实际签收人": r.get("实际签收人", ""),
                "分发渠道": r.get("分发渠道", ""),
                "送达时间": r.get("送达时间", ""),
            }
            for r in store.rows("dist_receipt")
            if (
                r.get("签收状态") == "有效"
                and exp_code
                and exp_code in str(r.get("报告编码", ""))
            )
        ]

    def consume_from_anomaly_metric(self, exp_code: str) -> list[dict[str, Any]]:
        """读取指标异常检测的待确认事件，合并进评审材料。"""
        return [
            {"异常编号": r.get("异常编号", ""), "异常评分": r.get("异常评分", "")}
            for r in store.rows("anomaly_metric")
            if r.get("status") in ("待确认", "已确认")
            and exp_code in str(r.get("指标编码", ""))
        ]

    def reopen_rejected(self, entry_id: int) -> dict[str, Any]:
        """重开已驳回记录：修正结论后回到待评审。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已驳回":
            return {"ok": False, "message": "仅已驳回记录可重开"}
        entry["status"] = "待评审"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["重开次数"] = str(int(entry.get("重开次数", "0") or 0) + 1)
        return {"ok": True, "message": f"记录已重开（第 {entry['重开次数']} 次）"}

    def export_review_queue(self) -> list[dict[str, Any]]:
        """导出待评审队列，供指标查询服务展示办结进度。"""
        return [
            {
                "记录编号": r.get("记录编号", ""),
                "实验编码": r.get("实验编码", ""),
                "评审角色": r.get("评审角色", ""),
                "进入时间": r.get("评审时间", ""),
                "证据版次": r.get("证据版次", ""),
                "已领证据数": len(r.get("已领证据", [])),
            }
            for r in store.rows(self.MODULE) if r.get("status") == "待评审"
        ]
