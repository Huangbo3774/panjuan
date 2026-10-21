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
BADGES = os.path.join(ROOT, "app", "extractor", "badges.py")
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
    Mutation("关·照片右缘密封线整列（请勿混进题干）", LINES,
             "    seal = _sealing_column_ids(items, page_w)",
             "    seal = set()",
             "照片边缘密封线整列要摘掉（含两个反例）"),
    Mutation("旧·照片页宽取 OCR 框右缘（密封线落到页面中间）", LINES,
             "        w_pt, h_pt = im_w * sc, im_h * sc",
             "        w_pt, h_pt = 0.0, 0.0",
             "照片路线用真实页宽且接上页边过滤"),
    Mutation("关·照片路线不接页边过滤", LINES,
             "    items, margin = drop_margin_items(items, w_pt)",
             "    items, margin = items, []",
             "照片路线用真实页宽且接上页边过滤"),
    Mutation("关·括号补全（残缺空位）", RULES,
             "    text, fixed = repair_blanks(text)",
             "    text, fixed = text, 0",
             "补括号真的接在成题链路上"),
    Mutation("关·多行题干行尾的开括号不补（第 3 题永远只有「（」）", RULES,
             '    if "\\n" in text:\n'
             '        text, line_fixed = re.subn(r"[（(][ \\t]*(?=\\n)", "（    ）", text)',
             "    if False:\n"
             "        text, line_fixed = text, 0",
             "多行题干：行尾空位要补齐"),
    Mutation("关·小问 (2) 不另起一行（和上一行拼成一句）", RULES,
             "    sep = \"\\n\" if (_is_item_row(line) or _starts_subq(line)) else \" \"",
             "    sep = \"\\n\" if _is_item_row(line) else \" \"",
             "多行题干：行尾空位要补齐"),
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
    Mutation("旧·OCR 临时图用固定名 + pix.save（同一份卷跑两遍就 500）", LINES,
     '                fp = os.path.join(tmp, f"lines_p{page_no}_{os.getpid()}_{uuid.uuid4().hex[:8]}.png")\n                try:\n                    with open(fp, "wb") as fh:\n                        fh.write(pix.tobytes("png"))',
     '                fp = os.path.join(tmp, f"lines_p{page_no}.png")\n                try:\n                    pix.save(fp)',
     "OCR 临时图唯一名：同一份卷跑两遍不许 500"),
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
    # ---- 小问切分（split_subqs）：四条判据各挡一类误伤，逐条拆掉看红不红 ----
    Mutation("过·小问编号不要求从 1 严格递增（跳号也照样拆）", RULES,
             "        if n == want:", "        if True:",
             "小问切得出来也不误伤空位"),
    Mutation("过·只出现一次编号也当小问（（1）后面没有（2））", RULES,
             "    if len(keep) < 2:\n        return []",
             "    if len(keep) < 1:\n        return []",
             "小问切得出来也不误伤空位"),
    Mutation("过·光杆编号也拆（拆出三行空白）", RULES,
             "        if not seg:\n            return []",
             '        if not seg:\n            out.append({"no": n, "text": "", "blanks": 0})\n            continue',
             "小问切得出来也不误伤空位"),
    Mutation("关·第一个小问之前的引导语不保留", RULES,
             "        if i == 0 and st > 0:", "        if False:",
             "小问切得出来也不误伤空位"),
    Mutation("过·小问号不必成对括号（行内数量词被当编号）", RULES,
             r'SUBQ_MARK_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[）)]")',
             r'SUBQ_MARK_RE = re.compile(r"(?:[（(]\s*)?(\d{1,2})(?:\s*[）)])?")',
             "小问切得出来也不误伤空位"),
    # ---- 空位数：旧口径卡 1–4 个空格，真卷的 6 空格空位会被整批漏数 ----
    Mutation("旧·空位只认 1–4 个空格（33 个空位数出 3 个）", RULES,
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|[（(]\s*[）)])")',
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|（\s{0,4}）|\(\s{1,4}\))")',
             "括号里的长空格流要数成空位"),
    Mutation("旧·括号必须成对（漏掉 OCR 读成的混配（   )）", RULES,
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|[（(]\s*[）)])")',
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|（\s*）|\(\s*\))")',
             "括号里的长空格流要数成空位"),
    Mutation("过·空位允许括号里夹字（把「（ 见上图 ）」也当空位）", RULES,
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|[（(]\s*[）)])")',
             r'BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|[（(][^（）()]{0,8}[）)])")',
             "括号里的长空格流要数成空位"),
    # ---- 题号粘在题干行首：locate 要能认这一行，否则整张图给上一题 ----
    Mutation("关·题号粘行首不认（第 4 题一张图都没有）", LINES,
             "            if len(t) >= 4 and q.get(\"q_no\") is not None:\n"
             "                lead = re.compile",
             "            if False:\n                lead = re.compile",
             "题号粘在题干行首时，区间起点要落在这一行"),
    Mutation("过·粘行首不看本题题号（任何数字前缀都敢当起点）", LINES,
             r'                lead = re.compile(r"^\s*%s\s*[.、．]?" % re.escape(str(q["q_no"])))',
             r'                lead = re.compile(r"^\s*\d{1,3}\s*[.、．]?")',
             "题号粘在题干行首时，区间起点要落在这一行"),
    Mutation("关·教辅栏目横幅不当家具（栏目名被裁成配图）", RULES,
             "    return _is_stage(s)", "    return False",
             "教辅栏目横幅是家具不是配图"),
    Mutation("过·横幅判据不看题号（带【能力提升】的题干被抹成家具）", RULES,
             "    return len(s) <= 16 and not Q_NUM_RE.match(s) and any(k in s for k in STAGE_KW)",
             "    return len(s) <= 24 and any(k in s for k in STAGE_KW)",
             "教辅栏目横幅是家具不是配图"),
    # ---- 第十二轮（周末作业 第 3 页：页眉广告拼成无题号假题 + 581×77 废图）----
    Mutation("关·页眉扫码批改广告不认（拼成无题号假题、裁出废图）", RULES,
             'NOISE_HEADER_RE = re.compile(r"(拍照批改|互动讲解|智能错题本|教材变式练|"\n'
             '                             r"AI\\s*伴学)")',
             'NOISE_HEADER_RE = re.compile(r"(?!x)x")',
             "页眉扫码批改广告不是题目"),
    Mutation("过·页眉判据把「实际用时」也吞掉（正常题干被抹）", RULES,
             'NOISE_HEADER_RE = re.compile(r"(拍照批改|互动讲解|智能错题本|教材变式练|"\n'
             '                             r"AI\\s*伴学)")',
             'NOISE_HEADER_RE = re.compile(r"(拍照批改|互动讲解|智能错题本|教材变式练|"\n'
             '                             r"AI\\s*伴学|实际用时)")',
             "页眉扫码批改广告不是题目"),
    # ---- 条目行：空位里的空白不是卡片间隔（周末作业 第 1 页第 1 题）----
    Mutation("过·空位里的空白当条目间隔（题干被误插换行、空位被撑开）", RULES,
             '    masked = BLANK_RE.sub("□", s)',
             "    masked = s",
             "括号里的空白不是连线卡片的间隔"),
    # ---- 闯关式综合实践卷：关卡横幅接在题干末尾（综合实践单元(1) p1 第 5 题）----
    Mutation("关·66 关卡横幅不当家具（「第二关一方向应用我能行」接进题干）", RULES,
             "    if NOISE_STAGE_BANNER_RE.match(compact):\n        return True",
             "    if False:\n        return True",
             "闯关横幅不许接在题干末尾（含反例）"),
    Mutation("过·66 横幅判据把正常题干也吞掉（「第二关我们来到了动物园」）", RULES,
             'NOISE_STAGE_BANNER_RE = re.compile(\n'
             '    r"^第[一二三四五六七八九十]+关[—\\-一]?.{0,14}(大本营|我能行|闯关|挑战)")',
             'NOISE_STAGE_BANNER_RE = re.compile(\n'
             '    r"^第[一二三四五六七八九十]+关")',
             "闯关横幅不许接在题干末尾（含反例）"),
    # ---- 行首地图标签挡住题号（综合实践单元(1) 第 3 页第三大题）----
    Mutation("关·66 行首地图标签挡住题号（两题并成一道「1. 1.喷泉」）", RULES,
             'LEAD_LABEL_QNO_RE = re.compile(\n'
             '    r"^((?:[^\\s\\d]{1,8}[ \\t\\u3000]{2,}){1,3})(\\d{1,3})[.、．](?!\\d)\\s*(.*)$")',
             'LEAD_LABEL_QNO_RE = re.compile(r"(?!x)x")',
             "行首地图标签不许挡住题号（含两个反例）"),
    Mutation("过·66 题号跳号也认（正文被切成假题）", RULES,
             "    if last_no is not None:\n"
             "        if no != last_no + 1:\n"
             "            return None, s",
             "    if last_no is not None:\n"
             "        if False:\n"
             "            return None, s",
             "行首地图标签不许挡住题号（含两个反例）"),
    Mutation("过·66 长正文也当行首标签（题干被吞）", RULES,
             "r\"^((?:[^\\s\\d]{1,8}[ \\t\\u3000]{2,}){1,3})(\\d{1,3})[.、．](?!\\d)\\s*(.*)$\")",
             "r\"^((?:[^\\s\\d]{1,99}[ \\t\\u3000]{2,}){1,3})(\\d{1,3})[.、．](?!\\d)\\s*(.*)$\")",
             "行首地图标签不许挡住题号（含两个反例）"),
    # ---- 教辅活页的页面家具（品牌行/填写栏/提示栏/标题上的广告）----
    Mutation("关·出版社品牌行当正文（王朝霞广告并进题干）", RULES,
             'NOISE_BRAND_RE = re.compile(r"王朝霞|少而精|活页同步练习册|"\n'
             '                            r"去除封面|化繁为简|品质优良|价格公道")',
             'NOISE_BRAND_RE = re.compile(r"(?!x)x")',
             "教辅活页的品牌行"),
    Mutation("关·班级姓名填写栏当正文", RULES,
             'NOISE_FILLIN_RE = re.compile(r"班级\\s*[/／]\\s*姓名|^姓\\s*名\\s*[:：]|"\n'
             '                             r"^日\\s*期\\s*[:：]|^实际用时\\s*[:：]?$")',
             'NOISE_FILLIN_RE = re.compile(r"(?!x)x")',
             "教辅活页的品牌行"),
    Mutation("关·提示栏内容并进上一题（解题妙招/知识打卡）", RULES,
             "            if any(k in line for k in SIDEBAR_KW):",
             "            if False:",
             "教辅活页的品牌行"),
    Mutation("关·标题行上的答案页码不摘（分段名带广告印上卷面）", RULES,
             '    out = NOISE_ANSWER_REF_RE.sub(" ", s)',
             "    out = s",
             "教辅活页的品牌行"),
    # ---- 彩色题号徽标（白字红底，RapidOCR 检测不到；周末作业(1) 第 1/2 页）----
    Mutation("关·徽标右边不用有题干（装饰图标全当题号）", BADGES,
             "        if not _has_text_on_right(box, items, float(W)):\n            continue",
             "        if False:\n            continue",
             "彩色题号徽标"),
    Mutation("关·徽标识别结果不校验（乱码/低置信度也当题号）", BADGES,
             '        if not DIGIT_RE.match(text) or text == "0" or float(conf) < DIGIT_CONF_MIN:\n            continue',
             "        if False:\n            continue",
             "彩色题号徽标"),
    Mutation("关·已有 OCR 框里的题号不切开（2看一看 认不出题号）", BADGES,
             '                    it["text"] = m.group(1) + "." + tail',
             '                    it["text"] = t',
             "彩色题号徽标"),
    Mutation("过·徽标尺寸不设上限（整条横幅当题号）", BADGES,
             "        if w < W * BADGE_W_FRAC[0] or w > W * BADGE_W_FRAC[1]:\n"
             "            continue\n"
             "        if h < W * BADGE_W_FRAC[0] or h > W * BADGE_W_FRAC[1]:\n"
             "            continue",
             "        if w < W * BADGE_W_FRAC[0]:\n"
             "            continue\n"
             "        if h < W * BADGE_W_FRAC[0]:\n"
             "            continue",
             "彩色题号徽标"),
    Mutation("过·课时序号「第5课时」被补成题号（成品印成「第 5. 课时」）", BADGES,
             "        if _after_ordinal_marker(box, items):\n"
             "            continue\n",
             "        if False:\n"
             "            continue\n",
             "彩色题号徽标"),
    # ---- 第九轮（用户截图：乘法题被判成判断题；图片选项的选择题没有尺在量）----
    Mutation("旧·判断信号带光秃秃的 ×（所有乘法题被判判断题）", RULES,
             'JUDGE_HINT = ("对的打", "正确的打", "错的打", "判断", "对的画", "正确的画",\n'
             '              "打√", "打×", "画√", "画×")',
             'JUDGE_HINT = ("对的打", "正确的打", "错的打", "判断", "对的画", "正确的画",\n'
             '              "打√", "打×", "画√", "画×", "×", "√")',
             "乘法题不许被判成判断题"),
    Mutation("关·选择题信号（题干要「填序号」也不提醒）", RULES,
             'CHOICE_CUE = re.compile(\n'
             '    r"填序号|填字母|正确的序号|选一选|选择题|单项选择|多项选择|选出|"\n'
             '    r"正确的是|错误的是|不正确的是|不能用.{0,16}表示的是")',
             'CHOICE_CUE = re.compile(r"(?!x)x")',
             "图片选项的选择题：可作答 + 待校对"),
    Mutation("关·「像选择题却没选项」不标待校对", RULES,
             '    if (q["qtype"] != "choice" and not judge_signal',
             '    if (False and q["qtype"] != "choice" and not judge_signal',
             "图片选项的选择题：可作答 + 待校对"),
    Mutation("关·待校对汇总不看 review_note（提醒被置信度冲掉）", RULES,
             '    q["needs_review"] = q["confidence"] < 0.7 or bool(q.get("review_note"))',
             '    q["needs_review"] = q["confidence"] < 0.7',
             "图片选项的选择题：可作答 + 待校对"),
    # ---- 第十九轮（综合实践单元(1)：附加题整段被裁进上一题的图）----
    Mutation("关·附加题不分段（标题和两道填空并进上一题）", RULES,
             '    if SECTION_BONUS_RE.match(s):\n'
             '        return True, "", _clean_title(s)\n',
             '    if False:\n        return True, "", _clean_title(s)\n',
             "附加题单独成段（含反例）"),
    Mutation("过·附加题规则不锚定整行（「附加题部分…」也当大题）", RULES,
             'SECTION_BONUS_RE = re.compile(\n'
             '    r"^附加题\\s*[。.．]?\\s*(?:[（(]\\s*共\\s*\\d+\\s*分\\s*[）)])?\\s*$")',
             'SECTION_BONUS_RE = re.compile(r"附加题")',
             "题干里的附加题不误分段（反例）"),
]

if __name__ == "__main__":
    sys.exit(run(M, TEST))
