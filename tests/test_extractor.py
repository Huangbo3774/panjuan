"""题型识别单测：正例 + 反例。

反例尤其重要：PRD 的题号正则 `^\\d{1,3}[.、．)]` 会把 "4. 4×7 读作" 里的
"4×7" 当成新题号，也会把 "1." 之外的乘号误判。这里把这类坑钉住。
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

from app.extractor.rules import extract, flatten_questions            # noqa: E402
from app.extractor.rules import _parse_question_no as _parse          # noqa: E402

ok_n = bad_n = 0


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}")


def qs(res):
    return flatten_questions(res)


print("\n[基本切分]")
def basic():
    lines = [
        "一、选择题（每题 3 分，共 15 分）",
        "1. 4×7 读作（  ）",
        "A. 4乘7    B. 4乘以7    C. 7乘4    D. 四七二十八",
        "2. 一个因数是 6，另一个因数是 8，积是（  ）",
        "A. 14      B. 48        C. 24      D. 16",
        "二、填空题（每空 2 分，共 20 分）",
        "3. 一年有＿＿个月，其中大月有＿＿个。",
        "三、解答题（共 25 分）",
        "4. 果园里有 6 行桃树，每行 8 棵，一共有多少棵？",
    ]
    r = extract(lines, "测试卷")
    q = qs(r)
    assert [x["q_no"] for x in q] == [1, 2, 3, 4], f"题号错: {[x['q_no'] for x in q]}"
    assert q[0]["qtype"] == "choice", f"第1题应 choice，实际 {q[0]['qtype']}"
    assert len(q[0]["options"]) == 4, f"选项数 {len(q[0]['options'])}: {q[0]['options']}"
    assert q[2]["qtype"] == "fill", f"第3题应 fill，实际 {q[2]['qtype']}"
    assert q[2]["blanks"] == 2, f"应有 2 个空，实际 {q[2]['blanks']}"
    assert q[3]["qtype"] == "essay", f"第4题应 essay，实际 {q[3]['qtype']}"
    assert len(r["sections"]) == 3, f"大题数 {len(r['sections'])}"
t("选择/填空/解答三题型 + 3 个大题", basic)


def multiply_not_question():
    """反例：题干里的乘号不能被当成题号（PRD 原正则的坑）。"""
    lines = ["一、选择题", "1. 4×7 读作（  ）", "A. x    B. y    C. z    D. w"]
    q = qs(extract(lines))
    assert len(q) == 1, f"应只切出 1 题，实际 {len(q)}: {[x['text'] for x in q]}"
t("题干中的乘号不被误判为题号（反例）", multiply_not_question)


def decimal_not_question():
    """反例：句点后不要求空格后，小数不能被当成题号。"""
    assert _parse("3.5 与 4.2 哪个大") == (None, "3.5 与 4.2 哪个大")
    assert _parse("1.一共有（ ）个") == (1, "一共有（ ）个")
    assert _parse("长 3.5 厘米") == (None, "长 3.5 厘米")
t("小数不被当题号，句点无空格仍可切（反例）", decimal_not_question)


def inline_options():
    lines = ["一、选择题", "3. 五八（  ）四九（  ）六七（  ）",
             "A. 四十 三六 四十二     B. 四十 三十六 四十二",
             "C. 四十五 三十六 四十二  D. 四十 三十六 四十八"]
    q = qs(extract(lines))
    assert len(q) == 1, f"应 1 题，实际 {len(q)}"
    assert len(q[0]["options"]) >= 3, f"选项太少: {q[0]['options']}"
    assert q[0]["qtype"] == "choice"
t("一行内多个选项也能拆开", inline_options)


def judge_type():
    lines = ["二、判断题（对的打√，错的打×）",
             "1. 0 乘任何数都得 0。",
             "2. 5×0 和 0+5 结果相同。"]
    q = qs(extract(lines))
    assert all(x["qtype"] == "judge" for x in q), f"应全 judge: {[x['qtype'] for x in q]}"
t("判断题识别（对的打√）", judge_type)


def multiplication_is_not_a_judge_signal():
    """乘号不是判断信号：题干里只要有 × 就判 judge，做题页只给对/错，孩子没处写答案。

    真实卷（第三单元练习题）实测 8 道乘法题因此被判成判断题；用户原话"这题都怎么做啊"。
    判断题的信号必须是"对的打/判断/画√"这类指令，不是光秃秃一个符号。
    """
    lines = ["一、填一填。",
             "1. 2×3 可以表示（  ）个（  ）相加。",
             "2. 6×2=（  ），5×3=（  ）。"]
    q = qs(extract(lines))
    assert len(q) == 2, f"应切出 2 题：{[x['text'][:20] for x in q]}"
    assert all(x["qtype"] != "judge" for x in q), \
        f"乘法题被判成判断题：{[(x['text'][:16], x['qtype']) for x in q]}"
    assert q[0]["qtype"] == "fill" and q[1]["qtype"] == "fill", \
        f"应是有空位的填空题：{[x['qtype'] for x in q]}"
t("乘法题不许被判成判断题", multiplication_is_not_a_judge_signal)


def picture_choice_is_flagged_not_turned_into_judge():
    """选项是图片的选择题：OCR 读不到 A/B/C/D，不许判成判断题，且要挂待校对。

    真实卷第 3 题（自然科普·树叶）：题干"不能用2×4表示的是（ ）(填序号)"，
    四片叶子是图片选项。修掉乘号误判后它应是可作答的 fill，并提醒家长补选项。
    """
    lines = ["第2天 儿童乐园",
             "3. 下面的树叶中，不能用2×4表示的是（  ）。(填序号)",
             "4. 第二题的题干文字。"]
    q = qs(extract(lines))
    assert len(q) == 2, f"应切出 2 题：{[x['text'][:18] for x in q]}"
    assert q[0]["qtype"] != "judge", f"又是判断题：{q[0]['qtype']}"
    assert q[0]["qtype"] == "fill", f"应保留成可作答的 fill：{q[0]['qtype']}"
    assert q[0]["needs_review"], "题干明写填序号却没选项，必须挂待校对"
    assert "选择题" in str(q[0].get("review_note") or ""), \
        f"待校对理由没说清：{q[0].get('review_note')}"
t("图片选项的选择题：可作答 + 待校对", picture_choice_is_flagged_not_turned_into_judge)


def real_judge_section_still_works():
    """反例保险：修掉乘号后，真正的判断题（大题名给的信号）不能跟着丢。"""
    lines = ["三、判断。（对的画√，错的画×）",
             "1. 所有直角都一样大。",
             "2. 长方形的四条边都相等。"]
    q = qs(extract(lines))
    assert all(x["qtype"] == "judge" for x in q), f"判断题丢了：{[x['qtype'] for x in q]}"
t("真判断题仍然认（反例保险）", real_judge_section_still_works)


def header_not_question():
    """反例：表头「班级/姓名/满分」不该变成题目。"""
    lines = ["第三单元达标练习", "班级＿＿ 姓名＿＿ 得分＿＿", "满分：100 分  时间：40 分钟",
             "一、选择题", "1. 例子（  ）", "A. a  B. b  C. c  D. d"]
    r = extract(lines)
    q = qs(r)
    assert len(q) == 1, f"应只有 1 题，实际 {len(q)}: {[x['text'] for x in q]}"
    assert any("班级" in x for x in r["skipped_header_lines"]), "表头应被记为跳过行"
t("表头不当题目（反例）", header_not_question)


def no_loss():
    """核心不变式：一行内容都不能丢。宁可切错也不能漏。"""
    lines = ["一、选择题", "1. 题目甲（  ）", "A. a  B. b  C. c  D. d",
             "2. 题目乙。", "3. 题目丙。", "二、填空题", "4. 空是＿＿。",
             "5. 长题干题目，需要写出计算过程和答语。"]
    r = extract(lines)
    joined = " ".join(x["text"] + " " + " ".join(x["options"]) for x in qs(r))
    for key in ("题目甲", "题目乙", "题目丙", "空是", "计算过程"):
        assert key in joined, f"内容丢失：{key}"
t("内容零丢失不变式", no_loss)


def empty_paren_is_blank():
    """PRD 只写「全角括号长度≥2」；二年级的（　）常是 0~2 个空格，也要认成空位。"""
    lines = ["一、填空题", "1. 光沿（）传播。", "2. 声音速度（  ）米每秒。"]
    q = qs(extract(lines))
    assert q[0]["qtype"] == "fill", f"空括号应判 fill，实际 {q[0]['qtype']}"
    assert q[1]["qtype"] == "fill"
t("空括号也算填空位（补 PRD 缺口）", empty_paren_is_blank)


def never_empty():
    """兜底：完全没有题号的乱文本，也必须返回至少一道题，不能返回空。
    （加了"隐式大题"之后，这类行走正常切题路径而非兜底路径，
      所以断言改为"内容不丢 + 有题产出"，不再要求置信度极低。）"""
    r = extract(["这是一段没有任何题号的文字内容"])
    q = qs(r)
    assert len(q) >= 1, "兜底失败，返回了 0 题"
    assert "文字内容" in q[0]["text"], f"内容丢失: {q[0]['text']}"
    # 必须走【隐式大题】这条正常路径，不许退到 fallback：
    # fallback 把每行都压成 confidence 0.2 的"整页当一堆文字"，是最后一道保险而不是常态。
    # 这条断言也让「没有大题标题就开一节」变成一把被量过的尺（变异闸门验证过它会红）。
    assert not any(x.get("fallback") for x in q), f"退到了 fallback 路径: {[x.get('confidence') for x in q]}"
    # 真正走到兜底分支时（全空白输入）才要求极低置信度
    r2 = extract(["   ", "", "  "])
    assert qs(r2) == [], "全空白输入不该造出题"
t("无题号文本不丢内容（反例）", never_empty)


def confidence_gate():
    lines = ["一、选择题", "1. 例子（  ）", "A. a  B. b  C. c  D. d", "2. 短"]
    q = qs(extract(lines))
    assert q[0]["needs_review"] is False, "清晰选择题不该标待校对"
    assert any(x["needs_review"] for x in q), "低置信题应标待校对"
t("置信度 <0.7 标待校对", confidence_gate)


def circled_numbers():
    """连线/排序题里 ①②③ 是条目 → 当题号。"""
    lines = ["四、排序题", "①最后用帽子盖住鸡蛋顶上的小洞。", "②然后用彩纸做一顶尖尖的小帽子。",
             "③先在鸡蛋顶部打一个小洞。"]
    q = qs(extract(lines))
    assert len(q) == 3, f"排序题里圆圈序号应切成 3 项，实际 {len(q)}"
    assert [x["q_no"] for x in q] == [1, 2, 3], f"{[x['q_no'] for x in q]}"
t("排序题里圆圈数字作题号", circled_numbers)


def circled_are_options_in_choice():
    """反例：选择题里 ①②③ 是选项，不能当题号（扫描卷实测：会被切成 4 道假题）。"""
    lines = ["一、选择题", "1. 小宇在家的（ ）方向。", "①东 ②南 ③西 ④北"]
    q = qs(extract(lines))
    assert len(q) == 1, f"应只 1 题，实际 {len(q)}: {[x['text'] for x in q]}"
    assert len(q[0]["options"]) == 4, f"圆圈应成为 4 个选项，实际 {q[0]['options']}"
    assert q[0]["qtype"] == "choice", f"应 choice，实际 {q[0]['qtype']}"
t("选择题里圆圈数字作选项（反例）", circled_are_options_in_choice)


def answer_key_not_questions():
    """反例：答案区不能被切成题目（实测英文样本 "参考答案：1.B 2.A" 被切成 7 道假题）。"""
    lines = ["一、选择题", "1. 例子（ ）", "A. a  B. b  C. c  D. d",
             "2. 例子二（ ）", "A. e  B. f  C. g  D. h",
             "参考答案：1.B 2.A"]
    r = extract(lines)
    q = qs(r)
    assert len(q) == 2, f"应只 2 题，实际 {len(q)}: {[(x['q_no'],x['text']) for x in q]}"
    assert r["answer_key_lines"], "答案区应被单独收集"
    assert any("1.B" in x or "B" in x for x in r["answer_key_lines"])
t("答案区不当题目（反例）", answer_key_not_questions)


def lone_letter_not_question():
    """反例：单独成行的 "B" 是答案，不是第 2 题。"""
    lines = ["一、选择题", "1. 例子（ ）", "A. a  B. b  C. c  D. d", "B"]
    q = qs(extract(lines))
    assert len(q) == 1, f"应只 1 题，实际 {len(q)}"
t("孤立字母不当题（反例）", lone_letter_not_question)


print("\n[分段·水印·栏目（真实扫描卷暴露的缺口）]")


def _dup(res):
    """重号只在大题内部算：中文卷每大题都从 1 重新编号。"""
    n = 0
    for sec in res["sections"]:
        sn = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
        n += len(sn) - len(set(sn))
    return n


def section_by_ordinal_not_keyword():
    """正例：大题名既不带动词的关键词（「三、公园畅游指南」「四、应急疏散路线指引」
    是真实卷的原话），只能靠【序号递增】认出分段。关键词表永远补不全。"""
    lines = ["一、填一填。", "1.甲（  ）", "2.乙（  ）",
             "三、公园畅游指南。（共21分）", "1.丙（  ）", "①东  ②西  ③北",
             "四、应急疏散路线指引。（共18分）", "2.丁（  ）"]
    r = extract(lines)
    names = [x["name"] for x in r["sections"]]
    assert len(r["sections"]) == 3, f"应 3 个大题，实际 {len(r['sections'])}: {names}"
    assert _dup(r) == 0, f"重号 {_dup(r)}: {names}"
    assert any("公园畅游" in n for n in names), f"无关键词大题没被认出: {names}"
t("无关键词大题靠序号递增切开", section_by_ordinal_not_keyword)


def increasing_numbers_do_not_split():
    """反例：同一小题号序列里编号递增，不能被"倒退分段"误切。"""
    lines = ["一、选择题", "1.题A（  ）", "A. a  B. b", "2.题B（  ）", "A. a  B. b", "3.题C（  ）"]
    r = extract(lines)
    assert len(r["sections"]) == 1, f"应 1 个大题，实际 {len(r['sections'])}"
    assert len(qs(r)) == 3, f"应 3 题，实际 {len(qs(r))}"
t("编号递增不误分段（反例）", increasing_numbers_do_not_split)


def restart_splits_without_header():
    """正例：编号从 3 倒回 1 且中间没有标题行 → 新的编号序列（教辅书每天重新编号）。"""
    lines = ["第1天", "1.甲", "2.乙", "第三步提思维", "3.丙", "1.丁", "2.戊"]
    r = extract(lines)
    assert _dup(r) == 0, f"重号 {_dup(r)}，分段 {[x['name'] for x in r['sections']]}"
    assert len(r["sections"]) == 2, f"应 2 段，实际 {len(r['sections'])}"
t("编号倒退自动分段", restart_splits_without_header)


def noisy_day_header_is_section():
    """回归：标题后面拖了水印长尾（剩余 27 字）也必须认出分段。
    曾用「剩余长度 ≤24 才算分段」，真实行「第2天 画校园路线图[课时2]   拍照秒批」漏认，
    导致整卷重号 20。"""
    lines = ["第1天 认识方向[课时1]            拍照秒批", "1.甲（  ）",
             "第2天   画校园路线图[课时2]            拍照秒批          视频讲解", "1.乙（  ）"]
    r = extract(lines)
    assert len(r["sections"]) == 2, f"应 2 段，实际 {len(r['sections'])}: {[x['name'] for x in r['sections']]}"
    assert _dup(r) == 0, f"重号 {_dup(r)}"
    assert "拍照秒批" not in r["sections"][0]["name"], f"标题没洗净水印: {r['sections'][0]['name']}"
t("带水印的日/课时标题仍认分段", noisy_day_header_is_section)


def watermark_lines_are_dropped():
    """正例：扫描 App 水印、页码、跑马页眉进 dropped_noise，不进题目。"""
    lines = ["一、填空题", "1.甲（  ）", "夸克扫描王", "极速扫描，就是高效", "·38·",
             "小学数学二年级上册·BS版", "2.乙（  ）"]
    r = extract(lines)
    q = qs(r)
    assert len(q) == 2, f"应 2 题，实际 {len(q)}: {[x['text'] for x in q]}"
    assert not any("扫描" in x["text"] for x in q), "水印混进题干"
    assert len(r["dropped_noise"]) == 4, f"噪声计数 {len(r['dropped_noise'])}: {r['dropped_noise']}"
t("水印/页码/页眉不进题目", watermark_lines_are_dropped)


def bare_number_not_pageno():
    """反例：「2.」是题号后内容全在图里的残缺题，绝不能当页码丢掉。"""
    lines = ["一、填空题", "1.甲（  ）", "2.", "3.丙（  ）"]
    r = extract(lines)
    got = [q["q_no"] for q in qs(r)]
    assert 2 in got, f"题号 2 被当页码丢了: {got}"
    assert "2." not in r["dropped_noise"], f"「2.」进了噪声: {r['dropped_noise']}"
t("裸题号「2.」不当页码（反例）", bare_number_not_pageno)


def stage_marker_not_question():
    """栏目行（第一步过考点 / 知识演练场）既不是题目也不是分段——编号会跨栏目延续。"""
    lines = ["第1天", "第一步过考点", "1.甲", "第二步练变式", "2.乙", "第三步提思维", "3.丙"]
    r = extract(lines)
    assert len(qs(r)) == 3, f"栏目行变成了题目: {[x['text'] for x in qs(r)]}"
    assert len(r["sections"]) == 1, f"栏目被误当分段: {[x['name'] for x in r['sections']]}"
    assert len(r["stage_markers"]) == 3, f"栏目计数 {len(r['stage_markers'])}"
t("教辅栏目行不当题/不当分段（反例）", stage_marker_not_question)


def english_section_detected():
    """正例：英文卷 Section A/B/C 要认作分段（曾用错正则分组，永远认不出）。"""
    lines = ["Section A  Multiple Choice", "1. one（  ）", "A. a  B. b",
             "Section B  Fill in the blank", "2. two __"]
    r = extract(lines)
    names = [x["name"] for x in r["sections"]]
    assert len(r["sections"]) == 2, f"应 2 段，实际 {names}"
    assert any("Multiple Choice" in n for n in names), names
t("英文 Section 识别为分段", english_section_detected)


def ordinal_guard_keeps_stem():
    """反例：以「二、」开头但自带答题空位/很长的行是题干，不能被序号判据吞成大题标题。"""
    lines = ["一、填空题", "1.甲（  ）", "二、把下面的数填在（  ）里：24、6、30、48"]
    r = extract(lines)
    assert len(r["sections"]) == 1, f"题干被当大题: {[x['name'] for x in r['sections']]}"
t("长题/带空位的行不当大题（反例）", ordinal_guard_keeps_stem)


def long_title_accepted():
    """回归：真实大题名可以带一长句引入（31 字）。曾用 24/30 字上限，
    把「六、随着无人驾驶技术的发展，无人配送车已投入使用。(共 12 分)」吞掉，
    该大题的题被并进上一节，报成"·续"+假重号。"""
    lines = ["五、小玉绘制了自己家附近的平面图。(共 18 分)", "1.甲（  ）",
             "六、随着无人驾驶技术的发展，无人配送车已投入使用。(共 12 分)", "1.乙（  ）"]
    r = extract(lines)
    names = [x["name"] for x in r["sections"]]
    assert len(r["sections"]) == 2, f"应 2 个大题，实际 {names}"
    assert _dup(r) == 0, f"重号 {_dup(r)}: {names}"
    assert not any("·续" in n for n in names), f"标题被吞: {names}"
t("长引入句的大题名仍认分段（回归）", long_title_accepted)


def long_essay_confidence():
    """正例：完整长问句（够长 + 句末标点）置信度要过 0.7，别把整卷标成待校对。
    反例：短残句（OCR 断行/图形碎片）必须仍然标 needs_review。"""
    lines = ["四、解决问题。",
             "1.果园里有 6 行桃树，每行 8 棵，一共有多少棵？请写出算式并作答。",
             "2.东", "3.图书馆       西            操场"]
    r = extract(lines)
    q = qs(r)
    assert q[0]["qtype"] == "essay", q[0]["qtype"]
    assert not q[0]["needs_review"], f"完整长题干被标待校对: {q[0]['confidence']}"
    assert all(x["needs_review"] for x in q[1:]), f"短残句没标待校对: {[(x['text'],x['confidence']) for x in q[1:]]}"
t("长问答置信达标/短残句仍待校对", long_essay_confidence)


def paper_title_promoted():
    """正例：卷名行（没题号、没空位、短）不该变成第 1 道题。"""
    lines = ["第三单元 过关练习", "班级＿＿ 姓名＿＿ 满分 100",
             "一、选择题", "1. 4×7 读作（  ）", "A. 四七二十八  B. 4乘7"]
    r = extract(lines)
    q = qs(r)
    assert len(q) == 1, f"卷名/表头变成了题目: {[(x['q_no'], x['text'][:20]) for x in q]}"
    assert r["title"] == "第三单元 过关练习", r["title"]
    assert any("班级" in x for x in r["skipped_header_lines"]), r["skipped_header_lines"]
t("卷名提升为标题、不当题目", paper_title_promoted)


def short_first_line_with_blank_stays():
    """反例：带空位的首行是题目（"填一填：（ ）"），不能被当成卷名吃掉。"""
    lines = ["填一填：（  ）", "1. 甲（  ）"]
    r = extract(lines)
    assert len(qs(r)) == 2, [x["text"] for x in qs(r)]
    assert not r["title"], f"带空位的行被当卷名: {r['title']}"
t("带空位的首行仍是题目（反例）", short_first_line_with_blank_stays)


def margin_strip_never_enters_body_text():
    """装订栏（竖排"学校/班级/姓名/学号"、"弥/封/线"）必须在【合并成行之前】被摘掉。

    真实卷：综合实践单元.pdf 841×653 横版两张 A4，左右各一条装订栏。
    这些竖排单字和正文同一水平线，一旦进了 group_lines 就变成
    「1. 学号： 线 小朋友们，准备好…」「…后面是（ 封」——用户说的"排版变形"根子在这。
    """
    from app.extractor.lines import drop_margin_items
    items = [
        {"text": "学号：", "x": 10, "y": 157, "w": 13, "h": 13},
        {"text": "线", "x": 27, "y": 145, "w": 9, "h": 9},
        {"text": "弥", "x": 26, "y": 426, "w": 9, "h": 11},
        {"text": "密封线内不要答题", "x": 800, "y": 300, "w": 30, "h": 90},
        {"text": "综合实践", "x": 800, "y": 140, "w": 34, "h": 92},      # 右侧栏色块
        {"text": "1. 小朋友们在操场上辨认方向，请帮他们补全记录单。",
         "x": 64, "y": 315, "w": 287, "h": 14},
    ]
    keep, dropped = drop_margin_items(items, 841.0)
    assert [d["text"] for d in dropped] == ["学号：", "线", "弥", "密封线内不要答题", "综合实践"], \
        f"装订栏没被清干净/清错：{[(d['x'], d['text']) for d in dropped]}"
    assert len(keep) == 1 and keep[0]["text"].startswith("1. 小朋友"), keep


def margin_filter_must_not_eat_body_line_ends():
    """反例：贴边但属于正文的行尾碎片不能丢。

    横版卷左半正文就从 x≈45 起笔。第一版用"框左边 ≤45"判贴边，
    于是把题干里短到两三个字的行尾（"）。"）也当成装订栏吃掉，
    用户看到的是"…一端指(  ）"读不通——比混进装订栏更糟。
    现在要求【整个框】都在页边带里。
    """
    from app.extractor.lines import drop_margin_items
    body = [{"text": "）。", "x": 40, "y": 240, "w": 26, "h": 12},
            {"text": "）；", "x": 30, "y": 260, "w": 18, "h": 12}]
    keep, dropped = drop_margin_items(body, 841.0)
    assert not dropped, f"正文行尾被当装订栏吃了：{[(d['x'], d['text']) for d in dropped]}"
    assert len(keep) == 2
    strip = [{"text": "学校：", "x": 8, "y": 470, "w": 22, "h": 12}]
    _k, dr = drop_margin_items(strip, 841.0)
    assert len(dr) == 1, "真装订栏反而没抓到"


t("装订栏不许混进题干", margin_strip_never_enters_body_text)
t("贴边正文行尾不许被当装订栏（反例）", margin_filter_must_not_eat_body_line_ends)


def broken_brackets_get_closed():
    """OCR 读丢半个括号的填空必须补回来 —— 括号不配对的题【做不了】。

    真实卷：综合实践单元.pdf 一、填空第 1、2 题，原文"一端指（ ），一端指（ ）。"
    OCR 只给到"…一端指 ),一端指("。
    """
    from app.extractor.rules import repair_blanks
    t1, n1 = repair_blanks("1.指南针是我国古代四大发明之一，它的特点是一端指 ),一端指(")
    assert n1 >= 1 and t1.count("（") + t1.count("(") == t1.count("）") + t1.count(")"), \
        f"没补配对：{t1} / {n1}"
    t2, n2 = repair_blanks("2.傍晚，爸爸欣赏落日时，他的前面是（       )，后面是（")
    assert n2 == 1 and t2.rstrip().endswith("）"), f"行尾括号没补：{t2}"
    assert t2.count("（") + t2.count("(") == t2.count("）") + t2.count(")")


def broken_bracket_repair_leaves_real_text_alone():
    """反例：选项标号、序号、已配对的空位、算式冒号，一个都不许改。"""
    from app.extractor.rules import repair_blanks
    for s in ["A）对 B）错", "（1）小明今年8岁，（2）爸爸今年（ ）岁。",
              "选择题：4×7 读作(    )", "3:4=（ ）：12",
              "5.同学们将面向（       )站立。", "一、填空。(每空1分,共16 分)"]:
        out, n = repair_blanks(s)
        assert n == 0 and out == s, f"误伤正文：{s!r} → {out!r}（补了 {n} 处）"


t("读残的填空括号要补全", broken_brackets_get_closed)
t("补括号不许误伤序号/选项/已配对空位（反例）", broken_bracket_repair_leaves_real_text_alone)


def unbalanced_paren_after_repair_is_flagged_not_silently_showed():
    """补不回来的括号（缺在句子中间，位置猜不出来）必须标"待人工校对"。

    真实卷：综合实践单元.pdf 一、填空第 2 题
      "…他的前面是（ ），后面是（ 夜晚，爸爸面向北极星时…"
    第二个空位缺的"）；"在句子中间，硬补就是编造题干。
    标出来让校对页挂角标，比悄悄印一张读不通的卷子好。
    """
    r = extract(["一、填空。",
                 "2.傍晚，爸爸欣赏落日时，他的前面是（ ），后面是（ 夜晚",
                 "，他的后面是（ ）。", "3.第三题的题干文字。"])
    q = [x for x in qs(r) if "爸爸欣赏落日" in x["text"]]
    assert q, [x["text"] for x in qs(r)]
    assert q[0]["needs_review"], f"括号不配对却没标待校对：{q[0]['text']}"
    assert "括号" in (q[0].get("review_note") or ""), q[0].get("review_note")
    # 反例：配好对的题不许被这条拖累（题号会被剥掉，所以按 q_no 找）
    ok = [x for x in qs(r) if x.get("q_no") == 3]
    assert ok, [x.get("q_no") for x in qs(r)]
    assert not ok[0].get("review_note"), ok[0]


t("补不回的括号要标待校对（含反例）", unbalanced_paren_after_repair_is_flagged_not_silently_showed)


def wiring_margin_filter_actually_runs_on_a_page():
    """接线检查：装订栏过滤必须真的挂在 `annotated_lines_from_pdf` 里。

    变异闸门打坏调用点（`items, margin = items, []`）时，上面那条直接调函数的
    单元测试【照样全绿】—— 因为它测的是函数会什么，不是"有没有人用它"。
    这条走完整链路：造一张带竖排装订栏的 PDF → 读行 → 断言正文里没有"学号/姓名"。
    """
    import os
    import tempfile
    import pymupdf
    from app.extractor.lines import annotated_lines_from_pdf
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "装订栏卷.pdf")
        doc = pymupdf.open()
        page = doc.new_page(width=841, height=653)
        page.insert_text((68, 60), "综合实践达标练习", fontsize=14, fontname="china-s")
        # 装订栏：竖排词，其中"学号："故意和正文同一基线 ——
        # 不同基线的话过滤关掉也只是多出行，测不出"混进题干"这个真症状。
        for w, wy in zip(["学校：", "班级：", "姓名：", "学号："], [140, 162, 184, 219]):
            page.insert_text((10, wy), w, fontsize=11, fontname="china-s")
        page.insert_text((64, 197), "一、填空。", fontsize=11, fontname="china-s")
        page.insert_text((64, 219), "1. 小朋友们在操场上辨认方向。", fontsize=11, fontname="china-s")
        doc.save(path)
        doc.close()
        r = annotated_lines_from_pdf(path)
        assert not any(("学号" in l or "姓名" in l or "学校" in l or "班级" in l)
                       for l in r["lines"]), f"装订栏字还是混进了正文：{r['lines'][:8]}"
        assert any("小朋友们在操场上辨认方向" in l for l in r["lines"]), r["lines"][:8]
        assert sum(p.get("margin_dropped", 0) for p in r["pages"]) >= 2, \
            f"过滤没跑：{[p.get('margin_dropped') for p in r['pages']]}"


def wiring_bracket_repair_actually_runs_in_extract():
    """接线检查：补括号必须真的在 extract() 的成题路径上（同上，防"函数对、线没接"）。"""
    r = extract(["一、填空。", "1.傍晚，爸爸欣赏落日时，他的前面是（       )，后面是（"])
    q = qs(r)
    assert q, [x["text"] for x in q]
    t = q[0]["text"]
    assert t.count("（") + t.count("(") == t.count("）") + t.count(")"), f"没补：{t}"
    assert q[0].get("blanks_closed"), q[0]


print()
print("[题号单独成行]")


def bare_number_line_opens_a_question():
    """题号被 OCR 切成单独一行、题干在整张图底下 —— 这道题不能凭空消失。

    真实卷：第三单元练习题 第 4 天「动物聚会」第 3 题，"3" 在 y=450（图顶），
    题干"观察图片，提出两个能用6×2解决的问题。"在 y=570（图底）。
    不认这个"3"，整卷就少一道题（审计器报"断号：缺第 3 题"）。
    """
    lines = [
        "一、看图回答问题。",
        "1. 想一想，连一连。",
        "3×4  4×3  4个3  3个4",
        "2",
        "观察图片，提出两个能用6×2解决的问题。",
        "问题一：      问题二：",
        "3. [思维探究]一共有多少个？把你的思考方法在图上圈一圈。",
    ]
    q = qs(extract(lines))
    nos = [x.get("q_no") for x in q]
    assert nos == [1, 2, 3], f"题号序列断了（少一道题孩子就少做一道）：{nos}"
    assert q[1]["text"].startswith("观察图片"), q[1]["text"]


def bare_number_must_be_the_next_in_sequence():
    """反例：数字不接着上一题、连着排的空数字 —— 都不许开题。"""
    # ① "5" 不接在 1 后面（图里的孤立数字、连线项）→ 并进题干，不开新题
    q = qs(extract(["一、填空。", "1. 第一题的题干文字内容。", "5", "第二行正文内容。"]))
    assert [x.get("q_no") for x in q] == [1], f"图里的孤立数字被当成了题号：{q}"
    assert "5" in q[0]["text"], q[0]["text"]
    # ② 连着排的数字（统计图上的 1 2 3 刻度）→ 只开一道，不许切出三道空题
    q2 = qs(extract(["一、看图填空。", "1. 第一题的题干文字内容。", "2", "3", "4"]))
    assert [x.get("q_no") for x in q2] == [1, 2],         f"一串刻度数字被切成好几道空题：{[x.get('q_no') for x in q2]}"
    # ③ 大题开头就冒出一个数字（没有上一题可接）→ 不开
    q3 = qs(extract(["二、解决问题。", "3", "这一行才是真正的题干内容。"]))
    assert [x.get("q_no") for x in q3] == [None], f"没有上一题时凭空认了题号：{q3}"


def wiring_bare_number_actually_runs_in_extract():
    """接线检查：判据必须真的接在 extract() 的成题路径上（防"函数对、线没接"）。"""
    from app.extractor.rules import _bare_number_starts_question as f
    prev = {"text": "想一想，连一连。"}
    assert f("3", 2, prev, 2) == 3, "判据本身就没通过（那上面两条测的是空气）"
    assert f("3", 2, {"text": ""}, 2) is None, "上一题还没有题干时不该认"
    r = extract(["一、看图回答问题。", "1. 第一题的题干文字内容。", "2",
                 "第二题的题干在图底下。"])
    assert [x.get("q_no") for x in qs(r)] == [1, 2],         f"判据算得出 2、成题路径却没开这道题（线没接）：{[x.get('q_no') for x in qs(r)]}"


print()
print("[区间起点：题号在图顶上]")


def span_anchor_lifts_to_the_bare_number_row():
    """裁图区间的起点要抬到那一行【题号】上，否则整张图落进上一题的区间。"""
    from app.extractor.lines import spans_for_questions
    ann = [
        {"text": "1. 想一想，连一连。", "x": 60, "y": 319, "w": 128, "h": 12,
         "page": 1, "col": 0},
        {"text": "2", "x": 60, "y": 450, "w": 11, "h": 12, "page": 1, "col": 0},
        {"text": "观察图片，提出两个能用6×2解决的问题。", "x": 75, "y": 570,
         "w": 294, "h": 12, "page": 1, "col": 0},
    ]
    questions = [
        {"q_no": 1, "text": "想一想，连一连。", "source_lines": ["想一想，连一连。"]},
        {"q_no": 2, "text": "观察图片，提出两个能用6×2解决的问题。",
         "source_lines": ["观察图片，提出两个能用6×2解决的问题。"]},
    ]
    pages = [{"page": 1, "width_pt": 595, "height_pt": 842,
              "bands": [{"x0": 0.0, "x1": 595.0}]}]
    sp = {int(s["q_index"]): s for s in spans_for_questions(ann, questions, pages=pages)}
    assert abs(sp[1]["y0"] - 450) < 1, f"区间起点没抬到题号行：{sp[1]['y0']}"
    assert abs(sp[0]["y1"] - 450) < 1, f"上一题的区间下界没收到题号行：{sp[0]['y1']}"

    # 反例：那一行的数字和本题题号对不上 → 不许抬（否则区间会吞掉上一题的图）
    ann2 = [dict(ann[0]), {**ann[1], "text": "7"}, dict(ann[2])]
    sp2 = {int(s["q_index"]): s for s in spans_for_questions(ann2, questions, pages=pages)}
    assert abs(sp2[1]["y0"] - 570) < 1, f"数字对不上也把区间往上抬了：{sp2[1]['y0']}"


t("题号单独成行也要开一道题", bare_number_line_opens_a_question)
t("反例：不接号的数字不许开题", bare_number_must_be_the_next_in_sequence)
t("裸题号判据真的接在成题链路上", wiring_bare_number_actually_runs_in_extract)
t("区间起点抬到图顶上那行题号（含反例）", span_anchor_lifts_to_the_bare_number_row)

def header_guard_skips_numbered_lines():
    """带题号的行永远不是"卷首信息行"，哪怕句子里有"答案/得分"这些表头词。

    真实坑：合成夹具里"1. 看图填方向，把答案写在括号里。"被 HEADER_HINTS 的
    "答案"命中，而这条判据跑在【第一道带题号的题】之前（seen_numbered 还是 False），
    于是整道第 1 题被当表头丢掉 —— 孩子看到的就是卷子少一题。
    """
    from app.extractor.rules import _looks_like_header as hdr
    # 正对照：真的卷首信息行还是要认
    assert hdr("班级＿＿＿＿ 姓名＿＿＿＿ 得分＿＿＿＿"), "卷首信息行不认了，表头会混进题目"
    assert hdr("满分：100分  时间：60分钟"), "卷首信息行不认了"
    # 这条判据要挡的就是它
    assert not hdr("1. 看图填方向，把答案写在括号里。"), "带题号的行仍被当表头"
    q = qs(extract(["一、看图填空。", "1. 看图填方向，把答案写在括号里。",
                    "2. 第二题的题干文字内容。"]))
    assert [x.get("q_no") for x in q] == [1, 2], \
        f"第 1 题被当卷首信息行丢了：{[x.get('q_no') for x in q]}"


def subquestion_paren_markers_merge_into_their_question():
    """"1. …再完成练习。" 下面的（1）（2）是【小问】，不许各开一道题。

    真实卷：第三单元达标练习题A 第三大题 —— 旧行为切出"第 1 题、第 1 题、第 2 题、
    第 2 题"，卷面上凭空多出两道假题（审计器报"重号 2"）。
    """
    lines = ["三、分类积累词语。（15分）",
             "1. 先把本单元学习的词语补充完整，再完成练习。（12分）",
             "（1）以上词语都可以用来描写春天的景象。（2分）",
             "（2）选词填空：春天来了，满园的鲜花让人眼前一亮。（3分）",
             "2. 下面的词语中，分类最合理的是哪一组？（3分）"]
    q = qs(extract(lines))
    assert [x.get("q_no") for x in q] == [1, 2], \
        f"小问（1）（2）被当成新题，出现重号：{[x.get('q_no') for x in q]}"
    assert "以上词语都可以用来描写" in q[0]["text"], q[0]["text"]
    assert "选词填空" in q[0]["text"], q[0]["text"]

    # 反例：整段都用（1）（2）平排编号的卷，它们就是各一道题，不许并
    q2 = qs(extract(["二、选一选。（10分）",
                     "（1）下列词语中不属于同一类的是（  ）",
                     "（2）下面说法正确的是（  ）"]))
    assert [x.get("q_no") for x in q2] == [1, 2], \
        f"平排的（1）（2）被并成一道题了：{[x.get('q_no') for x in q2]}"


t("小问（1）（2）不许切成两道重号题（含反例）", subquestion_paren_markers_merge_into_their_question)

t("卷首信息行不许吃掉带题号的第一题", header_guard_skips_numbered_lines)
def ocr_temp_files_must_not_collide_across_runs():
    """同一份扫描卷连跑两遍（先出卷、再识别题型），OCR 的临时图不许撞名。

    真实故障（2026-10-19 用户在网页上点"开始出卷"→ 识别题型失败：HTTP 500）：
    固定名 `lines_p2.png` + MuPDF 的 `pix.save()` 会【先删再写】；上一遍收尾的
    `os.remove` 因为 OCR 还压着句柄而失败（异常被咽掉），文件留在那儿，
    第二遍删不掉 → FzErrorSystem: Permission denied → 整份卷 500。
    修法：临时名带 pid+随机后缀（撞不上）+ 用 Python 直接覆盖写（不先删）。
    """
    import shutil
    import pymupdf
    from app.extractor import lines as L
    from app.extractor import ocr as O

    out = os.path.join(ROOT, "var", "_ocr_collide")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    src = os.path.join(out, "纯扫描页.pdf")
    d = pymupdf.open()
    pg = d.new_page(width=595, height=200)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pg.get_pixmap(dpi=72))   # 只有像素、没有文字层
    pg.insert_image(pgm := pymupdf.Rect(0, 0, 595, 200), pixmap=pix)
    d.save(src)
    d.close()

    seen: list[str] = []
    held: list = []

    def fake_ocr(path: str):
        seen.append(os.path.basename(path))
        held.append(open(path, "rb"))        # 模拟 OCR 那边句柄还没放
        return [{"text": "1. 一、选择题", "x": 40, "y": 40, "w": 140, "h": 14, "conf": 0.9}]

    old = O.ocr_image
    try:
        O.ocr_image = fake_ocr
        r1 = L.annotated_lines_from_pdf(src, work_dir=os.path.join(out, "w1"), dpi=100)
        r2 = L.annotated_lines_from_pdf(src, work_dir=os.path.join(out, "w1"), dpi=100)
    finally:
        O.ocr_image = old
        for f in held:
            f.close()
        shutil.rmtree(out, ignore_errors=True)
    assert len(seen) == 2, f"两遍应该各渲染一次临时图：{seen}"
    assert len(set(seen)) == len(seen), f"临时图撞名（下一次就会去删一个被占用的文件）：{seen}"
    assert r2["lines"], "第二遍一行都没读到（说明这一页被静默跳过了）"
    assert not any(p["route"] in ("ocr-write-failed", "ocr-missing") for p in r2["pages"]), r2["pages"]


t("OCR 临时图唯一名：同一份卷跑两遍不许 500", ocr_temp_files_must_not_collide_across_runs)

t("装订栏过滤真的接在读页链路上", wiring_margin_filter_actually_runs_on_a_page)
t("补括号真的接在成题链路上", wiring_bracket_repair_actually_runs_in_extract)


def sub_questions_split_for_display_but_stay_one_question():
    """一道大题里的（1）（2）（3）要【分行分空作答】，但【不能拆成三道题】。

    用户拿真实卷问的："一个题目里面有三个小题，非得挤在一个框子里，怎么分别作答呢？"
    两头都要顾：拆成独立题会重排题号、丢分值（上一轮就是被这个搞出"重号假题"的）；
    完全不拆又看不清哪一空归哪一问。所以题号/分值/批改仍按一道题走，
    排版和作答按小问走 —— 这里测的是"小问怎么切"。
    """
    from app.extractor.rules import split_subqs

    t = ("(1)2只2只地数,数了(    )次,一共有(    )只蝴蝶。 "
         "(2)3只3只地数,数了(    )次,一共有(    )只蝴蝶。 "
         "(3)4只4只地数,数了(    )次,一共有(    )只蝴蝶。")
    subs = split_subqs(t)
    assert [s["no"] for s in subs] == [1, 2, 3], f"三问没切出来：{subs}"
    assert [s["blanks"] for s in subs] == [2, 2, 2], f"每问该有两个空：{subs}"
    assert sum(s["blanks"] for s in subs) == 6, "小问空位数要能对上做题页的 6 个输入框"

    # 反例①：填空的空位写作"（   ）"，没有数字 —— 绝不能当成小问号
    assert split_subqs("一年有（    ）个月，其中大月有（    ）个。") == [], \
        "把空位当成了小问号"
    # 反例②：只出现一次编号 → 不是一串小问
    assert split_subqs("（1）这一问后面再没有第二问。") == []
    # 反例③：已经填了数的括号（"3×4=（12）"）编号不从 1 起、也不递增
    assert split_subqs("算式 3×4=（12），5×6=（30）") == [], "把算式结果当成了小问号"
    # 反例④：编号跳号（1）、（3）—— 中间丢了（2），宁可整条不拆
    assert split_subqs("（1）第一问。（3）第三问。") == [], "跳号也照样拆，会把小问标错"
    # 反例⑤：光杆编号（内容在表格里，OCR 只回"（1）（2）（3）"）→ 拆出来是三行空白
    assert split_subqs("数一数。（1）（2）（3）") == [], "把没有正文的编号拆成三个空行"
    # 反例⑥：行内的普通数字（"第 1 组…第 2 组…"）—— 括号的【成对形状】才是小问号
    assert split_subqs("第 1 组有 5 个，第 2 组有 3 个，第 3 组有 7 个。") == [], \
        "括号可有可无时，量词数字被当成了小问号"

    # 引导语要留住：「看图填一填。（1）…（2）…」里的"看图填一填"不是小问，也不能丢
    lead = split_subqs("看图填一填。 （1）数是几个几？（2）一共有多少？")
    assert lead and lead[0].get("lead") == "看图填一填。", f"引导语丢了：{lead}"
    assert len(lead) == 2 and [x["no"] for x in lead] == [1, 2], lead


t("（1）（2）（3）小问切得出来也不误伤空位（含六个反例）",
  sub_questions_split_for_display_but_stay_one_question)


def long_blank_runs_count_as_blanks():
    """括号里【一整串空白】就是一个空位，不管几个空格。

    真卷实测（E:\\数学卷子\\第三单元练习题.pdf 第 1 页）：扫描 OCR 把空位读成
    "(      )" 六个空格，旧口径只认 1–4 个 → 卷面 33 个空位数出 3 个，
    做题页每道题只给一个输入框，孩子根本没法"分别作答"。
    """
    from app.extractor.rules import BLANK_RE

    real = "(1)2只2只地数,数了(      )次,一共有(      )只蝴蝶。"
    assert len(BLANK_RE.findall(real)) == 2, \
        f"真卷这一行的空位数不对：{len(BLANK_RE.findall(real))}（应为 2：两个 6 空格空位；(1) 是小问号不算）"
    assert len(BLANK_RE.findall("一年有（        ）个月，大月有（  ）个。")) == 2
    # OCR 常把一对括号读成"全角开 + 半角闭"的混配，只认成对写法就漏（真卷有 5 个）
    assert len(BLANK_RE.findall("数了（      )次,一共有(      ）只蝴蝶。")) == 2, \
        "混配括号的空位没数到"
    assert len(BLANK_RE.findall("算式：____________ ＝ ____________")) == 2
    # 反例①：括号里有内容 → 那是填了数的空/普通括号，不是空位
    assert len(BLANK_RE.findall("3×4=（12），5×6=（30）")) == 0, "把填了数的括号当成空位"
    # 反例②：括号里夹了字 → 不是空位
    assert len(BLANK_RE.findall("（ 见上图 ）不对，应该是（   ）")) == 1, "把带字的括号当成空位"
    # 反例③：一个下划线不是空位（卷面上的脚注线、破折号）
    assert len(BLANK_RE.findall("a_b")) == 0
t("括号里的长空格流要数成空位（含三个反例）", long_blank_runs_count_as_blanks)


def span_locates_the_number_glued_stem_row():
    """题号【粘在第一行行首】（"4.(1)一共有多少根胡萝卜?"）时，区间起点必须是这一行。

    真卷第 2 页实测：上一题的区间一路吃到 y=584.8，第 4 题的货架图和答题空
    整块落进第 3 题的裁框里 → 第 3 题的图混着别人的题，第 4 题一张图都没有。
    用户那句话就是这么来的："这题都对不上，怎么做啊"。
    """
    from app.extractor.lines import spans_for_questions
    ann = [
        {"text": "3.[自然科普]落叶腐(f)烂后会化作养分,促进植物生长。下面的树叶片数",
         "x": 41, "y": 407.0, "w": 480, "h": 19, "page": 2, "col": 0},
        {"text": "不能用2×4表示的是(       )。(填序号)",
         "x": 60, "y": 436.7, "w": 300, "h": 19, "page": 2, "col": 0},
        {"text": "CL            长长", "x": 60, "y": 482.9, "w": 400, "h": 18,
         "page": 2, "col": 0},
        {"text": "4.(1)一共有多少根胡萝卜?", "x": 41, "y": 519.5, "w": 210, "h": 19,
         "page": 2, "col": 0},
        {"text": "(2)5X2在图中表示什么意思？", "x": 60, "y": 584.8, "w": 220, "h": 19,
         "page": 2, "col": 0},
        {"text": "第三步提思维", "x": 41, "y": 701.9, "w": 100, "h": 19, "page": 2, "col": 0},
    ]
    questions = [
        {"q_no": 3, "text": "[自然科普]落叶腐(f)烂后会化作养分,促进植物生长。"
                           "下面的树叶片数 不能用2×4表示的是(       )。(填序号)",
         "source_lines": ["[自然科普]落叶腐(f)烂后会化作养分,促进植物生长。下面的树叶片数",
                          "不能用2×4表示的是(       )。(填序号)", "CL            长长"]},
        {"q_no": 4, "text": "(1)一共有多少根胡萝卜? (2)5X2在图中表示什么意思？",
         "source_lines": ["(1)一共有多少根胡萝卜?", "(2)5X2在图中表示什么意思？"]},
    ]
    pages = [{"page": 2, "width_pt": 595, "height_pt": 907,
              "bands": [{"x0": 0.0, "x1": 595.0}]}]
    sp = {int(s["q_index"]): s for s in spans_for_questions(ann, questions, pages=pages)}
    assert abs(sp[1]["y0"] - 519.5) < 1, \
        f"第 4 题的区间没从粘着题号的那一行开始：{sp[1]['y0']}（图会整个给上一题）"
    assert abs(sp[0]["y1"] - 519.5) < 1, \
        f"第 3 题的区间下界没收到第 4 题起手行：{sp[0]['y1']}"

    # 反例：行首的数字【不是本题题号】→ 不许拿这一行当起点（否则区间会乱吞）
    ann2 = [dict(x) for x in ann]
    ann2[3] = dict(ann[3], text="9.(1)一共有多少根胡萝卜?")
    sp2 = {int(s["q_index"]): s for s in spans_for_questions(ann2, questions, pages=pages)}
    assert abs(sp2[1]["y0"] - 584.8) < 1, \
        f"行首数字对不上也把区间往上抬了：{sp2[1]['y0']}"
t("题号粘在题干行首时，区间起点要落在这一行（含反例）",
  span_locates_the_number_glued_stem_row)


def stage_banner_is_furniture_not_a_figure():
    """教辅的【栏目横幅】（"第二步 练变式"）是页面家具，不许被当成配图裁下来。

    真卷实测（第三单元练习题 第 3 页第 1 题）：整块橙底反白的"第二步练变式"
    被裁成一张"配图"挂在题目下面，卷子上就是一张和题目无关的栏目名。
    """
    from app.extractor.rules import is_furniture_text
    assert is_furniture_text("第二步练变式"), "栏目横幅没当家具（会被裁成配图）"
    assert is_furniture_text("第三步 提思维")
    assert is_furniture_text("知识演练场")
    # 反例：题干里出现同一个关键词，不算横幅
    assert not is_furniture_text("3.【能力提升】看图列式，图中的圆点有几个？"), \
        "带题号的题干被当横幅抹掉了"
    assert not is_furniture_text("第一步，请把 3 个 4 改写成乘法算式，并读出算式。"), \
        "长句子被当横幅抹掉了"
t("教辅栏目横幅是家具不是配图（含反例）", stage_banner_is_furniture_not_a_figure)


print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
