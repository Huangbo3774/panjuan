"""批改引擎（PRD §5.3）：三种判分方式分层兜底。

  1) 标准答案比对（本模块，纯规则，离线）：选择/判断精确匹配，填空归一化匹配
  2) 人工确认：问答题、以及"没录标准答案/题目本身待校对"的题 → verdict=pending
  3) （预留）可选大模型辅助：PRD 列为可选，本版本【不接入】——项目对外承诺
     "本地运行、不上传"，把孩子的作答发出去必须有显式开关，而 V1.1 没有这个开关，
     所以宁可不做。

为什么不"猜"：把没把握的题判成"错"，家长会以为孩子不会，进而错怪孩子；
判成"待确认"最多少给一分，不会造成误判。这是本模块所有分支的取向。
"""
from __future__ import annotations

import re
from typing import Any

from .normalizer import alternatives, judge_symbol, norm_answer, numbers_equal, variants

VERDICTS = ("correct", "wrong", "pending")

# 题目自带的序号可能重复（不同大题各自从 1 编号），所以用"大题+题号"做稳定键。
# ⚠️ 不能只用 q_no：真实扫描卷 8 个大题就有 8 个"1"，答案会串题（实测切分阶段就踩过）。
UID_SEP = "|"


def make_uid(q: dict[str, Any], index: int | None = None) -> str:
    """题目在一张卷内的稳定键。

    入库后一律用数据库给的 q["uid"]（"q<rowid>"）：家长校对时改了大题或题号，
    用「大题+题号」拼的键会变，标准答案和已录入的作答会当场失联。
    没入库时（单测、纯内存跑）才退回 section+题号。
    """
    if q.get("uid"):
        return str(q["uid"])
    sec = (q.get("section") or "").strip() or "S"
    no = q.get("q_no") if q.get("q_no") is not None else q.get("auto_no")
    if no is None:
        no = f"i{index if index is not None else 0}"
    return f"{UID_SEP}{sec}{UID_SEP}{no}"


# 选项正文要把行首的标记（A. / A、/ A） / ①）摘掉再比。
# ⚠️ 不能指望 norm_answer 顺手去掉：strip(EDGE_PUNCT) 遇到开头的字母 A 就停了，
#    "A. 四七二十八" 归一化后仍是 "a. 四七二十八"，学生会抄正文的场景直接判错（实测）。
OPTION_LEAD_RE = re.compile(r"^\s*(?:[A-H]|[①-⑳])\s*[.、．)）]?\s*", re.I)
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _option_letter(text: str) -> str | None:
    """选项行首的字母标号（A./B、/C））。"""
    m = re.match(r"^\s*([A-H])\s*[.、．)）]?\s*", str(text or ""), re.I)
    return m.group(1).upper() if m else None


def _option_body(text: str) -> str:
    return OPTION_LEAD_RE.sub("", str(text or ""), count=1).strip()


def _marker(text: str) -> tuple[str, str] | None:
    """把 "B" / "B、" / "②" 解析成标记；解析不出（写的是正文）返回 None。

    中文卷的选项标号两种都有：A/B/C/D 和 ①②③④。只认字母的话，
    标准答案 "②" 与学生作答 "南" 就比不上了（真实样本里 ①东 ②南 ③西 ④北 就是这么出的）。
    """
    s = str(text or "").strip()
    if not s:
        return None
    m = re.match(r"^([A-H])\s*(?:[.、．)）]\s*\S)?$", s, re.I)
    if m:
        return ("L", m.group(1).upper())
    # 「A. 四七二十八」这种【字母 + 整条选项正文】也必须解析出字母标号：
    # 做题页的单选框 value 存的就是整条选项文本，解析不出字母的话，
    # 标准答案 "A" 会去和 "a. 四七二十八" 比正文，把对的判成错的（浏览器实测命中）。
    m = re.match(r"^([A-H])\s*[.、．)）]\s*(.+)$", s, re.I)
    if m:
        return ("L", m.group(1).upper())
    if len(s) == 1 and s in CIRCLED:
        return ("N", str(CIRCLED.index(s) + 1))
    m = re.match(r"^([①-⑳])\s*(?:[.、．)）])?\s*(.+)$", s)
    if m and len(m.group(2).strip()) <= 2:          # "②南" 这类：标记 + 短正文
        return ("N", str(CIRCLED.index(m.group(1)) + 1))
    return None


def _body_of_marker(mark: tuple[str, str], options: list[str]) -> str | None:
    kind, val = mark
    if kind == "L":
        for opt in options or []:
            if _option_letter(opt) == val:
                return _option_body(opt)
        return None
    idx = int(val) - 1
    if 0 <= idx < len(options or []):
        return _option_body(options[idx])
    return None


def _eq(a: str, b: str) -> str | None:
    """两个答案串在归一化/数值两个口径下是否等价；等价返回命中的形式，否则 None。"""
    va, vb = variants(a), variants(b)
    return next((x for x in vb if x in va), None)


def _match_choice(expected: str, given: str, options: list[str]) -> tuple[bool, str]:
    """选择题：先比标记（字母/圆圈），比不上再落到【选项正文】。

    四种组合都覆盖：标准=标记·作答=标记 / 标记·正文 / 正文·标记 / 正文·正文。
    """
    e, g = str(expected or "").strip(), str(given or "").strip()
    me, mg = _marker(e), _marker(g)
    if me and mg:
        return (me == mg, f"标记 {me} vs {mg}")
    if me and not mg:
        body = _body_of_marker(me, options)
        if body is None:
            return (False, f"标准答案 {e!r} 在本卷选项里找不到对应正文")
        hit = _eq(body, g)
        return (bool(hit), f"正文比对 {g!r} vs {body!r}" + ("" if hit else "（未命中）"))
    if mg and not me:
        body = _body_of_marker(mg, options)
        if body is not None:
            hit = _eq(e, body)
            return (bool(hit), f"作答 {g!r} 对应选项正文 {body!r}" + ("" if hit else "（未命中）"))
    hit = _eq(e, g)
    return (bool(hit), "归一化相等" if hit else f"{variants(e)} ≠ {variants(g)}")


def _match_judge(expected: str, given: str) -> tuple[bool, str]:
    se, sg = judge_symbol(expected), judge_symbol(given)
    if se is None or sg is None:
        return (False, f"判断题写法无法识别（标准={expected!r} 作答={given!r}）→ 交人工")
    return (se == sg, f"{se} vs {sg}")


def _match_fill(expected: str, given: str) -> tuple[bool | None, str]:
    """填空：多个可接受写法任一命中即对；比不上再比数值。

    返回 None 只用在一种情况：这一空【没有标准答案】（空串），那是"判不了"。
    有标准答案而写法不匹配，就是明确的 wrong——"宁可少判对"不等于"不敢判错"：
    标准答案是家长自己录的，比对不上就是错，把错的都说成"待确认"会让整张卷子
    几十道题全是黄标，人工复核成本反而压垮家长（实测第一版就是这么坏的）。
    """
    alts = alternatives(expected)
    if not alts:
        return (None, "该空没有标准答案")
    gv = variants(given)
    if not gv:
        return (False, "未作答")
    for alt in alts:
        if _eq(alt, given):
            return (True, f"命中可接受答案 {alt!r}")
    for alt in alts:
        if any(numbers_equal(a, b) for a in gv for b in variants(alt)):
            return (True, f"数值等价 {given!r} ≡ {alt!r}")
    se, sg = judge_symbol(alts[0]), judge_symbol(given)
    if se and sg:
        return _match_judge(alts[0], given)
    return (False, f"与标准答案 {alts} 不符（若是同义写法，可加入可接受答案或人工改判）")


def _keyword_hint(reference: str, given: str) -> float:
    """问答题的关键词命中率，只作提示、不计分（PRD 明确要求不计分）。"""
    ref = re.sub(r"[\s\W]+", "", norm_answer(reference)[0])
    got = re.sub(r"[\s\W]+", "", norm_answer(given)[0])
    if not ref:
        return 0.0
    return round(sum(1 for ch in set(ref) if ch in got) / len(set(ref)), 3)


def grade(questions: list[dict[str, Any]],
          key: dict[str, Any] | None = None,
          answers: dict[str, Any] | None = None,
          scores: dict[str, float] | None = None,
          manual: dict[str, str] | None = None) -> dict[str, Any]:
    """执行批改。

    入参（键都用 make_uid 生成）：
      questions  extractor 出来的题目列表
      key        标准答案 {uid: "答案" 或 ["第1空", "第2空"]}
      answers    学生作答 {uid: "答案" 或 [...]}
      scores     分值覆盖 {uid: 分数}，默认取题目自带 score（1.0）
      manual     人工改判 {uid: "correct"/"wrong"}，优先级最高
    """
    key = key or {}
    answers = answers or {}
    scores = scores or {}
    manual = manual or {}
    results: list[dict[str, Any]] = []
    score = max_score = pending_max = 0.0
    counts = {"correct": 0, "wrong": 0, "pending": 0}

    for i, q in enumerate(questions):
        uid = make_uid(q, i)
        maxs = float(scores.get(uid, q.get("score", 1.0)) or 1.0)
        max_score += maxs
        exp_raw = key.get(uid)
        exp_list = exp_raw if isinstance(exp_raw, (list, tuple)) else ([exp_raw] if exp_raw not in (None, "") else [])
        giv_raw = answers.get(uid)
        giv_list = giv_raw if isinstance(giv_raw, (list, tuple)) else ([giv_raw] if giv_raw not in (None, "") else [])
        given = "\n".join(str(x) for x in giv_list if str(x).strip())
        qtype = (q.get("qtype") or "unknown").lower()
        reason, verdict = "", "pending"
        detail: list[str] = []

        if uid in manual:
            verdict = manual[uid] if manual[uid] in ("correct", "wrong") else "pending"
            reason = f"人工改判：{manual[uid]}"
        elif not exp_list:
            verdict, reason = "pending", "未录入标准答案"
        elif not giv_list or not given.strip():
            verdict, reason = "wrong", "未作答"
        elif qtype in ("choice",):
            ok, why = _match_choice(str(exp_list[0]), given, q.get("options") or [])
            verdict, reason = ("correct" if ok else "wrong"), why
        elif qtype in ("judge", "true_false"):
            ok, why = _match_judge(str(exp_list[0]), given)
            verdict = "correct" if ok else ("wrong" if judge_symbol(str(exp_list[0])) and judge_symbol(given) else "pending")
            reason = why
        elif qtype in ("fill",):
            # 多空：按空位逐个比，全对才算对（二年级卷常见"每空1分"，
            # 但每题分值是整题的，这里不做半对给半分——宁可让人复核）。
            n_blanks = max(int(q.get("blanks") or 0), 1)
            exp_slots = exp_list if len(exp_list) > 1 else [str(exp_list[0])]
            giv_slots = giv_list if len(giv_list) > 1 else re.split(r"[；;，,\n]", given) or [given]
            pairs = max(len(exp_slots), len(giv_slots), n_blanks)
            all_ok, any_unknown = True, False
            for k in range(pairs):
                e = str(exp_slots[k]) if k < len(exp_slots) else ""
                g = str(giv_slots[k]).strip() if k < len(giv_slots) else ""
                ok, why = _match_fill(e, g)
                detail.append(f"第{k+1}空：{why}")
                if ok is None:
                    any_unknown = True
                    all_ok = False          # ⚠️ "判不了"必须同时压掉 all_ok，
                elif not ok:                #   否则一题里只要有一空没标准答案，
                    all_ok = False          #   整题会被算成 correct（第一版实测命中）
            if all_ok:
                verdict = "correct"
            elif any_unknown:
                verdict = "pending"
            else:
                verdict = "wrong"
            reason = "；".join(detail) if detail else _match_fill(str(exp_slots[0]), given)[1]
        else:
            # essay / unknown：PRD 规定不自动判分，只给关键词命中提示
            verdict = "pending"
            hint = _keyword_hint(str(exp_list[0]), given)
            reason = f"问答题需人工确认（与参考答案关键词重合 {int(hint*100)}%）"
            detail.append(f"keyword_hit={hint}")

        if verdict == "correct":
            score += maxs
        elif verdict == "pending":
            pending_max += maxs
        counts[verdict] += 1
        results.append({
            "uid": uid, "q_no": q.get("q_no"), "auto_no": q.get("auto_no"),
            "section": q.get("section", ""), "qtype": qtype,
            "stem": (q.get("text") or "")[:120],
            "expected": exp_list, "given": given,
            "verdict": verdict, "reason": reason, "detail": detail,
            "score": maxs if verdict == "correct" else 0.0, "max_score": maxs,
        })

    return {
        "results": results,
        "score": round(score, 2),
        "total": round(max_score, 2),
        "pending_max": round(pending_max, 2),
        "counts": counts,
        "graded": counts["correct"] + counts["wrong"],
        "pending": counts["pending"],
        "wrong_uids": [r["uid"] for r in results if r["verdict"] == "wrong"],
    }
