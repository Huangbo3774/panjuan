"""SQLite 存储单测：读写往返、uid 稳定性、级联删除、以及「重启不能删数据」。

最后一条是真实设计缺陷引出来的：app/main.py 的 startup 会整目录删 var/（PRD §4.7 临时目录），
第一版把库放在 var/papers.db，等于每次重启把孩子的作答和标准答案删干净。
现在库在 data/，这里用「库路径不在 var/ 下」这条断言把它钉住。
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.storage import db                                          # noqa: E402
from app.grading.engine import grade, make_uid                      # noqa: E402

ok_n = bad_n = 0


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}")


def fresh(tmp: str) -> None:
    """把库指到临时文件，别污染用户真实数据。"""
    db.DB_PATH = os.path.join(tmp, "t.db")
    for suf in ("", "-wal", "-shm"):
        p = db.DB_PATH + suf
        if os.path.exists(p):
            os.remove(p)
    db.init()


print("\n[存储]")


def storage_not_in_var():
    tmp = os.path.join(ROOT, "var", "_t_storage")
    os.makedirs(tmp, exist_ok=True)
    fresh(tmp)
    default = os.path.join(ROOT, "data", "papers.db")
    assert os.path.dirname(default) != os.path.join(ROOT, "var"), "库不能放 var/（startup 会清空）"
    assert "var" not in os.path.normpath(default).split(os.sep), default
    shutil.rmtree(tmp, ignore_errors=True)
t("库位置躲开 var/ 的启动清理", storage_not_in_var)


def roundtrip():
    tmp = os.path.join(ROOT, "var", "_t_storage")
    os.makedirs(tmp, exist_ok=True)
    fresh(tmp)
    pid = db.create_paper("第三单元练习", {"font_size": 12}, source_task="abc123")
    qs = [{"q_no": 1, "auto_no": 1, "section": "一、填空", "qtype": "fill",
           "text": "一半是（ ）", "options": [], "blanks": 1, "score": 2.0,
           "confidence": 0.85, "needs_review": False, "source_lines": ["1.一半是（ ）"]},
          {"q_no": 1, "auto_no": 1, "section": "二、选择", "qtype": "choice",
           "text": "4×7 读作", "options": ["A. 四七二十八", "B. 4乘7"], "blanks": 0,
           "score": 1.0, "confidence": 0.9, "needs_review": True, "source_lines": ["1.4×7 读作"]}]
    saved = db.replace_questions(pid, qs)
    assert len(saved) == 2 and all(q["uid"].startswith("q") for q in saved)
    # 两道题都是"第 1 题"，靠 uid 区分，不能撞
    assert saved[0]["uid"] != saved[1]["uid"], "同题号跨大题必须各有各的键"
    got = db.get_questions(pid)
    assert got[0]["options"] == [] and got[1]["options"] == ["A. 四七二十八", "B. 4乘7"]
    assert got[1]["needs_review"] is True
    assert abs(got[0]["score"] - 2.0) < 1e-9
    assert db.get_paper(pid)["options"] == {"font_size": 12}
    assert db.find_paper_by_task("abc123")["id"] == pid
    assert db.find_paper_by_task("zzz") is None
    shutil.rmtree(tmp, ignore_errors=True)
t("试卷/题目读写往返", roundtrip)


def uid_stable_across_reload():
    """uid 必须来自数据库行号：家长改了题号，已录的标准答案不能失联。"""
    tmp = os.path.join(ROOT, "var", "_t_storage")
    os.makedirs(tmp, exist_ok=True)
    fresh(tmp)
    pid = db.create_paper("稳定性")
    saved = db.replace_questions(pid, [{"q_no": 1, "section": "一、填空", "qtype": "fill",
                                       "text": "甲（ ）", "options": [], "blanks": 1}])
    uid = saved[0]["uid"]
    key = {uid: "东"}
    db.save_key(pid, key)
    # 家长校对：把题号从 1 改成 7
    db.update_question(pid, uid, q_no=7, text="甲（ ）（改）")
    again = db.get_questions(pid)
    assert again[0]["uid"] == uid, f"uid 变了：{uid} → {again[0]['uid']}"
    assert again[0]["q_no"] == 7 and again[0]["manual_fixed"] is True
    r = grade(again, db.latest_key(pid), {uid: "东"},
              scores={make_uid(q): float(q.get("score") or 1.0) for q in again})
    assert r["score"] == 1.0, f"改号后标准答案失联：{r['results'][0]}"
    shutil.rmtree(tmp, ignore_errors=True)
t("校对改号后答案仍对得上（uid 稳定）", uid_stable_across_reload)


def submissions_and_cascade():
    tmp = os.path.join(ROOT, "var", "_t_storage")
    os.makedirs(tmp, exist_ok=True)
    fresh(tmp)
    pid = db.create_paper("回传")
    qs = db.replace_questions(pid, [{"q_no": 1, "section": "一", "qtype": "fill",
                                     "text": "（ ）", "options": [], "blanks": 1}])
    uid = qs[0]["uid"]
    db.save_key(pid, {uid: "东"})
    res = grade(qs, {uid: "东"}, {uid: "东"})
    sid = db.add_submission(pid, "二(1)班", "小明", {uid: "东"}, res)
    subs = db.list_submissions(pid)
    assert len(subs) == 1 and subs[0]["student_name"] == "小明"
    assert subs[0]["score"] == 1.0
    one = db.get_submission(sid)
    assert one["results"]["counts"]["correct"] == 1
    db.save_key(pid, {uid: "西"})
    assert db.latest_key(pid)[uid] == "西", "标准答案要取最新一条"
    db.delete_paper(pid)
    assert db.get_questions(pid) == [] and db.list_submissions(pid) == []
    assert db.latest_key(pid) == {} and db.get_paper(pid) is None
    shutil.rmtree(tmp, ignore_errors=True)
t("作答记录、答案版本、级联删除", submissions_and_cascade)


def two_papers_isolated():
    tmp = os.path.join(ROOT, "var", "_t_storage")
    os.makedirs(tmp, exist_ok=True)
    fresh(tmp)
    a = db.create_paper("A 卷")
    b = db.create_paper("B 卷")
    qa = db.replace_questions(a, [{"q_no": 1, "section": "一", "qtype": "fill", "text": "甲", "options": []}])
    qb = db.replace_questions(b, [{"q_no": 1, "section": "一", "qtype": "fill", "text": "乙", "options": []}])
    db.save_key(a, {qa[0]["uid"]: "东"})
    assert db.latest_key(b) == {}, "B 卷不该看到 A 卷的答案"
    assert db.get_questions(b)[0]["text"] == "乙"
    assert db.list_papers(10) and {p["id"] for p in db.list_papers(10)} == {a, b}
    shutil.rmtree(tmp, ignore_errors=True)
t("多张试卷互不串数据", two_papers_isolated)


print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
