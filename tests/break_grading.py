"""批改引擎的变异闸门：把 grading 里真实犯过的错塞回去，看测试是否变红。

这一组比切题更重要：批改的错误方向是「把对的判成错」或「把错的判成对」，
两种都会直接误导家长对孩子的判断。所以每条变异都对应一个这类方向的实际缺陷。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mutate_gate import Mutation, run                    # noqa: E402

ENG = os.path.join(ROOT, "app", "grading", "engine.py")
NRM = os.path.join(ROOT, "app", "grading", "normalizer.py")
TEST = os.path.join(ROOT, "tests", "test_grading.py")

M = [
    Mutation("旧·中文分数分母分子写反", NRM,
             "        return num / den if den and num is not None else None",
             "        return den / num if den and num is not None else None",
             "全半角/大小写/标点/乘号/中文数字/分数"),
    Mutation("关·中文分数支持", NRM,
             "    m = CN_FRAC_RE.match(t)\n    if m:",
             "    m = None\n    if False:",
             "全半角/大小写/标点/乘号/中文数字/分数"),
    Mutation("旧·字母+整条正文解析不出标号", ENG,
             '    m = re.match(r"^([A-H])\\s*[.、．)）]\\s*(.+)$", s, re.I)\n    if m:\n        return ("L", m.group(1).upper())',
             '    m = re.match(r"^([A-H])\\s*[.、．)）]\\s*(.+)$", s, re.I)\n    if False:\n        return ("L", m.group(1).upper())',
             "作答带字母前缀的整条选项文本"),
    Mutation("旧·乘号表漏半角 *", NRM,
             r'MULT_RE = re.compile(r"[x×✕✖∗*＊·∙⋅]")',
             r'MULT_RE = re.compile(r"[x×✕✖∗＊·∙⋅]")',
             "全半角/大小写/标点/乘号/中文数字/分数"),
    Mutation("关·带单位答案的数值提取", NRM,
             '            mv = _num_value(m.group(1))',
             '            mv = None',
             "1/2≡0.5、全半角、中文数字、带单位答案"),
    Mutation("过·单位提取放宽到任意尾串", NRM,
             '                         r"([^\\d]{1,3})$")',
             '                         r"([^\\d]*)")',
             "带单位提取不过度（反例）"),
    Mutation("旧·填空比不上就标待确认（整卷黄标）", ENG,
             '    return (False, f"与标准答案 {alts} 不符（若是同义写法，可加入可接受答案或人工改判）")',
             '    return (None, f"与标准答案 {alts} 不符")',
             "多空可接受答案：命中即对、不匹配即错、可改判"),
    Mutation("旧·判不了时忘了压掉 all_ok（误判为对）", ENG,
             "                if ok is None:\n                    any_unknown = True\n                    all_ok = False",
             "                if ok is None:\n                    any_unknown = True",
             "部分空缺标准答案 → 整题待确认（反例）"),
    Mutation("旧·选项正文不剥行首标号", ENG,
             r'OPTION_LEAD_RE = re.compile(r"^\s*(?:[A-H]|[①-⑳])\s*[.、．)）]?\s*", re.I)',
             r'OPTION_LEAD_RE = re.compile(r"^\s*$")',
             "选择题字母与正文互认（含圆圈选项）"),
    Mutation("旧·圆圈标号不当标记", ENG,
             "    if len(s) == 1 and s in CIRCLED:\n        return (\"N\", str(CIRCLED.index(s) + 1))",
             "    if False:\n        return (\"N\", str(CIRCLED.index(s) + 1))",
             "选择题字母与正文互认（含圆圈选项）"),
    Mutation("旧·uid 不带大题（跨大题串答案）", ENG,
             '    sec = (q.get("section") or "").strip() or "S"',
             '    sec = "S"',
             "不同大题同号不串答案（反例）"),
    Mutation("违·问答题按关键词命中率自动给分", ENG,
             '                verdict = "pending"\n                hint = _keyword_hint(str(exp_list[0]), given)',
             '                hint = _keyword_hint(str(exp_list[0]), given)\n                verdict = "correct" if hint >= 0.3 else "wrong"',
             "问答题不计分，只给命中提示"),
    Mutation("旧·没录标准答案算成错", ENG,
             '            verdict, reason = "pending", "未录入标准答案"',
             '            verdict, reason = "wrong", "未录入标准答案"',
             "无标准答案 → 待确认（反例）"),
    Mutation("关·人工改判", ENG,
             "        if uid in manual:",
             "        if False:",
             "人工改判优先级最高"),
    Mutation("旧·判断题认不出硬判成错", ENG,
             '            verdict = "correct" if ok else ("wrong" if judge_symbol(str(exp_list[0])) and judge_symbol(given) else "pending")',
             '            verdict = "correct" if ok else "wrong"',
             "判断题精确匹配 + 认不出交人工"),
]

if __name__ == "__main__":
    sys.exit(run(M, TEST))
