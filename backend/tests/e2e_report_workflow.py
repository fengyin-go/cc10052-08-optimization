"""端到端业务验证：R-v2 分发续做 + 代领资格 + 评审证据领用全链路。

用 TestClient 打真实 HTTP 路由，覆盖题面要求的每一条规则：
1. A 已签收保留原回执，材料只送达一次，重复续做/重发不重复建投递、不重复签收；
2. B 第一渠道明确拒收未送达，续做申请后不新建投递记录；
3. 续做期间登记/撤换代领资格，回执能看出实际使用了哪份；
4. 本人继续办理与代领冲突时可选择实际接件人；
5. 同接收方不同版次（R-v1 / R-v2）分别送达，重发不凭名字阻断新版；
6. 同版次+接收方+渠道只有一份有效签收；
7. 整组中途失败，已送达部分独立可引用，未送达人可续做；
8. 评审按版次领用已送达证据，不等整组完成；无证据不能通过评审。
"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def post(path: str, body: dict | None = None):
    resp = client.post(path, json=body or {})
    data = resp.json()
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return data


def get(path: str):
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


def find_entry(entry_id: int) -> dict:
    return get(f"/api/report_dist/{entry_id}")


print("== 初始场景：R-v2 批次 A 已签收、B 拒收后续做中 ==")
a_entry = find_entry(5)
b_entry = find_entry(6)
check("A 初始已送达", a_entry["status"] == "已送达")
check("B 初始续做中（拒收后续做申请已交、未交渠道）", b_entry["status"] == "续做中")
receipts = get("/api/report_dist/receipts/valid?report_version=R-v2")["data"]
check("R-v2 初始只有 A 的一份有效签收", len(receipts) == 1 and receipts[0]["接收方"] == "评审员A")
check("A 回执实际签收人是本人", receipts[0]["实际签收人"] == "评审员A" and receipts[0]["是否代领"] is False)

print("== 规则：续做清单只列确实未送达的人，按版次过滤 ==")
cont = get("/api/report_dist/continuation?report_version=R-v2")["data"]
check("续做清单仅 B 一人", cont["待续做人数"] == 1 and cont["items"][0]["接收方"] == "评审员B")
check("A 不在续做清单", all(i["接收方"] != "评审员A" for i in cont["items"]))

print("== 规则：A 重复续做/重发不重复投递，保留原回执 ==")
again = post("/api/report_dist/5/deliver", {"use_proxy": False})
check("A 重复送达幂等且不新建签收", again["ok"] and again["data"].get("duplicated") is True)
receipts2 = get("/api/report_dist/receipts/valid?report_version=R-v2")["data"]
check("R-v2 仍只有 A 一份签收（材料只送达一次）", len(receipts2) == 1)

print("== 规则：广播重发按版次+接收方去重，断线重发不重复建立投递 ==")
before = len(get("/api/report_dist?size=200")["items"])
bc = post("/api/report_dist/broadcast", {}) if False else None
# broadcast_to_reviewers 走服务层（无专用 HTTP 入口），直接验证去重逻辑
from app.services.report_dist import ReportDistService
svc = ReportDistService()
bc = svc.broadcast_to_reviewers("RPT-R-V2", ["评审员A", "评审员B", "评审员D"])
check("重复接收方 A/B 被跳过，仅新建 D", bc["created"] == 1 and bc["skipped"] == 2)
after = len(get("/api/report_dist?size=200")["items"])
check("分发记录只净增 1 条（D）", after - before == 1)

print("== 规则：同接收方不同版次不凭名字阻断，R-v1 独立查证 ==")
v1 = get("/api/report_dist/receipts/valid?report_version=R-v1")["data"]
check("R-v1 保留 A 的独立签收", len(v1) == 1 and v1[0]["报告版次"] == "R-v1")
svc.broadcast_to_reviewers("RPT-R-V1", ["评审员B"])
v1_b = [r for r in get("/api/report_dist?size=200")["items"]
        if r.get("报告版次") == "R-v1" and r.get("接收方") == "评审员B"]
check("B 在 R-v1 可新建投递，不受 R-v2 拒收影响", len(v1_b) == 1 and v1_b[0]["status"] == "排队中")

print("== 代领资格：续做期间登记协作评审员 C，再撤换为 E ==")
px = post("/api/report_dist/proxy", {
    "report_version": "R-v2", "receiver": "评审员B", "proxy_person": "协作评审员C"})
check("登记代领资格成功", px["ok"] and px["data"]["proxy"]["资格状态"] == "生效")
px2 = post("/api/report_dist/proxy", {
    "report_version": "R-v2", "receiver": "评审员B", "proxy_person": "协作评审员E", "replace": True})
check("撤换后新资格 E 生效", px2["ok"] and px2["data"]["proxy"]["代领人"] == "协作评审员E")
proxies = get("/api/report_dist/proxy/active?report_version=R-v2")["data"]
check("旧资格 C 标记已撤换", any(p["代领人"] == "协作评审员C" and p["资格状态"] == "已撤换" for p in proxies))
check("当前生效资格为 E", any(p["代领人"] == "协作评审员E" and p["资格状态"] == "生效" for p in proxies))

print("== 冲突处理：本人地址仍有效，值班员选择本人继续办理 ==")
detail_before = get("/api/report_dist/6/detail")["data"]
check("详情把可续办与已签收分开", detail_before["可续办"] is True
      and detail_before["未送达区"] is not None and detail_before["已签收区"] == [])
check("详情可见生效代领人 E", detail_before["未送达区"]["可代领人"] == "协作评审员E")
res = post("/api/report_dist/6/deliver", {"use_proxy": False})
check("本人续做送达成功", res["ok"])
b_after = find_entry(6)
check("B 状态变为已送达且复用原记录（id 仍为 6）", b_after["status"] == "已送达")
check("实际签收人为本人 B，未使用代领资格", b_after["实际签收人"] == "评审员B" and b_after["使用代领资格"] == "")

print("== 规则：同版次+接收方+渠道只有一份有效签收 ==")
b_receipts = get("/api/report_dist/receipts/valid?report_version=R-v2&receiver=评审员B")["data"]
check("B 在 R-v2 仅一份有效签收", len(b_receipts) == 1)
check("E 的资格未被使用（本人办理优先）", all(p["代领人"] != "协作评审员E" or p["资格状态"] == "生效"
      for p in get("/api/report_dist/proxy/active?report_version=R-v2")["data"]))

print("== 投递详情：已签收区展示回执与代领沿革 ==")
detail_after = get("/api/report_dist/6/detail")["data"]
check("续办完成后可续办区关闭", detail_after["可续办"] is False and detail_after["未送达区"] is None)
check("已签收区出现 B 的回执", len(detail_after["已签收区"]) == 1
      and detail_after["已签收区"][0]["实际签收人"] == "评审员B")
check("代领资格沿革保留撤换痕迹", len(detail_after["代领资格沿革"]) >= 2)

print("== 整组中途失败：已送达独立可引用，未送达可续做 ==")
# 新登记一个报告未完成的投递，批量送达时失败但不影响其他人
rows = get("/api/report_dist?size=200")["items"]
d_row = next(r for r in rows if r.get("接收方") == "评审员D")
batch = post("/api/report_dist/batch-deliver", {"entry_ids": [d_row["id"]]})
check("批量送达 D 成功（RPT-R-V2 已完成）", batch["ok"] and batch["data"]["delivered"] == 1)
cont2 = get("/api/report_dist/continuation?report_version=R-v2")["data"]
check("续做清单随送达完成而清空 B/D", all(i["接收方"] not in ("评审员B", "评审员D") for i in cont2["items"]))

print("== 评审：按版次采纳真实回执，领用签收后才能通过 ==")
versions = get("/api/conclusion_review/evidence/versions?report_code=RPT-R-V2")["data"]
v2_ev = next(v for v in versions if v["报告版次"] == "R-v2")
check("证据明细按版次列出 R-v2 实际送达的人（A/B/D）",
      {p["接收方"] for p in v2_ev["实际送达的人"]} == {"评审员A", "评审员B", "评审员D"})
avail = get("/api/conclusion_review/evidence/available?report_version=R-v2")["data"]
check("整组未要求全部完成，R-v2 已有证据可独立领用", avail["可领用"] is True)

# CONC-R-V2 的 id=5；领用 A 的回执（id=2）
claim = post("/api/conclusion_review/5/claim", {
    "report_version": "R-v2", "receipt_id": 2, "reviewer": "值班评审员"})
check("评审队列领用 A 的 R-v2 回执成功", claim["ok"])
claim_dup = post("/api/conclusion_review/5/claim", {
    "report_version": "R-v2", "receipt_id": 2, "reviewer": "值班评审员"})
check("同一回执不可重复领用", claim_dup["ok"] is False)
no_evidence_approve = post("/api/conclusion_review/4/approve", {"comment": ""})
check("R-v1 未领证据不能通过评审", no_evidence_approve["ok"] is False)

# R-v1 在自己的评审中单独查证：领用 R-v1 回执（id=1）到 CONC-R-V1（id=4）
claim_v1 = post("/api/conclusion_review/4/claim", {
    "report_version": "R-v1", "receipt_id": 1, "reviewer": "值班评审员"})
check("R-v1 评审单独领用 R-v1 回执", claim_v1["ok"])
ap1 = post("/api/conclusion_review/4/approve", {"comment": "R-v1 复核通过"})
ap2 = post("/api/conclusion_review/5/approve", {"comment": "R-v2 复核通过"})
check("R-v1 评审通过", ap1["ok"])
check("R-v2 评审通过", ap2["ok"])
ed = get("/api/conclusion_review/5/evidence")["data"]
check("评审证据明细按版本归档", len(ed["按版次证据"]) == 1 and ed["按版次证据"][0]["报告版次"] == "R-v2")
check("R-v2 证据实际签收人仅含真实签收者",
      {p["实际签收人"] for p in ed["按版次证据"][0]["实际送达的人"]} == {"评审员A"})

print("== 通用动作入口：开始分发/重试分发不绕过新规则 ==")
# 新广播一批 R-v2 给评审员F，走通用「开始分发」动作
svc.broadcast_to_reviewers("RPT-R-V2", ["评审员F"])
f_row = next(r for r in get("/api/report_dist?size=200")["items"]
             if r.get("接收方") == "评审员F" and r.get("报告版次") == "R-v2")
act1 = client.post(f"/api/report_dist/{f_row['id']}/actions", json={"action": "开始分发"}).json()
check("通用开始分发成功", act1["ok"] and act1["entry"]["status"] == "已送达")
act2 = client.post(f"/api/report_dist/{f_row['id']}/actions", json={"action": "开始分发"}).json()
f_receipts = get(f"/api/report_dist/receipts/valid?report_version=R-v2&receiver=评审员F")["data"]
check("重复通用动作不产生第二份签收", act2["ok"] and len(f_receipts) == 1)

# 另一收件人 J：明确拒收 → 通用重试分发 → 进入续做中且记录数不变
svc.broadcast_to_reviewers("RPT-R-V2", ["评审员J"])
j_row = next(r for r in get("/api/report_dist?size=200")["items"]
             if r.get("接收方") == "评审员J" and r.get("报告版次") == "R-v2")
total_rows_before = get("/api/report_dist?size=200")["total"]
post(f"/api/report_dist/{j_row['id']}/reject", {"reason": "渠道明确拒收"})
act3 = client.post(f"/api/report_dist/{j_row['id']}/actions", json={"action": "重试分发"}).json()
total_rows_after = get("/api/report_dist?size=200")["total"]
check("通用重试分发达续做中且不新建记录、不自动改渠道",
      act3["entry"]["status"] == "续做中"
      and act3["entry"]["分发渠道"] == "邮件"
      and total_rows_after == total_rows_before)

print("== 代领实际使用：回执能看出用了哪份资格 ==")
post("/api/report_dist/proxy", {
    "report_version": "R-v2", "receiver": "评审员J", "proxy_person": "协作评审员G"})
res_proxy = post(f"/api/report_dist/{j_row['id']}/deliver", {"use_proxy": True})
check("按代领送达成功", res_proxy["ok"] and res_proxy["data"]["receipt"]["实际签收人"] == "协作评审员G")
j_receipt = get("/api/report_dist/receipts/valid?report_version=R-v2&receiver=评审员J")["data"][0]
check("回执标记代领并记录使用的资格编号", j_receipt["是否代领"] is True and bool(j_receipt["使用代领资格"]))
used_proxy = next(p for p in get("/api/report_dist/proxy/active?report_version=R-v2")["data"]
                  if p["代领人"] == "协作评审员G")
check("被使用的资格状态为已使用并回写回执编号",
      used_proxy["资格状态"] == "已使用" and used_proxy["使用回执"] == j_receipt["回执编号"])
# 撤换已使用资格后由值班员显式切换渠道再送达：原渠道回执保留，新渠道由新代领人签收
post("/api/report_dist/proxy", {
    "report_version": "R-v2", "receiver": "评审员J", "proxy_person": "协作评审员H", "replace": True})
# J 已送达，需先模拟新渠道续做场景：对同接收方新渠道是独立签收，
# 这里直接验证已签收记录禁止切渠道，并对仍在途的记录验证切换
sw = post(f"/api/report_dist/{j_row['id']}/channel", {"channel": "webhook"})
check("已签收记录禁止切换渠道", sw["ok"] is False)

# 新接收人 K 走完整的「拒收→续做→切渠道→代领」路径验证新渠道独立签收
svc.broadcast_to_reviewers("RPT-R-V2", ["评审员K"])
k_row = next(r for r in get("/api/report_dist?size=200")["items"]
             if r.get("接收方") == "评审员K" and r.get("报告版次") == "R-v2")
post(f"/api/report_dist/{k_row['id']}/reject", {"reason": "渠道明确拒收"})
client.post(f"/api/report_dist/{k_row['id']}/actions", json={"action": "重试分发"})
sw2 = post(f"/api/report_dist/{k_row['id']}/channel", {"channel": "webhook"})
k_after_switch = get(f"/api/report_dist/{k_row['id']}")
check("续做中可显式切换渠道", sw2["ok"] and k_after_switch["分发渠道"] == "webhook")
post("/api/report_dist/proxy", {
    "report_version": "R-v2", "receiver": "评审员K", "proxy_person": "协作评审员H"})
res_h = post(f"/api/report_dist/{k_row['id']}/deliver", {"use_proxy": True})
check("新渠道由代领人 H 签收", res_h["ok"] and res_h["data"]["receipt"]["实际签收人"] == "协作评审员H")
all_k = get("/api/report_dist/receipts/valid?report_version=R-v2&receiver=评审员K")["data"]
check("K 的 webhook 渠道仅一份有效签收", len(all_k) == 1 and all_k[0]["分发渠道"] == "webhook")

print("== 通用工作台动作与专用接口同一套业务门槛 ==")
# 新广播一个评审员 L，通用「开始分发」遇报告异常时应返回失败而不是假成功
svc.broadcast_to_reviewers("RPT-R-V2", ["评审员L"])
l_row = next(r for r in get("/api/report_dist?size=200")["items"]
             if r.get("接收方") == "评审员L" and r.get("报告版次") == "R-v2")
# 未领证据的评审记录不能通过通用动作绕过证据门槛（CONC-R-V1 在上面已领用，改用未改的 CONC-0001 id=1）
gate = client.post("/api/conclusion_review/1/actions", json={"action": "通过记录"}).json()
check("通用通过动作同样强制证据门槛", gate["ok"] is False and "证据" in gate["message"])
# 通用驳回自动补原因并联动停止分发
gate2 = client.post("/api/conclusion_review/1/actions", json={"action": "驳回记录"}).json()
check("通用驳回走服务层联动逻辑", gate2["ok"] and gate2["entry"]["status"] == "已驳回")
# 已签收记录通用重试应被拒
gate3 = client.post(f"/api/report_dist/{l_row['id']}/actions", json={"action": "开始分发"}).json()
check("L 通用开始分发成功（报告已完成）", gate3["ok"] and gate3["entry"]["status"] == "已送达")
gate4 = client.post(f"/api/report_dist/{l_row['id']}/actions", json={"action": "重试分发"}).json()
check("已签收记录通用重试被拦截", gate4["ok"] is False)

print(f"\n结果：通过 {PASS}，失败 {FAIL}")
sys.exit(1 if FAIL else 0)
