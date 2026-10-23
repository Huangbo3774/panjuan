"""批改引擎单测：PRD F14（填空容错）+ 分层兜底的取向。

这一组用例的重点不是"判得对"，而是【判不准时不许装作判过】：
没标准答案 → pending；问答题 → pending；写法认不出来 → pending。
把没把握的题判成"错"，家长会错怪孩子，这是本产品最不能接受的错误。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.grading.engine import VERDICTS, grade, make_uid            # noqa: E402
from app.grading.normalizer import (norm_answer, judge_symbol,      # noqa: E402
                                    numbers_equal, variants)

ok_n = bad_n = 0


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}")


def paper(*specs):
    """specs: (section, q_no, qtype, text, options, blanks)"""
    qs = []
    for sec, no, qt, text, opts, blanks in specs:
        qs.append({"section": sec, "q_no": no, "auto_no": no, "qtype": qt,
                   "text": text, "options": opts, "blanks": blanks, "score": 1.0})
    return qs


def run(qs, key_map, ans_map, **kw):
    k = {make_uid(q, i): key_map[i] for i, q in enumerate(qs) if i in key_map}
    a = {make_uid(q, i): ans_map[i] for i, q in enumerate(qs) if i in ans_map}
    return grade(qs, k, a, **kw)


print("\n[归一化原子能力]")


def norm_atoms():
    assert norm_answer("１／２")[0] == "0.5", norm_answer("１／２")
    assert norm_answer("0.50")[0] == "0.5"
    assert norm_answer("Ａ。")[0] == "a", norm_answer("Ａ。")
    assert norm_answer("6  行")[0] == "6 行"
    assert set(variants("6  行")) & set(variants("6行")), (variants("6  行"), variants("6行"))
    assert norm_answer("3×4")[0] == norm_answer("3x4")[0] == norm_answer("3＊4")[0]
    assert numbers_equal("二十五", "25") and numbers_equal("1/2", "0.5")
    assert numbers_equal("二分之一", "1/2"), "孩子写中文分数就该判对（PRD F14 的容错范围）"
    assert not numbers_equal("二分之一", "2"), "「A分之B」= B/A，分母在前写反就成了 2"
    assert numbers_equal("百分之五十", "0.5")
    assert numbers_equal("50%", "0.5")
    assert not numbers_equal("0.5", "5"), "整串数值比较被做成了子串比较"
    assert not numbers_equal("12", "24")
t("全半角/大小写/标点/乘号/中文数字/分数", norm_atoms)


def judge_atoms():
    for w in ("对", "√", "✓", "T", "true", "正确", "是"):
        assert judge_symbol(w) == "T", w
    for w in ("错", "×", "F", "false", "错误", "否"):
        assert judge_symbol(w) == "F", w
    assert judge_symbol("大概对吧") is None, "认不出写法时必须返回 None（交人工），不能硬猜"
t("判断题写法归一", judge_atoms)


print("\n[F14 填空容错]")


def fill_tolerant():
    qs = paper(("二、填空", 1, "fill", "一半是（ ）", [], 1),
               ("二、填空", 2, "fill", "24 的中文写法", [], 1),
               ("二、填空", 3, "fill", "每行8棵6行共（ ）棵", [], 1))
    r = run(qs, {0: "1/2", 1: "二十四", 2: "48"},
            {0: "０．５", 1: "24", 2: "４８个"})
    v = [(x["verdict"], x["reason"]) for x in r["results"]]
    assert [x[0] for x in v] == ["correct", "correct", "correct"], v
    wrong = run(qs, {2: "48"}, {2: "480"})["results"][2]
    assert wrong["verdict"] != "correct", f"48 与 480 判成相等：{wrong['reason']}"
t("1/2≡0.5、全半角、中文数字、带单位答案", fill_tolerant)


def unit_extraction_is_conservative():
    """反例：只在「数字 + 1~3 个非数字字符」时提取数值，"3行8棵"不许退化成 3。"""
    assert "3" not in variants("3行8棵"), variants("3行8棵")
    assert "48" in variants("48个"), variants("48个")
    assert variants("48")[0] == "48"
t("带单位提取不过度（反例）", unit_extraction_is_conservative)


def fill_multiple_alternatives():
    """有标准答案而写法不匹配 = 明确判错（不是"待确认"）。
    口径理由：第一版把"比不上"统统标 pending，结果整卷 20 道题全黄标，
    家长复核成本比手工判卷还高——"宁可少判对"不等于"不敢判错"。
    同义写法由家长用 | 加进可接受答案，或事后人工改判。"""
    qs = paper(("二、填空", 1, "fill", "太阳从（ ）升起", [], 1))
    uid = make_uid(qs[0], 0)
    hit = grade(qs, {uid: "东|东方"}, {uid: "东方"})
    assert hit["results"][0]["verdict"] == "correct", hit["results"][0]["reason"]
    miss = grade(qs, {uid: "东|东方"}, {uid: "东边"})
    assert miss["results"][0]["verdict"] == "wrong", miss["results"][0]["reason"]
    assert "人工改判" in miss["results"][0]["reason"] or "可接受答案" in miss["results"][0]["reason"]
    fixed = grade(qs, {uid: "东|东方"}, {uid: "东边"}, manual={uid: "correct"})
    assert fixed["results"][0]["verdict"] == "correct" and fixed["score"] == 1.0
t("多空可接受答案：命中即对、不匹配即错、可改判", fill_multiple_alternatives)


def blank_without_key_is_pending():
    """反例：一题里只要有一空没标准答案，整题必须是 pending，不能被算成 correct。"""
    qs = paper(("二、填空", 1, "fill", "（ ）和（ ）", [], 2))
    uid = make_uid(qs[0], 0)
    r = grade(qs, {uid: ["东", ""]}, {uid: ["东", "西"]})
    assert r["results"][0]["verdict"] == "pending", r["results"][0]["reason"]
    assert r["score"] == 0 and r["pending_max"] == 1
t("部分空缺标准答案 → 整题待确认（反例）", blank_without_key_is_pending)


def fill_multi_blank():
    qs = paper(("二、填空", 1, "fill", "前面是（ ），后面是（ ）", [], 2))
    ok = run(qs, {0: ["东", "西"]}, {0: ["东", "西"]})
    assert ok["results"][0]["verdict"] == "correct", ok["results"][0]["reason"]
    bad = run(qs, {0: ["东", "西"]}, {0: ["东", "南"]})
    assert bad["results"][0]["verdict"] == "wrong", bad["results"][0]["reason"]
    half = run(qs, {0: ["东", "西"]}, {0: ["东"]})
    assert half["results"][0]["verdict"] == "wrong", f"漏答一个空应判错：{half['results'][0]['reason']}"
    assert "未作答" in half["results"][0]["reason"]
t("多空按空位逐个比", fill_multi_blank)


print("\n[选择/判断]")


def choice_both_forms():
    opts = ["A. 四七二十八", "B. 4乘7", "C. 7乘4", "D. 四四十六"]
    qs = paper(("一、选择题", 1, "choice", "4×7 读作", opts, 0),
               ("一、选择题", 2, "choice", "方向", ["①东", "②南", "③西", "④北"], 0))
    r = run(qs, {0: "A", 1: "②"}, {0: "四七二十八", 1: "南"})
    assert [x["verdict"] for x in r["results"]] == ["correct", "correct"], \
        [(x["verdict"], x["reason"]) for x in r["results"]]
    w = run(qs, {0: "A", 1: "②"}, {0: "B", 1: "③"})
    assert [x["verdict"] for x in w["results"]] == ["wrong", "wrong"]
t("选择题字母与正文互认（含圆圈选项）", choice_both_forms)


def judge_grading():
    qs = paper(("三、判断", 1, "judge", "6×3 读作6乘3", [], 0))
    assert run(qs, {0: "√"}, {0: "对"})["results"][0]["verdict"] == "correct"
    assert run(qs, {0: "√"}, {0: "×"})["results"][0]["verdict"] == "wrong"
    weird = run(qs, {0: "√"}, {0: "我觉得差不多"})["results"][0]
    assert weird["verdict"] == "pending", f"判断题认不出的写法应交人工：{weird['reason']}"
t("判断题精确匹配 + 认不出交人工", judge_grading)


print("\n[分层兜底：不许装作判过]")


def no_key_is_pending():
    """反例：没录标准答案绝不能算"错"。"""
    qs = paper(("一、填空", 1, "fill", "（ ）", [], 1))
    r = run(qs, {}, {0: "东"})
    assert r["results"][0]["verdict"] == "pending", r["results"][0]
    assert r["score"] == 0 and r["pending_max"] == 1 and r["total"] == 1
t("无标准答案 → 待确认（反例）", no_key_is_pending)


def blank_answer_is_wrong():
    qs = paper(("一、填空", 1, "fill", "（ ）", [], 1))
    r = run(qs, {0: "东"}, {})
    assert r["results"][0]["verdict"] == "wrong"
    assert "未作答" in r["results"][0]["reason"]
t("未作答 → 错", blank_answer_is_wrong)


def essay_never_auto_scored():
    """PRD：问答题不自动判分，只给关键词提示且不计分。"""
    qs = paper(("四、解答", 1, "essay", "说说你是怎么想的", [], 0))
    r = run(qs, {0: "先算乘法再算加法"}, {0: "我用了乘法"})
    res = r["results"][0]
    assert res["verdict"] == "pending", res
    assert "keyword_hit" in " ".join(res["detail"]), res["detail"]
    assert r["score"] == 0 and r["pending_max"] == 1
t("问答题不计分，只给命中提示", essay_never_auto_scored)


def essay_exact_match_is_correct():
    """兜底成问答的题：作答与标准答案完全一致时必须判对。

    独立复测 report_A P1-03：15 道题因选项是图片退成问答，标准答案 "A"、
    作答也是 "A"，旧口径整卷只自动判 5 题。完全一致没有歧义，不该挂待确认。
    """
    qs = paper(("一、选择", 1, "essay", "她看到的情景是图（ ）", [], 0),
               ("四、解答", 2, "essay", "还剩多少米？", [], 0))
    k = {make_uid(qs[0], 0): "A", make_uid(qs[1], 1): "7/10"}
    a = {make_uid(qs[0], 0): "A", make_uid(qs[1], 1): "0.7"}
    r = grade(qs, k, a)
    assert [x["verdict"] for x in r["results"]] == ["correct", "correct"], r["results"]
    assert r["score"] == 2.0 and r["pending"] == 0, r
    # 反例：措辞不同（不是完全一致）仍是待确认，不许拿关键词硬判
    r2 = grade(qs, k, {make_uid(qs[0], 0): "图A"})
    assert r2["results"][0]["verdict"] == "pending", r2["results"][0]
t("兜底问答题：答案完全一致判对，措辞不同仍待确认（含反例）", essay_exact_match_is_correct)


def manual_override_wins():
    qs = paper(("三、判断", 1, "judge", "6×3", [], 0),
               ("四、解答", 1, "essay", "写一写", [], 0))
    k = {make_uid(qs[0], 0): "√", make_uid(qs[1], 1): "答案"}
    a = {make_uid(qs[0], 0): "×", make_uid(qs[1], 1): "我写了过程"}
    r = grade(qs, k, a, manual={make_uid(qs[0], 0): "correct"})
    assert r["results"][0]["verdict"] == "correct", r["results"][0]
    assert r["results"][1]["verdict"] == "pending", r["results"][1]
    assert r["score"] == 1.0
t("人工改判优先级最高", manual_override_wins)


def uid_keeps_sections_apart():
    """反例：每大题都从 1 重新编号，键必须带大题，否则答案串题。"""
    qs = paper(("一、填空", 1, "fill", "甲（ ）", [], 1),
               ("二、填空", 1, "fill", "乙（ ）", [], 1))
    r = run(qs, {0: "东", 1: "西"}, {0: "东", 1: "东"})
    assert [x["verdict"] for x in r["results"]] == ["correct", "wrong"], \
        [(x["section"], x["verdict"]) for x in r["results"]]
    assert r["score"] == 1.0
t("不同大题同号不串答案（反例）", uid_keeps_sections_apart)


def score_arithmetic_invariant():
    qs = paper(("一、填空", 1, "fill", "甲", [], 1),
               ("一、填空", 2, "fill", "乙", [], 1),
               ("一、填空", 3, "fill", "丙", [], 1),
               ("二、解答", 1, "essay", "丁", [], 0))
    r = run(qs, {0: "东", 1: "东", 2: "东", 3: "参考答案"},
            {0: "东", 1: "西", 2: "", 3: "我的话"})
    got = r["score"] + r["pending_max"]
    judged_wrong = sum(x["max_score"] for x in r["results"] if x["verdict"] == "wrong")
    assert abs(got + judged_wrong - r["total"]) < 1e-9, (got, judged_wrong, r["total"])
    assert all(x["verdict"] in VERDICTS for x in r["results"])
    assert all(x["score"] <= x["max_score"] for x in r["results"])
t("得分+待确认+判错 = 满分（不变式）", score_arithmetic_invariant)


def editable_scores():
    qs = paper(("一、填空", 1, "fill", "甲", [], 1))
    uid = make_uid(qs[0], 0)
    r = grade(qs, {uid: "东"}, {uid: "东"}, scores={uid: 3.0})
    assert r["total"] == 3.0 and r["score"] == 3.0, r
t("每题分值可编辑并汇总", editable_scores)


def choice_answer_carries_letter_and_text():
    """反例：做题页的单选框存的是【整条选项文本】"A. 四七二十八"，
    标准答案只写 "A"。解析不出字母就会拿 "a. 四七二十八" 去比 "四七二十八"，把对的判成错。"""
    opts = ["A. 四七二十八", "B. 4乘7", "C. 7乘4", "D. 四四十六"]
    qs = paper(("一、选择题", 1, "choice", "4×7 读作", opts, 0),
               ("一、选择题", 2, "choice", "积是多少", opts, 0))
    r = run(qs, {0: "A", 1: "A"}, {0: "A. 四七二十八", 1: "C. 7乘4"})
    assert [x["verdict"] for x in r["results"]] == ["correct", "wrong"], \
        [(x["verdict"], x["reason"]) for x in r["results"]]
t("作答带字母前缀的整条选项文本", choice_answer_carries_letter_and_text)


print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
