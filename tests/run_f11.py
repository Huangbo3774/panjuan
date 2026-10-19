"""PRD F11 度量：题型/切分正确率（真实材料，行缓存来自 tests/dump_lines.py --dump）。

⚠️ 度量的尺【不能复用产品的尺】。这里"应有题号"用的是本脚本自己写的正则
   （NUMBERED_RE），而不是 app.extractor.rules.Q_NUM_RE；否则实现里漏掉的形态
   在尺上也会一起漏掉，等于拿实现给自己打分（本项目已吃过「尺文同源」的亏）。
   两个尺的口径差异会体现在"仅尺看到/仅实现看到"的行上，脚本会逐条列出来。

指标：
  · 题号召回率 = 实现切成独立题目的编号行 / 尺认定的编号行
  · 假题率     = 实现切出的、尺不认为是编号行、且没有正文的题 / 实现切出的题
  · 需人工校对比例（PRD：置信度 <0.7 标 needs_review）
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.extractor.rules import extract, flatten_questions          # noqa: E402

CACHE = os.path.join(ROOT, "data", "ocr_lines.json")   # 不能放 var/：服务启动会清空 var/
OUT = os.path.join(ROOT, "tests", "f11-report.json")

# 独立实现的一把尺：行首「数字 + 顿号/句点」后面还有内容才算一道题的开头
NUMBERED_RE = re.compile(r"^\d{1,3}\s*[、．.]\s*\S")
# 扫描 App 的页眉页脚噪声（同样独立写一遍，不复用实现里的表）
JUNK_RE = re.compile(r"(夸克|极速扫描|扫描王|拍照秒批|视频讲解|讲解|天天练|年级上?下?册|BS版|配北师版"
                     r"|第\s*\d+\s*页|共\s*\d+\s*页|答案\s*P)")
# 教辅书的栏目行：不是题目
STAGE_RE = re.compile(r"^(第[一二三四五六七八九十]步|知识演练场|智慧加油站|基础过关|能力提升|拓展延伸)")


def ruler_numbered(lines: list[str]) -> list[str]:
    out = []
    for l in lines:
        s = l.strip()
        if not s or JUNK_RE.search(s) or STAGE_RE.match(s):
            continue
        if NUMBERED_RE.match(s):
            out.append(s)
    return out


# 实现会把题号从题干里剥掉（"1.一共有(" → 题干"一共有("），所以比对要在【去号之后的正文】上做。
# ⚠️ 这条归一化本身也要防"假尺"：若两把尺都比全行，实现剥了号就永远命中不了——
#    第一版就是这么量出 0% 召回的（尺坏，不是产品坏）。
AFTER_NUM_RE = re.compile(r"^\d{1,3}\s*[、．.]\s*")


def after_num(s: str) -> str:
    return AFTER_NUM_RE.sub("", s.strip()).strip()


def main() -> int:
    if not os.path.exists(CACHE):
        print("没有行缓存，先跑: py -3.11 tests/dump_lines.py --dump")
        return 2
    data = json.load(open(CACHE, encoding="utf-8"))
    rows, tot_exp, tot_hit, tot_strict, tot_q, tot_frag = [], 0, 0, 0, 0, 0
    for key, lines in data.items():
        exp = ruler_numbered(lines)
        res = extract(lines, title=key)
        qs = flatten_questions(res)
        stems = {after_num((q.get("source_lines") or [""])[0]) for q in qs}

        def counted(src: str, prefix_ok: bool = True) -> bool:
            """整行命中；prefix_ok 时才允许"实现把这行拆成多题"的前缀口径。
            两种口径都报：只报前缀口径会把"短题干恰好是长句前缀"也算命中（虚高）。"""
            a = after_num(src)
            if a in stems:
                return True
            if not prefix_ok:
                return False
            return any(len(s) >= 4 and a.startswith(s) for s in stems)

        hit = [l for l in exp if counted(l)]
        strict = [l for l in exp if counted(l, prefix_ok=False)]
        miss = [l for l in exp if not counted(l)]
        frags = [q for q in qs if len(after_num(q["text"])) < 4]
        unflagged = [q for q in frags if not q.get("needs_review")]
        numbered = [q for q in qs if q["q_no"] is not None]
        review = [q for q in qs if q.get("needs_review")]
        types: dict[str, int] = {}
        for q in qs:
            types[q["qtype"]] = types.get(q["qtype"], 0) + 1
        tot_exp += len(exp); tot_hit += len(hit); tot_q += len(qs)
        tot_strict += len(strict); tot_frag += len(frags)
        rows.append({"file": key, "lines": len(lines), "ruler_numbered": len(exp),
                     "hit": len(hit), "hit_strict": len(strict),
                     "recall": round(len(hit) / len(exp), 3) if exp else 1.0,
                     "recall_strict": round(len(strict) / len(exp), 3) if exp else 1.0,
                     "questions": len(qs), "numbered": len(numbered),
                     "fragments": len(frags),
                     "needs_review": len(review), "types": types,
                     "miss_examples": miss[:4]})
        print(f"【{key}】尺认定编号行 {len(exp)} → 切成独立题 {len(hit)}"
              f"（召回 {round(len(hit)/len(exp)*100, 1) if exp else 100}%，"
              f"严格口径 {round(len(strict)/len(exp)*100, 1) if exp else 100}%）"
              f"  实出题 {len(qs)}  碎片 {len(frags)}  需校对 {len(review)}  题型 {types}")
        for m in miss[:4]:
            print("     漏：", m[:64])
        if unflagged:
            print(f"     ⚠️ 碎片题未标 needs_review {len(unflagged)} 条：{[x['text'][:12] for x in unflagged]}")

    recall = tot_hit / tot_exp if tot_exp else 1.0
    strict_recall = tot_strict / tot_exp if tot_exp else 1.0
    frag_rate = tot_frag / tot_q if tot_q else 0.0
    print(f"\n合计：编号行 {tot_exp}  命中 {tot_hit}（严格 {tot_strict}）"
          f"  题号召回率 {recall*100:.1f}%（严格 {strict_recall*100:.1f}%）")
    print(f"      切出题目 {tot_q}  其中无正文碎片 {tot_frag}（{frag_rate*100:.1f}%，全部标 needs_review）")
    print(f"      需人工校对 {sum(r['needs_review'] for r in rows)}"
          f"（{sum(r['needs_review'] for r in rows)/tot_q*100:.1f}%，PRD F11 允许人工校对）")
    verdict = "PASS" if strict_recall >= 0.8 else "FAIL"
    print(f"PRD F11（题号召回 ≥80%，取【严格口径】）→ {verdict}")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"recall": round(recall, 4), "recall_strict": round(strict_recall, 4),
                   "fragment_rate": round(frag_rate, 4), "rows": rows},
                  fh, ensure_ascii=False, indent=2)
    print("报告：", OUT)
    return 0 if strict_recall >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
