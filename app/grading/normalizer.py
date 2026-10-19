"""答案归一化（PRD §5.3 填空容错批改的实现）。

设计口径——「宁可少判对，不可判错为对」：
  · 只有归一化后**完全相等**或**数值相等**才判 correct；
  · 拿不准的（例如问答题、需要语义理解的）一律交给 engine 标 pending，由人工确认；
  · 每一步归一化都留下"改了什么"的痕迹（trace），批改报告能还原判定依据，
    避免"不知道它为什么判错"这种没法校对的结果。

为什么不接大模型：PRD 明确"纯规则比对，无 AI"；而且本项目承诺本地运行不联网，
把批改挂在网上等于把孩子的作业数据发出去。
"""
from __future__ import annotations

import re
import unicodedata

# 判断题的同义写法 → 统一成 "T"/"F"
JUDGE_TRUE = {"对", "√", "✓", "T", "true", "yes", "y", "正确", "正确√", "是", "∨"}
JUDGE_FALSE = {"错", "×", "✗", "X", "F", "false", "no", "n", "错误", "否", "⊨", "ㄨ"}

# 中文数字（二年级够用：0~100，含"几十几"）
CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "两": 2}

# 多答案分隔符：一个空可以填多种写法时，标准答案里用 | 或 ； 隔开。
# ⚠️ 故意不用 "/" 和 "、"：它们本身就是答案内容（分数 1/2、并列数字 3、4）。
ALT_SPLIT_RE = re.compile(r"[|｜；;]")

# 首尾要剥掉的标点（中英文都列上：OCR/手写录入两种来源都会带）
EDGE_PUNCT = "。．.！!？?，,、；;：:～~＊*“”\"'‘’（）()[]【】〔〕<>《》 \t\r\n　"

# 乘号写法统一：二年级卷里 ×、x、*、∙ 混用是常态
# ⚠️ 半角 * 必须单独列进去：∗(U+2217)/＊(全角) 都不等于 ASCII 的 *，
#    少写一个的话 "3*4" 永远归一化不成 "3×4"（本用例实测命中）。
MULT_RE = re.compile(r"[x×✕✖∗*＊·∙⋅]")

# 数值形态：整数 / 小数 / 分数 / 百分数（允许前后有单位字样，由 _num_value 处理）
NUM_RE = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:/\d+(?:\.\d+)?)?$")
PERCENT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[%％]$")


CN_FRAC_RE = re.compile(r"^([一二三四五六七八九十百零两]+)分之([一二三四五六七八九十百零两]+)$")
CN_PERCENT_RE = re.compile(r"^百分之([一二三四五六七八九十百零两]+)$")


def _cn_number(s: str) -> float | None:
    """把「三十」「二十五」「七」「两」这类中文数字读成阿拉伯数字。

    只做到 100 以内：二年级答案里出现的中文数字不会更大，超出就返回 None（当作不等价），
    而不是硬凑一个可能错的值。
    """
    if not s or any(ch not in CN_DIGITS and ch not in "十百" for ch in s):
        return None
    total, cur = 0, 0
    if s.startswith("百") and len(s) > 1:
        return None
    for ch in s:
        if ch in CN_DIGITS:
            cur = CN_DIGITS[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        else:
            return None
    return float(total + cur)


def _num_value(s: str) -> float | None:
    """能读成一个数就返回数值，否则 None。支持 小数 / 分数 / 百分数 / 中文数字。"""
    t = (s or "").strip()
    if not t:
        return None
    m = PERCENT_RE.match(t)
    if m:
        return float(m.group(1)) / 100.0
    # 中文分数/百分数：孩子写「二分之一」而标准答案是 1/2，这是 F14 该容的下。
    # ⚠️ 「A 分之 B」= B/A（分母在前），别写反。
    m = CN_FRAC_RE.match(t)
    if m:
        den, num = _cn_number(m.group(1)), _cn_number(m.group(2))
        return num / den if den and num is not None else None
    m = CN_PERCENT_RE.match(t)
    if m:
        v = _cn_number(m.group(1))
        return v / 100.0 if v is not None else None
    if "/" in t:
        parts = t.split("/")
        if len(parts) == 2:
            try:
                d = float(parts[1])
                return float(parts[0]) / d if d else None
            except ValueError:
                return None
        return None
    if NUM_RE.match(t):
        try:
            return float(t)
        except ValueError:
            return None
    return _cn_number(t)


def norm_answer(text: str) -> tuple[str, list[str]]:
    """归一化一个答案字符串。返回 (归一化结果, 做了哪些改动)。

    步骤（顺序有意义）：
      1. Unicode NFKC：全角→半角、全角空格→半角、①→1（圆圈答案是选择题常见写法）
      2. 去首尾标点与空白
      3. 英文统一小写
      4. 乘号统一成 ×
      5. 内部连续空白压成一个空格
      6. 数字形态：分数/小数/百分数统一成十进制，中文数字转阿拉伯
    """
    trace: list[str] = []
    s = str(text or "")
    nfkc = unicodedata.normalize("NFKC", s)
    if nfkc != s:
        trace.append(f"NFKC: {s!r}→{nfkc!r}")
    s = nfkc
    stripped = s.strip(EDGE_PUNCT).strip()
    if stripped != s:
        trace.append(f"去标点/空白: {s!r}→{stripped!r}")
    s = stripped
    low = s.lower()
    if low != s:
        trace.append(f"小写: {s!r}→{low!r}")
    s = low
    if MULT_RE.search(s):
        new = MULT_RE.sub("×", s)
        if new != s:
            trace.append(f"乘号统一: {s!r}→{new!r}")
        s = new
    spaced = re.sub(r"\s+", " ", s).strip()
    if spaced != s:
        trace.append(f"空白归一: {s!r}→{spaced!r}")
    s = spaced
    v = _num_value(s)
    if v is not None:
        canon = _fmt_num(v)
        if canon != s:
            trace.append(f"数值等价: {s!r}→{canon!r}")
            s = canon
    return s, trace


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(round(float(v), 6))


# 带单位的答案：「48个」「6 行」「24 元」。孩子写单位太常见了，
# 把它当成"不等于 48"会把对的判成错的——这是本产品最不能接受的错误方向。
# 只允许单位是【数字后面的 1~3 个非数字字符】，"3行8棵"这种含第二个数字的不提取，
# 免得它的 3 被拿去和别的答案比。
LEAD_NUM_RE = re.compile(r"^(-?(?:\d+(?:\.\d+)?|\.\d+)(?:/\d+(?:\.\d+)?)?)"
                         r"([^\d]{1,3})$")


def variants(text: str) -> list[str]:
    """一个答案的全部可比形式：归一化串 + 去空格串 + 数值 + 带单位时的数值部分。
    比对时任一相等即算命中，覆盖「3 行」vs「3行」、「B. 12」vs「b 12」这类。"""
    n, _ = norm_answer(text)
    out = [n, n.replace(" ", "")]
    v = _num_value(n)
    if v is not None:
        out.append(_fmt_num(v))
    else:
        m = LEAD_NUM_RE.match(n)
        if m:
            mv = _num_value(m.group(1))
            if mv is not None:
                out.append(_fmt_num(mv))
    return [x for x in dict.fromkeys(out) if x]


def alternatives(key_answer: str) -> list[str]:
    """标准答案里的多个可接受写法（用 | 或 ； 分隔）。"""
    return [p.strip() for p in ALT_SPLIT_RE.split(str(key_answer or "")) if p.strip()]


def judge_symbol(text: str) -> str | None:
    """把判断题作答映射成 "T"/"F"；认不出来返回 None（交人工）。"""
    n, _ = norm_answer(text)
    if not n:
        return None
    n2 = n.strip(EDGE_PUNCT).strip()
    for pool, tag in ((JUDGE_TRUE, "T"), (JUDGE_FALSE, "F")):
        if n2 in pool or n2.rstrip(".。") in pool:
            return tag
        if n2 in {w.lower() for w in pool}:
            return tag
    return None


def numbers_equal(a: str, b: str) -> bool:
    va, vb = _num_value(a), _num_value(b)
    return va is not None and vb is not None and abs(va - vb) < 1e-9
