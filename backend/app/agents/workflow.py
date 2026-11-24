"""LangGraph 审查工作流（阶段 2 完整版）。

流程：parse → extract_clauses → risk_identify ∥ compliance_check（并行）
      → suggest → human_review（高风险 interrupt 挂起）→ report → END
Checkpoint 使用 SqliteSaver（开发期），生产切 PostgresSaver，通过 config 注入。
"""
import json
import re
from typing import TypedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.services import events, llm

# 单份合同超过该长度时直接走规则切分（控制 LLM 输入/输出 token）
LLM_EXTRACT_MAX_CHARS = 20000
# 风险识别每批次送审的条款数
RISK_BATCH_SIZE = 8
# 条款送入提示词的单条最大字符数
CLAUSE_PROMPT_CHARS = 600


def _search_rules(query: str, top_k: int = 2) -> list[dict]:
    """经后端内部接口检索规则。

    milvus-lite 单进程独占，Worker 直接打开会与后端冲突，故统一由后端持有向量库连接。
    """
    try:
        qs = urlencode({"q": query[:CLAUSE_PROMPT_CHARS], "top_k": top_k})
        req = Request(
            f"{settings.INTERNAL_API_BASE}/api/internal/rag/search-rules?{qs}",
            headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
        )
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["data"]
    except Exception as exc:
        print(f"[RAG] 规则检索失败，本批降级为无规则注入：{exc}")
        return []


# ---------- State ----------

class ReviewState(TypedDict, total=False):
    task_id: int
    contract_id: int
    file_path: str
    file_type: str
    raw_text: str
    clauses: list[dict]
    risks: list[dict]               # {clause_no, level, risk_type, description, evidence, confidence}
    compliance_issues: list[dict]   # {clause_no, level, risk_type, description, evidence, confidence}
    suggestions: list[dict]         # {item_index, suggest_text, reason, reference} item_index 指向 risks+issues 合并序
    human_feedback: dict | None
    report_path: str
    error: str | None


# ---------- 节点：解析 ----------

def parse(state: ReviewState) -> dict:
    """解析节点：按文件类型提取全文文本。"""
    events.publish(state["task_id"], {"node": "parse", "status": "running", "message": "文本解析中"})

    from app.services import docparse
    text = docparse.extract_text(state["file_path"], state["file_type"])

    events.publish(state["task_id"], {"node": "parse", "status": "done", "message": f"解析完成，共 {len(text)} 字"})
    return {"raw_text": text}


# ---------- 节点：条款提取 ----------

def extract_clauses(state: ReviewState) -> dict:
    """条款提取节点：LLM 切分 + 分类 + 标题生成；失败或超长时回退规则切分。"""
    events.publish(state["task_id"], {"node": "extract_clauses", "status": "running", "message": "条款提取中（LLM）"})

    text = state["raw_text"]
    clauses: list[dict] | None = None
    if len(text) <= LLM_EXTRACT_MAX_CHARS:
        try:
            clauses = _extract_by_llm(text)
        except Exception as exc:
            events.publish(state["task_id"], {
                "node": "extract_clauses", "status": "running",
                "message": f"LLM 提取失败，回退规则切分（{exc}）",
            })
    if not clauses:
        clauses = _split_by_rules(text)

    events.publish(state["task_id"], {
        "node": "extract_clauses", "status": "done",
        "message": f"提取完成，共 {len(clauses)} 个条款", "clause_count": len(clauses),
    })
    return {"clauses": clauses}


def _extract_by_llm(text: str) -> list[dict]:
    """LLM 条款切分：按原有结构切分并输出类型/标题，返回结构化条款列表。"""
    prompt = f"""你是合同条款抽取助手。请把以下合同全文按条款切分，输出 JSON：
{{"clauses":[{{"clause_no":"条款序号（沿用原文编号，如 第一条 / 1.1）","title":"条款标题（原文无标题则根据内容概括，10字以内）","clause_type":"条款类型，从以下选一个：当事人信息、标的、价格与付款、交付、验收、保证与承诺、违约责任、保密、知识产权、不可抗力、期限与终止、争议解决、其他","content":"该条款完整原文"}}]}}

要求：
1. 严格按合同原有条款结构切分，不遗漏任何条款，content 保持原文不改写；
2. 合同标题、甲乙方信息等开头内容若无法归入编号条款，作为 clause_no 为 "0" 的条款，clause_type 取 "当事人信息"；
3. 仅输出 JSON，不要输出任何其他内容。

合同全文：
{text}"""
    data = llm.chat_json([{"role": "user", "content": prompt}], max_tokens=8192)

    raw = data.get("clauses") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise llm.LLMError("LLM 返回的 clauses 为空或格式错误")

    clauses: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not str(item.get("content", "")).strip():
            continue
        clauses.append({
            "clause_no": str(item.get("clause_no") or i + 1)[:30],
            "title": str(item.get("title", ""))[:50],
            "clause_type": str(item.get("clause_type", "其他"))[:30],
            "content": str(item["content"]).strip(),
            "confidence": 0.95,
        })
    if not clauses:
        raise llm.LLMError("LLM 返回的条款内容均为空")
    return clauses


def _split_by_rules(text: str) -> list[dict]:
    """规则切分兜底：按常见条款编号模式（第X条 / 一、 / 1. / 1.1）切分。"""
    pattern = re.compile(r"(?m)^(第[一二三四五六七八九十百千\d]+条|[一二三四五六七八九十]+、|\d+(?:\.\d+)*[.、\s])")
    parts = pattern.split(text)

    clauses: list[dict] = []
    buf: list[str] = []
    for part in parts:
        if part is None:
            continue
        if pattern.match(part.strip()) and buf:
            content = "".join(buf).strip()
            if content:
                clauses.append({"clause_no": str(len(clauses) + 1), "title": "",
                                "clause_type": "", "content": content, "confidence": 0.8})
            buf = [part]
        else:
            buf.append(part)
    if buf:
        content = "".join(buf).strip()
        if content:
            clauses.append({"clause_no": str(len(clauses) + 1), "title": "",
                            "clause_type": "", "content": content, "confidence": 0.8})
    if not clauses and text.strip():
        clauses = [{"clause_no": "1", "title": "", "clause_type": "",
                    "content": text.strip(), "confidence": 0.5}]
    return clauses


# ---------- 节点：风险识别（RAG + LLM） ----------

def risk_identify(state: ReviewState) -> dict:
    """风险识别节点：逐批条款 RAG 检索规则注入提示词，LLM 输出风险清单。"""
    events.publish(state["task_id"], {"node": "risk_identify", "status": "running", "message": "风险识别中"})

    clauses = state.get("clauses", [])
    risks: list[dict] = []
    try:
        for i in range(0, len(clauses), RISK_BATCH_SIZE):
            batch = clauses[i:i + RISK_BATCH_SIZE]
            risks.extend(_identify_risks_batch(batch))
    except Exception as exc:  # LLM 异常降级为空结果，不阻断流程（合规检查仍可产出）
        events.publish(state["task_id"], {
            "node": "risk_identify", "status": "running",
            "message": f"LLM 风险识别失败，跳过（{exc}）",
        })
        risks = []

    high = sum(1 for r in risks if r["level"] == "high")
    events.publish(state["task_id"], {
        "node": "risk_identify", "status": "done",
        "message": f"风险识别完成：{len(risks)} 项（高 {high}）",
        "risk_count": len(risks), "high_count": high,
    })
    return {"risks": risks}


def _identify_risks_batch(batch: list[dict]) -> list[dict]:
    """单批条款风险识别：先 RAG 检索候选规则，再一次 LLM 调用输出风险。"""
    # 聚合本批条款命中的规则（去重）
    rule_map: dict[str, dict] = {}
    for c in batch:
        for hit in _search_rules(c["content"], top_k=2):
            rule_map.setdefault(hit["code"], hit)

    if not rule_map:
        return []  # 规则库为空或无命中时不臆造风险

    clause_text = "\n\n".join(
        f"【条款 {c['clause_no']}】（类型：{c.get('clause_type') or '未知'}）{c['content'][:CLAUSE_PROMPT_CHARS]}"
        for c in batch
    )
    rule_text = "\n".join(f"[{r['code']}] {r['name']}：{r['content']}" for r in rule_map.values())

    prompt = f"""你是资深法务合同审查助手。基于"审查规则库"对下列合同条款逐条做风险识别，找出对合同任一方（重点甲方）不利或不合规的风险点。

【审查规则库】
{rule_text}

【合同条款】
{clause_text}

要求：
1. 仅输出 JSON：{{"risks":[{{"clause_no":"条款序号","level":"high|medium|low","risk_type":"风险类型（如违约责任/付款/知识产权等）","description":"风险描述（引用条款关键表述，说明为何构成风险）","evidence":"依据的规则编号，多个用逗号分隔","confidence":0.0-1.0}}]}}；
2. level 判定：high=可能导致重大经济损失、合同无效或核心权利丧失；medium=权责明显不对等或关键约定缺失；low=表述不规范等轻微问题；
3. 没有风险的条款不要输出；不确定的风险不要臆造；
4. 仅输出 JSON，不要输出其他内容。"""
    data = llm.chat_json([{"role": "user", "content": prompt}], max_tokens=4096)

    raw = data.get("risks") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise llm.LLMError("LLM 返回的 risks 格式错误")

    valid_nos = {c["clause_no"] for c in batch}
    risks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "low"))
        if level not in ("high", "medium", "low"):
            level = "low"
        desc = str(item.get("description", "")).strip()
        if not desc:
            continue
        clause_no = str(item.get("clause_no", ""))
        risks.append({
            "clause_no": clause_no if clause_no in valid_nos else "",
            "level": level,
            "risk_type": str(item.get("risk_type", "其他"))[:30],
            "description": desc,
            "evidence": str(item.get("evidence", ""))[:100],
            "confidence": float(item.get("confidence", 0.8)) if isinstance(item.get("confidence"), (int, float)) else 0.8,
            "source": "llm",
        })
    return risks


# ---------- 节点：合规检查（确定性规则引擎） ----------

# 必备条款关键词（命中任一即视为具备）
REQUIRED_CLAUSES = {
    "价格与付款": ["付款", "价款", "费用", "报酬"],
    "违约责任": ["违约"],
    "争议解决": ["争议", "仲裁", "诉讼"],
    "期限与终止": ["期限", "有效期", "终止", "解除"],
}
# 禁用/高危表述（正则 → 说明）
BANNED_PATTERNS = [
    (re.compile(r"(申请仲裁|提起仲裁|提交.{0,4}仲裁委).{0,30}(或|或者|和|与).{0,10}(起诉|诉讼)|(起诉|诉讼).{0,10}(或|或者|和|与).{0,20}仲裁"),
     "C-002", "high", "『或裁或诉』条款无效，争议解决方式必须诉讼/仲裁二选一且唯一"),
    (re.compile(r"最终解释权"), "C-003", "medium", "『最终解释权归…所有』属格式条款高危表述，存在被认定无效的风险"),
    (re.compile(r"概不负责"), "C-004", "medium", "『概不负责』属免除己方责任的格式条款高危表述"),
    (re.compile(r"违约金.{0,20}日千分|违约金.{0,20}千分之一|按日[123][‰%]"), "C-005", "medium",
     "违约金日利率偏高（≥日千分之一），超过司法保护上限部分可能被调减"),
]


def compliance_check(state: ReviewState) -> dict:
    """合规检查节点：必备条款齐备性 + 禁用表述扫描（确定性规则引擎）。"""
    events.publish(state["task_id"], {"node": "compliance_check", "status": "running", "message": "合规检查中"})

    clauses = state.get("clauses", [])
    full_text = "\n".join(c["content"] for c in clauses)
    issues: list[dict] = []

    # 必备条款齐备性
    for need, keywords in REQUIRED_CLAUSES.items():
        if not any(kw in full_text for kw in keywords):
            issues.append({
                "clause_no": "", "level": "medium",
                "risk_type": "合规检查", "description": f"合同缺少必备的『{need}』条款",
                "evidence": "C-001", "confidence": 0.9, "source": "engine",
            })

    # 禁用/高危表述逐条扫描
    for c in clauses:
        for pattern, code, level, msg in BANNED_PATTERNS:
            if pattern.search(c["content"]):
                issues.append({
                    "clause_no": c["clause_no"], "level": level,
                    "risk_type": "合规检查", "description": f"{msg}（命中条款 {c['clause_no']}）",
                    "evidence": code, "confidence": 0.95, "source": "engine",
                })

    events.publish(state["task_id"], {
        "node": "compliance_check", "status": "done",
        "message": f"合规检查完成：{len(issues)} 项问题", "issue_count": len(issues),
    })
    return {"compliance_issues": issues}


# ---------- 节点：建议生成 ----------

def suggest(state: ReviewState) -> dict:
    """建议生成节点：对高/中风险项生成条款级修改建议（一次 LLM 调用）。"""
    items = state.get("risks", []) + state.get("compliance_issues", [])
    events.publish(state["task_id"], {"node": "suggest", "status": "running", "message": "修改建议生成中"})

    targets = [(i, it) for i, it in enumerate(items) if it.get("level") in ("high", "medium")][:20]
    suggestions: list[dict] = []
    if targets:
        try:
            suggestions = _suggest_batch(state, items, targets)
        except Exception as exc:
            events.publish(state["task_id"], {
                "node": "suggest", "status": "running",
                "message": f"LLM 建议生成失败，跳过（{exc}）",
            })

    events.publish(state["task_id"], {
        "node": "suggest", "status": "done",
        "message": f"建议生成完成：{len(suggestions)} 条", "suggestion_count": len(suggestions),
    })
    return {"suggestions": suggestions}


def _suggest_batch(state: ReviewState, items: list[dict], targets: list[tuple[int, dict]]) -> list[dict]:
    clause_map = {c["clause_no"]: c for c in state.get("clauses", [])}
    lines = []
    for idx, it in targets:
        content = clause_map.get(it.get("clause_no", ""), {}).get("content", "")[:400]
        lines.append(
            f"[风险{idx}] 条款号={it.get('clause_no') or '全文'} 等级={it['level']} 类型={it['risk_type']}\n"
            f"风险描述：{it['description']}\n依据：{it.get('evidence') or '-'}\n条款原文：{content or '（无对应条款）'}"
        )
    prompt = f"""你是资深法务合同修改助手。针对下列合同风险项逐条给出修改建议，输出 JSON：
{{"suggestions":[{{"item_index":风险编号,"suggest_text":"修改后的条款文本（可直接替换原文）","reason":"修改理由（30字内）","reference":"引用的规则/依据编号"}}]}}

要求：修改建议必须具体可落地（给出可直接替换的文本，而非原则性描述）；涉及缺失条款的，给出新增条款文本；仅输出 JSON。

风险项清单：
{chr(10).join(lines)}"""
    data = llm.chat_json([{"role": "user", "content": prompt}], max_tokens=4096)

    raw = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise llm.LLMError("LLM 返回的 suggestions 格式错误")

    valid = {idx for idx, _ in targets}
    suggestions: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("item_index") not in valid:
            continue
        text = str(item.get("suggest_text", "")).strip()
        if not text:
            continue
        suggestions.append({
            "item_index": int(item["item_index"]),
            "suggest_text": text,
            "reason": str(item.get("reason", ""))[:200],
            "reference": str(item.get("reference", ""))[:100],
        })
    return suggestions


# ---------- 节点：人工复核 ----------

def human_review(state: ReviewState) -> dict:
    """人工复核节点：interrupt_before 挂起点，恢复后 human_feedback 已写入 state。"""
    feedback = state.get("human_feedback") or {}
    accepted = sum(1 for a in feedback.get("actions", []) if a.get("action") in ("accept", "edit"))
    events.publish(state["task_id"], {
        "node": "human_review", "status": "done",
        "message": f"人工复核完成：处置 {len(feedback.get('actions', []))} 项（采纳/编辑 {accepted}）",
    })
    return {}


def route_after_suggest(state: ReviewState) -> str:
    """条件路由：存在高风险项 → 挂起人工复核；否则直达报告。"""
    has_high = any(r.get("level") == "high" for r in state.get("risks", [])) \
        or any(i.get("level") == "high" for i in state.get("compliance_issues", []))
    if has_high:
        events.publish(state["task_id"], {
            "node": "human_review", "status": "running", "message": "存在高风险项，等待人工复核",
        })
        return "human_review"
    return "report"


# ---------- 节点：报告生成 ----------

def report(state: ReviewState) -> dict:
    """报告节点：渲染结构化审查报告（概要 + 风险明细 + 建议 + 复核记录）。"""
    events.publish(state["task_id"], {"node": "report", "status": "running", "message": "报告生成中"})

    from app.core.config import settings
    report_dir = settings.STORAGE_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"report_task_{state['task_id']}.txt"

    clauses = state.get("clauses", [])
    risks = state.get("risks", [])
    issues = state.get("compliance_issues", [])
    suggestions = state.get("suggestions", [])
    feedback = state.get("human_feedback")

    LEVEL_CN = {"high": "高", "medium": "中", "low": "低"}
    level_count = {lv: sum(1 for r in risks + issues if r["level"] == lv) for lv in ("high", "medium", "low")}

    lines = [
        "企业智能合同审查报告",
        "=" * 40,
        f"任务 ID：{state['task_id']}",
        f"条款数量：{len(clauses)}",
        f"风险统计：高 {level_count['high']} / 中 {level_count['medium']} / 低 {level_count['low']}",
        f"其中 LLM 风险识别 {len(risks)} 项，合规检查 {len(issues)} 项，修改建议 {len(suggestions)} 条",
        f"人工复核：{'已复核（处置 %d 项）' % len(feedback.get('actions', [])) if feedback else '无需复核（无高风险项）'}",
        "",
        "一、风险明细",
        "-" * 40,
    ]
    all_items = risks + issues
    if not all_items:
        lines.append("未识别出风险项。")
    for i, it in enumerate(all_items):
        lines += [
            f"[{i + 1}] 【{LEVEL_CN.get(it['level'], it['level'])}风险】{it['risk_type']}（条款 {it.get('clause_no') or '全文'}）",
            f"    描述：{it['description']}",
            f"    依据：{it.get('evidence') or '-'}    置信度：{it.get('confidence', '-')}",
        ]
        sug = next((s for s in suggestions if s["item_index"] == i), None)
        if sug:
            lines += [
                f"    修改建议：{sug['suggest_text']}",
                f"    理由：{sug['reason']}    引用：{sug.get('reference') or '-'}",
            ]
        lines.append("")

    lines += ["二、条款清单", "-" * 40]
    for c in clauses:
        head = f"[{c['clause_no']}]"
        if c.get("title"):
            head += f" {c['title']}（{c.get('clause_type') or '未分类'}）"
        lines.append(f"{head} {c['content'][:80].replace(chr(10), ' ')}…")

    path.write_text("\n".join(lines), encoding="utf-8")

    events.publish(state["task_id"], {"node": "report", "status": "done", "message": "报告已生成"})
    return {"report_path": str(path)}


# ---------- 图构建 ----------

def build_graph(checkpointer=None):
    graph = StateGraph(ReviewState)
    graph.add_node("parse", parse)
    graph.add_node("extract_clauses", extract_clauses)
    graph.add_node("risk_identify", risk_identify)
    graph.add_node("compliance_check", compliance_check)
    graph.add_node("suggest", suggest)
    graph.add_node("human_review", human_review)
    graph.add_node("report", report)

    graph.add_edge(START, "parse")
    graph.add_edge("parse", "extract_clauses")
    # 风险识别与合规检查并行扇出，汇合于 suggest
    graph.add_edge("extract_clauses", "risk_identify")
    graph.add_edge("extract_clauses", "compliance_check")
    graph.add_edge("risk_identify", "suggest")
    graph.add_edge("compliance_check", "suggest")
    # 条件边：高风险 → 人工复核挂起；否则直达报告
    graph.add_conditional_edges("suggest", route_after_suggest,
                                {"human_review": "human_review", "report": "report"})
    graph.add_edge("human_review", "report")
    graph.add_edge("report", END)

    return graph.compile(checkpointer=checkpointer, interrupt_before=["human_review"])
