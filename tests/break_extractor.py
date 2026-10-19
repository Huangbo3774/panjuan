"""题型识别（extractor）的变异闸门：把已修过的缺陷塞回 rules.py，看测试是否变红。

每条变异都是本项目真实踩过的坑，不是假想的坏代码。
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

RULES = os.path.join(ROOT, "app", "extractor", "rules.py")
LINES = os.path.join(ROOT, "app", "extractor", "lines.py")
TEST = os.path.join(ROOT, "tests", "test_extractor.py")

M = [
    Mutation("旧·分段标题长度闸门", RULES,
             '    if m:\n        return True, "", _clean_title(s)',
             '    if m and len(m.group(2)) <= 24:\n        return True, "", _clean_title(s)',
             "带水印的日/课时标题仍认分段"),
    Mutation("旧·页码正则（会吞掉裸题号）", RULES,
             r'NOISE_PAGENO_RE = re.compile(r"^[·•。.]\s*\d{1,3}\s*[·•。]$|^\d{1,3}\s*[·•。]\s*\d{1,3}$")',
             r'NOISE_PAGENO_RE = re.compile(r"^[·•.。]?\s*\d{1,3}\s*[·•.。]+$")',
             "裸题号"),
    Mutation("关·编号倒退分段", RULES,
             "            if last_no is not None and no < last_no and numbered_in_sec >= 2:",
             "            if False:",
             "编号倒退自动分段"),
    Mutation("关·大题序号递增判据", RULES,
             "        ordinal = (n is not None and expect_no is not None and n >= expect_no",
             "        ordinal = (False and n is not None and expect_no is not None and n >= expect_no",
             "无关键词大题靠序号递增切开"),
    Mutation("新·大题序号判据丢掉空位护栏", RULES,
             "                   and len(rest) <= 60 and not BLANK_RE.search(rest))",
             "                   and len(rest) <= 300)",
             "长题/带空位的行不当大题（反例）"),
    Mutation("旧·大题标题 30 字上限（吞掉长题）", RULES,
             "                   and len(rest) <= 60 and not BLANK_RE.search(rest))",
             "                   and len(rest) <= 24 and not BLANK_RE.search(rest))",
             "长引入句的大题名仍认分段（回归）"),
    Mutation("关·水印过滤", RULES,
             "        if _is_noise(line):", "        if False:",
             "水印/页码/页眉不进题目"),
    Mutation("关·教辅栏目行过滤", RULES,
             "        if _is_stage(line):", "        if False:",
             "教辅栏目行不当题"),
    Mutation("旧·英文分组错位", RULES,
             'return any(k in (m.group(3) or "").lower() for k in SECTION_EN_KW), "", s',
             'return any(k in (m.group(2) or "").lower() for k in SECTION_EN_KW), "", s',
             "英文 Section"),
    Mutation("旧·长问句也压 0.6（整卷标待校对）", RULES,
             '            q["qtype"] = "essay"\n            conf = 0.8',
             '            q["qtype"] = "essay"\n            conf = 0.6',
             "长问答置信达标/短残句仍待校对"),
    Mutation("关·表头跳过", RULES,
             "        if _looks_like_header(line) and not seen_numbered:",
             "        if False:",
             "表头不当题目（反例）"),
    Mutation("关·卷名提升", RULES,
             '        if (q0.get("q_no") is None and not q0.get("options")',
             "        if (False and q0.get(\"q_no\") is None and not q0.get(\"options\")",
             "卷名提升为标题、不当题目"),
    Mutation("过·卷名提升不看空位", RULES,
             '                and not BLANK_RE.search(q0["text"])',
             "                and True",
             "带空位的首行仍是题目（反例）"),
    Mutation("旧·没有大题标题就整行丢弃", RULES,
             '            new_section("")',
             "            skipped.append(line)\n            continue",
             "无题号文本不丢内容（反例）"),
    # ── 本轮（审计器：装订栏混进题干 / 括号读残）新增判据 ──
    Mutation("关·装订栏过滤（竖排字混进题干）", LINES,
             "            items, margin = drop_margin_items(items, width_pt)",
             "            items, margin = items, []",
             "装订栏过滤真的接在读页链路上"),
    Mutation("旧·装订栏按【框左边】判贴边（咬掉行尾）", LINES,
             "        in_edge = x1 <= MARGIN_ZONE_PT or x0 >= page_w - MARGIN_ZONE_PT",
             "        in_edge = x0 <= MARGIN_ZONE_PT or x1 >= page_w - MARGIN_ZONE_PT",
             "贴边正文行尾不许被当装订栏（反例）"),
    Mutation("关·括号补全（残缺空位）", RULES,
             "    text, fixed = repair_blanks(text)",
             "    text, fixed = text, 0",
             "补括号真的接在成题链路上"),
    Mutation("过·括号补全不看行首是不是汉字", RULES,
             '            elif out and re.match(r"[\\u4e00-\\u9fff]", ("".join(out)).rstrip()[-1:] or " "):',
             "            elif out:",
             "补括号不许误伤序号/选项/已配对空位（反例）"),
    Mutation("关·不配对标待校对", RULES,
             '    q["needs_review"] = q["confidence"] < 0.7 or bool(q.get("review_note"))',
             '    q["needs_review"] = q["confidence"] < 0.7',
             "补不回的括号要标待校对（含反例）"),
    Mutation("旧·卷头品牌行不当表头", RULES,
             '                "测评卷", "天天练", "课时练", "单元测评", "年级上册", "年级下册",',
             '                "", "", "", "", "", "",',
             "卷名提升为标题、不当题目"),
    # ── 裸题号（题号被 OCR 单独切成一行，题干在整张图底下）──
    Mutation("关·（1）（2）小问并回上一题（卷面出现重号假题）", RULES,
             '        if no is not None and cur_q is not None and cur_q.get("no_form") == "plain" \\',
             "        if False and no is not None and cur_q is not None \\",
             "小问（1）（2）不许切成两道重号题（含反例）"),
    Mutation("过·小问判据不看上一题的编号形式（平排（1）（2）被并成一道）", RULES,
             'and cur_q.get("no_form") == "plain" \\',
             'and cur_q.get("no_form") in ("plain", "paren", "") \\',
             "小问（1）（2）不许切成两道重号题（含反例）"),
    Mutation("关·带题号的行不当卷首信息行（第 1 题被当表头丢掉）", RULES,
             "    if Q_NUM_RE.match(s) or Q_CIRCLED_RE.match(s):\n        return False",
             "    if False:\n        return False",
             "卷首信息行不许吃掉带题号的第一题"),
    Mutation("关·裸题号单独成行也开题（整道题凭空消失）", RULES,
             "        bare = _bare_number_starts_question(line, last_no, cur_q, numbered_in_sec)",
             "        bare = None",
             "题号单独成行也要开一道题"),
    Mutation("过·裸题号不要求正好接上一题（图里孤立数字乱开题）", RULES,
             "    return n if n == last_no + 1 else None",
             "    return n",
             "反例：不接号的数字不许开题"),
    Mutation("过·裸题号不看上一题有没有题干（一串刻度数字切成几道空题）", RULES,
             '    if cur_q is None or len(str(cur_q.get("text") or "").strip()) < 4:',
             "    if cur_q is None:",
             "反例：不接号的数字不许开题"),
    Mutation("关·裸题号接在成题链路上（判据对、线没接）", RULES,
             '            push_question(bare, "", cur_sec, "plain")',
             "            cur_q = None",
             "裸题号判据真的接在成题链路上"),
    Mutation("关·区间起点抬到图顶上的题号行（图落进上一题）", LINES,
             "        n = anchor_row(q, n)",
             "        n = n",
             "区间起点抬到图顶上那行题号（含反例）"),
    Mutation("过·抬起点时不核对那行的数字就是本题题号", LINES,
             '        return n - 1 if int(m.group(1)) == int(q["q_no"]) else n',
             "        return n - 1",
             "区间起点抬到图顶上那行题号（含反例）"),
]

if __name__ == "__main__":
    sys.exit(run(M, TEST))
