"""报告分发与结论评审专用路由。

通用资源路由继续提供列表/登记/动作能力；本路由承载续做清单、投递详情、
代领资格、证据领用等带业务判断的接口，状态流转仍全部落在领域服务内。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.conclusion_review import ConclusionReviewService
from app.services.report_dist import ReportDistService

router = APIRouter(prefix="/api", tags=["报告分发与评审"])

dist_service = ReportDistService()
review_service = ConclusionReviewService()


class Result(BaseModel):
    ok: bool
    message: str = ""
    data: dict[str, Any] | list[Any] | None = None


class ContinuationPayload(BaseModel):
    prefer_proxy: bool = False


class RejectPayload(BaseModel):
    reason: str = ""


class ChannelPayload(BaseModel):
    channel: str


class DeliverPayload(BaseModel):
    # None 表示按生效资格自动判定；True 强制代领；False 强制本人办理
    use_proxy: bool | None = None
    entry_ids: list[int] | None = None


class ProxyPayload(BaseModel):
    report_version: str
    receiver: str
    proxy_person: str
    replace: bool = False


class ClaimPayload(BaseModel):
    report_version: str
    receipt_id: int
    reviewer: str = ""


class CommentPayload(BaseModel):
    comment: str = ""


# ---------------- 报告分发：续做清单与批量续做 ----------------

@router.get("/report_dist/continuation", response_model=Result)
def continuation_list(report_version: str | None = None, batch_id: str | None = None) -> Result:
    """按当前报告版次列出分发续做清单，只含确实未送达的收件人。"""
    data = dist_service.continuation_list(report_version=report_version, batch_id=batch_id)
    return Result(ok=True, data=data)


@router.post("/report_dist/{entry_id}/continuation", response_model=Result)
def register_continuation(entry_id: int, payload: ContinuationPayload) -> Result:
    """从分发列表打开被拒收/失败的请求并办理续做（不新建投递）。"""
    out = dist_service.register_continuation(entry_id, prefer_proxy=payload.prefer_proxy)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.post("/report_dist/{entry_id}/reject", response_model=Result)
def reject_received(entry_id: int, payload: RejectPayload) -> Result:
    """登记渠道明确拒收。"""
    out = dist_service.reject_received(entry_id, payload.reason)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.post("/report_dist/{entry_id}/channel", response_model=Result)
def switch_channel(entry_id: int, payload: ChannelPayload) -> Result:
    """续做期间由值班员显式切换分发渠道。"""
    out = dist_service.switch_channel(entry_id, payload.channel)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.post("/report_dist/{entry_id}/deliver", response_model=Result)
def deliver_one(entry_id: int, payload: DeliverPayload) -> Result:
    """续做送达：值班员选择本人继续办理或代领，写入唯一有效签收。"""
    out = dist_service.deliver(entry_id, use_proxy=payload.use_proxy)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.post("/report_dist/batch-deliver", response_model=Result)
def batch_deliver(payload: DeliverPayload) -> Result:
    """批量送达选中收件人；已送达部分独立成回执，失败的留在续做清单。"""
    out = dist_service.batch_deliver(payload.entry_ids)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.get("/report_dist/{entry_id}/detail", response_model=Result)
def delivery_detail(entry_id: int) -> Result:
    """投递详情：可续办的人与已签收的人分开，代领资格沿革可追溯。"""
    out = dist_service.delivery_detail(entry_id)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


# ---------------- 报告分发：代领资格 ----------------

@router.get("/report_dist/proxy/active", response_model=Result)
def list_proxies(report_version: str | None = None) -> Result:
    return Result(ok=True, data=dist_service.list_proxies(report_version))


@router.post("/report_dist/proxy", response_model=Result)
def register_proxy(payload: ProxyPayload) -> Result:
    """登记/撤换续做期间的代领资格，实际使用了哪份在回执上留痕。"""
    out = dist_service.register_proxy(
        payload.report_version,
        payload.receiver,
        payload.proxy_person,
        replace=payload.replace,
    )
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.get("/report_dist/receipts/valid", response_model=Result)
def valid_receipts(report_version: str | None = None, receiver: str | None = None) -> Result:
    """有效签收查询：同版次+接收方+渠道只有一份。"""
    return Result(ok=True, data=dist_service.valid_receipts(report_version=report_version, receiver=receiver))


# ---------------- 结论评审：证据领用与按版次采纳 ----------------

@router.get("/conclusion_review/evidence/versions", response_model=Result)
def evidence_versions(report_code: str | None = None) -> Result:
    """评审证据明细按报告版本列出实际送达的人。"""
    return Result(ok=True, data=review_service.evidence_versions(report_code))


@router.get("/conclusion_review/evidence/available", response_model=Result)
def available_evidence(report_version: str) -> Result:
    """某版次当前可领用的已送达证据，无需等整组全部完成。"""
    out = review_service.available_evidence(report_version)
    return Result(ok=True, data=out)


@router.post("/conclusion_review/{entry_id}/claim", response_model=Result)
def claim_evidence(entry_id: int, payload: ClaimPayload) -> Result:
    """评审队列领用签收：只认实际签收人的有效回执。"""
    out = review_service.claim_evidence(
        entry_id, payload.report_version, payload.receipt_id, payload.reviewer
    )
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.get("/conclusion_review/{entry_id}/evidence", response_model=Result)
def evidence_detail(entry_id: int) -> Result:
    out = review_service.evidence_detail(entry_id)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)


@router.post("/conclusion_review/{entry_id}/approve", response_model=Result)
def approve(entry_id: int, payload: CommentPayload) -> Result:
    """实际复核通过：按投递批次采纳当前报告版次真实回执后归档。"""
    out = review_service.approve(entry_id, payload.comment)
    return Result(ok=bool(out.get("ok")), message=str(out.get("message", "")), data=out)
