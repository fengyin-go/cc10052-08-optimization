"""报告分发领域服务：管理分析报告的分版次分发、送达回执、失败续做与代领资格。

数据链路位置：报告分发层，是实验评估数据流出平台的最后一环，消费报告生成器
的成品报告，把送达回执写回报告生成器形成闭环。

核心规则（评审要点）：
- 同一「报告版次 + 接收方 + 分发渠道」只允许一份有效签收，重复续做不会再建投递。
- 整组（整批次）分发中途失败时，已送达部分独立形成可引用回执，未送达人可逐条续做。
- 续做不新建分发记录，只把原失败/拒收记录推进到「续做中」，续做完成复用原记录。
- 续做期间可登记/撤换代领资格，实际签收人记录在回执上，能看出用了哪一份资格。
- 同一接收方的不同报告版次互不阻断：R-v1 的签收与否不影响 R-v2 的重发与签收。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 签收后不再参与续做/重投的终态
DELIVERED_STATUS = "已送达"
# 需要值班员续做的未送达状态
UNDERIVERED_STATUSES = ("送达失败", "已拒收", "续做中")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


def _version_of(row: dict[str, Any]) -> str:
    """报告版次优先取显式版次字段，兼容只写报告编码的旧记录。"""
    return str(row.get("报告版次") or row.get("报告编码") or "")


class ReportDistService(BaseModuleService):
    MODULE = "report_dist"
    ENTITY = "分发记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["分发批次", "报告版次", "报告编码", "接收方", "分发渠道", "送达状态"]
    REQUIRED_FIELDS = ["分发批次", "报告编码", "接收方"]
    # 新增「已拒收」「续做中」两个显式状态，原有三个状态含义保持不变
    STATUS_ORDER = ["排队中", "已送达", "送达失败", "已拒收", "续做中"]
    ACTION_RULES = {"开始分发": "已送达", "重试分发": "送达失败"}
    NEGATIVE_ACTIONS = []

    # ============ 回执（签收）查询 ============

    def receipt_rows(self) -> list[dict[str, Any]]:
        return store.rows("dist_receipt")

    def proxy_rows(self) -> list[dict[str, Any]]:
        return store.rows("dist_proxy")

    def valid_receipts(
        self,
        *,
        report_version: str | None = None,
        receiver: str | None = None,
    ) -> list[dict[str, Any]]:
        """有效签收清单：只认「有效」状态的回执，可按版次/接收方过滤。"""
        result = []
        for receipt in self.receipt_rows():
            if receipt.get("签收状态") != "有效":
                continue
            if report_version and str(receipt.get("报告版次", "")) != report_version:
                continue
            if receiver and str(receipt.get("接收方", "")) != receiver:
                continue
            result.append(receipt)
        return result

    def _find_valid_receipt(
        self, report_version: str, receiver: str, channel: str
    ) -> dict[str, Any] | None:
        """同一报告版次、接收方、渠道只允许一份有效签收。"""
        for receipt in self.receipt_rows():
            if (
                receipt.get("签收状态") == "有效"
                and str(receipt.get("报告版次", "")) == report_version
                and str(receipt.get("接收方", "")) == receiver
                and str(receipt.get("分发渠道", "")) == channel
            ):
                return receipt
        return None

    def _active_proxy(self, report_version: str, receiver: str) -> dict[str, Any] | None:
        """当前生效（未撤换、未停用）的代领资格；撤换只影响后续续做。"""
        for proxy in self.proxy_rows():
            if (
                proxy.get("资格状态") == "生效"
                and str(proxy.get("报告版次", "")) == report_version
                and str(proxy.get("接收方", "")) == receiver
            ):
                return proxy
        return None

    # ============ 签收（幂等） ============

    def deliver(self, entry_id: int, use_proxy: bool | None = None) -> dict[str, Any]:
        """执行送达并写入有效签收；已签收的记录幂等返回，绝不重复投递/重复签收。

        use_proxy：续做存在代领资格时由值班员明确选择实际接件人。
        - None：有生效代领资格默认代领，否则本人；
        - True：必须存在生效代领资格，由代领人签收；
        - False：本人地址须仍有效，由本人签收（本人继续办理优先于代领资格）。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        version = _version_of(entry)
        receiver = str(entry.get("接收方", ""))
        channel = str(entry.get("分发渠道", "站内信") or "站内信")

        # 规则 1：同版次+接收方+渠道已有有效签收 → 直接复用，不重复建投递
        existing = self._find_valid_receipt(version, receiver, channel)
        if existing is not None:
            entry["status"] = DELIVERED_STATUS
            entry["送达状态"] = DELIVERED_STATUS
            entry["pending"] = False
            return {
                "ok": True,
                "message": f"{receiver} 的 {version} 已存在有效签收（{existing.get('实际签收人')}），不重复投递",
                "receipt": existing,
                "duplicated": True,
            }

        active_proxy = self._active_proxy(version, receiver)
        self_address_valid = bool(entry.get("本人地址有效", True))

        # 续做中的记录：本人继续办理与代领资格变更发生冲突时，以值班员本次选择为准
        if entry.get("status") == "续做中":
            if use_proxy is True and active_proxy is None:
                return {"ok": False, "message": "无生效代领资格，不能按代领送达"}
            if use_proxy is False and not self_address_valid:
                return {"ok": False, "message": "本人地址已失效，不能由本人签收"}
            if not self_address_valid and active_proxy is None:
                return {"ok": False, "message": "本人地址已失效且无生效代领资格，无法续做送达"}

        # 报告成品校验：未完成则记失败（整组批量场景下不影响其他人）
        report_code = str(entry.get("报告编码", ""))
        report = next(
            (r for r in store.rows("report_gen") if r.get("报告编码") == report_code), None
        )
        if report is None or report.get("status") != "已完成":
            entry["status"] = "送达失败"
            entry["abnormal"] = True
            entry["失败原因"] = "报告未完成或不存在"
            return {"ok": False, "message": f"报告 {report_code} 未完成，分发失败"}

        # 确定实际签收人：值班员明确本人办理时本人优先，否则按生效代领资格代领
        choose_proxy = active_proxy is not None and use_proxy is not False
        proxy = active_proxy if choose_proxy else None
        actual_signer = str(proxy.get("代领人")) if proxy else receiver
        used_proxy_id = proxy.get("资格编号") if proxy else ""

        receipt = {
            "id": _next_id(self.receipt_rows()),
            "回执编号": f"RC-{version}-{receiver}-{channel}",
            "报告版次": version,
            "报告编码": report_code,
            "分发批次": entry.get("分发批次", ""),
            "接收方": receiver,
            "分发渠道": channel,
            "实际签收人": actual_signer,
            "使用代领资格": used_proxy_id,
            "是否代领": bool(proxy),
            "签收状态": "有效",
            "送达时间": _now(),
        }
        self.receipt_rows().append(receipt)

        # 代领资格一经实际使用即留痕：后续撤换不影响这份回执追溯到当时用的资格
        if proxy is not None:
            proxy["资格状态"] = "已使用"
            proxy["使用时间"] = receipt["送达时间"]
            proxy["使用回执"] = receipt["回执编号"]

        entry["status"] = DELIVERED_STATUS
        entry["送达状态"] = DELIVERED_STATUS
        entry["pending"] = False
        entry["abnormal"] = False
        entry["实际签收人"] = actual_signer
        entry["使用代领资格"] = used_proxy_id
        entry["送达时间"] = receipt["送达时间"]
        entry.pop("失败原因", None)

        # 回执写回报告生成器，形成闭环
        report["分发回执"] = f"已送达:{channel}"
        return {
            "ok": True,
            "message": f"{version} 已通过 {channel} 送达，实际签收人：{actual_signer}",
            "receipt": receipt,
            "duplicated": False,
        }

    # 兼容旧命名
    dispatch = deliver

    def switch_channel(self, entry_id: int, channel: str) -> dict[str, Any]:
        """续做期间切换分发渠道；只允许在未送达记录上操作，已签收渠道不可改。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        if entry.get("status") == DELIVERED_STATUS:
            return {"ok": False, "message": "已签收记录不能切换渠道"}
        channel = (channel or "").strip()
        if not channel:
            return {"ok": False, "message": "渠道不能为空"}
        entry["分发渠道"] = channel
        entry["送达状态"] = entry.get("status", "续做中")
        return {"ok": True, "message": f"续做渠道已切换为 {channel}"}

    def reject_received(self, entry_id: int, reason: str) -> dict[str, Any]:
        """渠道明确拒收：记录为「已拒收」并保留拒收原因，等待值班员续做。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        if entry.get("status") == DELIVERED_STATUS:
            return {"ok": False, "message": "已签收记录不能登记拒收"}
        entry["status"] = "已拒收"
        entry["送达状态"] = "已拒收"
        entry["pending"] = True
        entry["abnormal"] = True
        entry["失败原因"] = reason or "渠道明确拒收"
        entry["拒收时间"] = _now()
        return {"ok": True, "message": f"{entry.get('接收方')} 已登记拒收，待续做"}

    # ============ 续做（不新建投递） ============

    def register_continuation(self, entry_id: int, prefer_proxy: bool = False) -> dict[str, Any]:
        """续做申请：把未送达记录推进到「续做中」，复用原记录而不是新建分发。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        if entry.get("status") == DELIVERED_STATUS:
            return {"ok": False, "message": "已签收记录无需续做"}
        if entry.get("status") == "续做中":
            return {"ok": False, "message": "该记录已在续做中，请勿重复申请"}
        entry["status"] = "续做中"
        entry["送达状态"] = "续做中"
        entry["pending"] = True
        entry["续做次数"] = str(int(entry.get("续做次数", "0") or 0) + 1)
        entry["续做申请时间"] = _now()
        # 续做意向：优先代领 / 本人继续办理；实际签收人在送达时按生效资格落定
        entry["续做意向"] = "代领" if prefer_proxy else "本人"
        entry["本人地址有效"] = entry.get("本人地址有效", True)
        return {"ok": True, "message": f"{entry.get('接收方')} 的续做申请已登记（未交渠道）"}

    def continuation_list(
        self, *, report_version: str | None = None, batch_id: str | None = None
    ) -> dict[str, Any]:
        """按当前报告版次列出分发续做清单：只包含确实未送达、需要续做的收件人。"""
        rows = store.rows(self.MODULE)
        items: list[dict[str, Any]] = []
        for row in rows:
            if row.get("status") not in UNDERIVERED_STATUSES:
                continue
            if report_version and _version_of(row) != report_version:
                continue
            if batch_id and str(row.get("分发批次", "")) != batch_id:
                continue
            proxy = self._active_proxy(_version_of(row), str(row.get("接收方", "")))
            items.append({
                "id": row.get("id"),
                "分发批次": row.get("分发批次", ""),
                "报告版次": _version_of(row),
                "报告编码": row.get("报告编码", ""),
                "接收方": row.get("接收方", ""),
                "分发渠道": row.get("分发渠道", ""),
                "当前状态": row.get("status", ""),
                "失败原因": row.get("失败原因", ""),
                "续做次数": row.get("续做次数", "0"),
                "本人地址有效": row.get("本人地址有效", True),
                "生效代领资格": proxy.get("资格编号", "") if proxy else "",
                "可代领人": proxy.get("代领人", "") if proxy else "",
            })
        return {
            "ok": True,
            "报告版次": report_version or "全部版次",
            "待续做人数": len(items),
            "items": items,
        }

    def batch_deliver(self, entry_ids: list[int] | None = None) -> dict[str, Any]:
        """批量送达：逐条幂等签收。整组中途失败时已送达部分独立成回执，未送达可续做。"""
        rows = store.rows(self.MODULE)
        targets = [r for r in rows if entry_ids is None or int(r.get("id", 0)) in entry_ids]
        queued = [r for r in targets if r.get("status") in ("排队中", "续做中")]
        delivered, failed, skipped = 0, 0, 0
        for row in queued:
            result = self.deliver(int(row.get("id", 0)))
            if result.get("ok"):
                delivered += 1
                if result.get("duplicated"):
                    skipped += 1
            else:
                failed += 1
        return {
            "ok": True,
            "message": f"批量分发完成：送达 {delivered}（其中复用已签收 {skipped}），失败 {failed}",
            "delivered": delivered,
            "failed": failed,
            "skipped": skipped,
        }

    # ============ 代领资格 ============

    def register_proxy(
        self,
        report_version: str,
        receiver: str,
        proxy_person: str,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        """登记/撤换代领资格。撤换时旧资格标记「已撤换」，新资格「生效」。

        已被有效回执使用过的资格保留「已使用」快照，撤换不影响历史回执的可追溯性。
        """
        if not report_version or not receiver or not proxy_person:
            return {"ok": False, "message": "报告版次、接收方、代领人均为必填"}
        rows = self.proxy_rows()
        active = self._active_proxy(report_version, receiver)
        if active is not None:
            if not replace and str(active.get("代领人")) == proxy_person:
                return {"ok": True, "message": "该代领资格已生效，无需重复登记", "proxy": active}
            active["资格状态"] = "已撤换"
            active["撤换时间"] = _now()
        proxy = {
            "id": _next_id(rows),
            "资格编号": f"PX-{report_version}-{receiver}-{len(rows) + 1}",
            "报告版次": report_version,
            "接收方": receiver,
            "代领人": proxy_person,
            "资格状态": "生效",
            "登记时间": _now(),
            "撤换时间": "",
            "使用时间": "",
            "使用回执": "",
        }
        rows.append(proxy)
        action = "撤换" if active is not None else "登记"
        return {"ok": True, "message": f"已{action}代领资格：{proxy_person} 可代领 {receiver} 的 {report_version}", "proxy": proxy}

    def list_proxies(self, report_version: str | None = None) -> list[dict[str, Any]]:
        """列出代领资格及其实际使用情况（生效/已撤换/已使用）。"""
        return [
            dict(p)
            for p in self.proxy_rows()
            if not report_version or str(p.get("报告版次", "")) == report_version
        ]

    # ============ 投递详情：可续办与已签收分开 ============

    def delivery_detail(self, entry_id: int) -> dict[str, Any]:
        """打开投递详情：把可续办（未送达）的人和已签收的人分开，并展示代领实际使用。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"{self.ENTITY} {entry_id} 不存在"}
        version = _version_of(entry)
        receiver = str(entry.get("接收方", ""))

        delivered_section = [
            {
                "回执编号": r.get("回执编号", ""),
                "报告版次": r.get("报告版次", ""),
                "接收方": r.get("接收方", ""),
                "分发渠道": r.get("分发渠道", ""),
                "实际签收人": r.get("实际签收人", ""),
                "是否代领": r.get("是否代领", False),
                "使用代领资格": r.get("使用代领资格", ""),
                "送达时间": r.get("送达时间", ""),
            }
            for r in self.valid_receipts(report_version=version, receiver=receiver)
        ]
        proxy = self._active_proxy(version, receiver)
        actionable = entry.get("status") in UNDERIVERED_STATUSES
        return {
            "ok": True,
            "entry": dict(entry),
            "可续办": actionable,
            "未送达区": {
                "当前状态": entry.get("status", ""),
                "失败原因": entry.get("失败原因", ""),
                "本人地址有效": entry.get("本人地址有效", True),
                "续做次数": entry.get("续做次数", "0"),
                "续做意向": entry.get("续做意向", ""),
                "生效代领资格": proxy.get("资格编号", "") if proxy else "",
                "可代领人": proxy.get("代领人", "") if proxy else "",
            } if actionable else None,
            "已签收区": delivered_section,
            "代领资格沿革": [
                {
                    "资格编号": p.get("资格编号", ""),
                    "代领人": p.get("代领人", ""),
                    "资格状态": p.get("资格状态", ""),
                    "登记时间": p.get("登记时间", ""),
                    "撤换时间": p.get("撤换时间", ""),
                    "使用回执": p.get("使用回执", ""),
                }
                for p in self.proxy_rows()
                if str(p.get("报告版次", "")) == version and str(p.get("接收方", "")) == receiver
            ],
        }

    # ============ 兼容旧接口 ============

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """通用动作入口接到新流程：开始分发走幂等签收，重试分发达续做，不绕过规则。"""
        if action == "开始分发":
            out = self.deliver(entry_id)
            if not out.get("ok"):
                return None, str(out.get("message", ""))
            return store.find(self.MODULE, entry_id), str(out.get("message", ""))
        if action == "重试分发":
            out = self.retry_failed(entry_id)
            if not out.get("ok"):
                return None, str(out.get("message", ""))
            return store.find(self.MODULE, entry_id), str(out.get("message", ""))
        return super().run_action(entry_id, action)

    def retry_failed(self, entry_id: int) -> dict[str, Any]:
        """旧入口：重投送达失败批次，内部走续做流程，不新建投递、不自动改渠道。

        渠道切换改由值班员在续做期间通过 switch_channel 显式办理。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") not in ("送达失败", "已拒收", "续做中"):
            return {"ok": False, "message": "仅送达失败/已拒收批次可重试"}
        if entry.get("status") != "续做中":
            registered = self.register_continuation(entry_id)
            if not registered.get("ok"):
                return registered
        return {"ok": True, "message": f"续做已登记（{entry.get('接收方')}），可切换渠道后执行续做送达"}

    def consume_from_report_gen(self, report_code: str) -> dict[str, Any]:
        """读取报告生成器的成品报告信息，校验可分发性。"""
        report = next((r for r in store.rows("report_gen") if r.get("报告编码") == report_code), None)
        if report is None:
            return {"ok": False, "message": f"报告 {report_code} 不存在"}
        return {
            "ok": report.get("status") == "已完成",
            "生成状态": report.get("status", ""),
            "数据窗口": report.get("数据窗口", ""),
            "结论条数": report.get("结论条数", "0"),
        }

    def broadcast_to_reviewers(self, report_code: str, receivers: list[str]) -> dict[str, Any]:
        """整组广播登记；按版次+接收方+渠道去重，断线重发不会重复建立投递。"""
        if not receivers or not report_code:
            return {"ok": False, "message": "缺少报告编码或接收方列表"}
        rows = store.rows(self.MODULE)
        version = str(
            next((r.get("报告版次") for r in rows if r.get("报告编码") == report_code), report_code)
        )
        batch_id = f"RD-BC-{datetime.now(timezone.utc).timestamp():.0f}"
        created, skipped = 0, 0
        for receiver in receivers:
            # 同版次同接收方已有任何渠道的在途/有效投递则不重复建立
            duplicate = any(
                str(r.get("报告编码", "")) == report_code
                and _version_of(r) == version
                and str(r.get("接收方", "")) == receiver
                for r in rows
            )
            if duplicate:
                skipped += 1
                continue
            rows.append({
                "id": _next_id(rows),
                "分发批次": batch_id,
                "报告版次": version,
                "报告编码": report_code,
                "接收方": receiver,
                "分发渠道": "邮件",
                "送达状态": "排队中",
                "status": "排队中",
                "pending": True,
                "abnormal": False,
                "本人地址有效": True,
                "续做次数": "0",
            })
            created += 1
        return {
            "ok": True,
            "message": f"广播批次 {batch_id} 新建 {created} 个投递，跳过重复 {skipped} 个",
            "batch_id": batch_id,
            "created": created,
            "skipped": skipped,
        }

    def list_delivered(self, report_code: str) -> list[dict[str, Any]]:
        """列出报告各版次的有效签收，供结论评审队列按版次引用。"""
        return [
            {
                "报告版次": r.get("报告版次", ""),
                "分发批次": r.get("分发批次", ""),
                "接收方": r.get("接收方", ""),
                "实际签收人": r.get("实际签收人", ""),
                "分发渠道": r.get("分发渠道", ""),
                "使用代领资格": r.get("使用代领资格", ""),
                "送达时间": r.get("送达时间", ""),
            }
            for r in self.receipt_rows()
            if r.get("报告编码") == report_code and r.get("签收状态") == "有效"
        ]

    def sync_receipt_to_archive(self, report_code: str) -> dict[str, Any]:
        """把送达回执同步到实验归档库的结论摘要。"""
        delivered = self.list_delivered(report_code)
        if not delivered:
            return {"ok": False, "message": "报告无有效签收记录"}
        archive_rows = store.rows("exp_archive")
        for row in archive_rows:
            if report_code in str(row.get("归档位置", "")):
                row["结论摘要"] = f"{row.get('结论摘要', '')}；已送达 {len(delivered)} 个接收方"
                row["pending"] = True
        return {"ok": True, "message": f"归档摘要已更新有效签收回执 {len(delivered)} 份"}
