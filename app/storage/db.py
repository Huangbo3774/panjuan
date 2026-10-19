"""SQLite 存储（PRD §7.5）。

为什么用文件库而不是内存：在线作答要跨多次请求、也要跨重启——
孩子做了一半关掉浏览器，第二天还得接着做；老师的答案录一次要用很多遍。

隐私口径（PRD §6「本地运行、不上传」）：
  · 库文件落在 data/papers.db，data/ 已在 .gitignore 里，永远不会进仓库；
  · 真实学生姓名/班级属于未成年人数据，本模块不提供任何出网路径；
  · 提供 delete_paper() 给前端「删除这份试卷」，同时清掉工作目录。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

# 库文件【不能】放 var/：app/main.py 的 startup 会整目录清空 var/（PRD §4.7 临时目录），
# 放那里的话每次重启都把孩子的作答和标准答案删了。数据目录单独走 data/（同样 gitignore）。
# 路径唯一来源是 app/paths.py —— 打包成 exe 后数据必须落在可写且升级不被覆盖的位置。
from ..paths import APP_HOME as ROOT, DATA, DB_PATH
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY, title TEXT, subject TEXT,
  options TEXT, status TEXT, created_at TEXT,
  source_task TEXT, meta TEXT,
  published_at TEXT, source_pages TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, paper_id INTEGER, q_no INTEGER, auto_no INTEGER,
  section TEXT, qtype TEXT, text TEXT, options TEXT, blanks INTEGER DEFAULT 0,
  score REAL DEFAULT 1, confidence REAL, needs_review INTEGER DEFAULT 0,
  manual_fixed INTEGER DEFAULT 0, source_lines TEXT, ord INTEGER,
  images TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY, paper_id INTEGER,
  class_name TEXT, student_name TEXT,
  answers TEXT, score REAL, total REAL, results TEXT, graded_at TEXT
);
CREATE TABLE IF NOT EXISTS answer_keys (
  id INTEGER PRIMARY KEY, paper_id INTEGER,
  answers TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_questions_paper ON questions(paper_id);
CREATE INDEX IF NOT EXISTS ix_submissions_paper ON submissions(paper_id);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")        # 本机多人同时点也不会 locked
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init() -> None:
    with _lock:
        c = connect()
        try:
            c.executescript(SCHEMA)
            _migrate(c)
            c.commit()
        finally:
            c.close()


def _migrate(c: sqlite3.Connection) -> None:
    """老库补列。CREATE TABLE IF NOT EXISTS 对已存在的表不做任何事，
    所以 V1.1 之后新加的列必须在这里补，否则别人升级后第一次查询就 no such column。"""
    def cols(table: str) -> set[str]:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if "images" not in cols("questions"):
        c.execute("ALTER TABLE questions ADD COLUMN images TEXT DEFAULT '[]'")
    if "published_at" not in cols("papers"):
        c.execute("ALTER TABLE papers ADD COLUMN published_at TEXT")
    if "source_pages" not in cols("papers"):
        c.execute("ALTER TABLE papers ADD COLUMN source_pages TEXT DEFAULT '[]'")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------- papers ----------------

def create_paper(title: str, options: dict | None = None, status: str = "draft",
                 source_task: str = "", meta: dict | None = None) -> int:
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO papers(title, subject, options, status, created_at, source_task, meta)"
            " VALUES(?,?,?,?,?,?,?)",
            (title, (meta or {}).get("subject", ""), json.dumps(options or {}, ensure_ascii=False),
             status, _now(), source_task, json.dumps(meta or {}, ensure_ascii=False)))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def get_paper(pid: int) -> dict | None:
    c = connect()
    try:
        r = c.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        return _paper_row(r) if r else None
    finally:
        c.close()


def find_paper_by_task(tid: str) -> dict | None:
    c = connect()
    try:
        r = c.execute("SELECT * FROM papers WHERE source_task=? ORDER BY id DESC LIMIT 1",
                      (tid,)).fetchone()
        return _paper_row(r) if r else None
    finally:
        c.close()


def list_papers(limit: int = 50) -> list[dict]:
    c = connect()
    try:
        rows = c.execute("SELECT * FROM papers ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_paper_row(r) for r in rows]
    finally:
        c.close()


def _paper_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("options", "meta"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except json.JSONDecodeError:
            d[k] = {}
    return d


def update_paper(pid: int, **fields: Any) -> None:
    allowed = {"title", "subject", "status", "options", "meta", "published_at", "source_pages"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    for k in ("options", "meta", "source_pages"):
        if k in sets:
            sets[k] = json.dumps(sets[k], ensure_ascii=False)
    c = connect()
    try:
        c.execute(f"UPDATE papers SET {','.join(k + '=?' for k in sets)} WHERE id=?",
                  [*sets.values(), pid])
        c.commit()
    finally:
        c.close()


def delete_paper(pid: int) -> None:
    """级联删除：题目/答案/作答一起走，不留孤儿行。"""
    c = connect()
    try:
        for table in ("questions", "answer_keys", "submissions"):
            c.execute(f"DELETE FROM {table} WHERE paper_id=?", (pid,))
        c.execute("DELETE FROM papers WHERE id=?", (pid,))
        c.commit()
    finally:
        c.close()


# ---------------- questions ----------------

def replace_questions(pid: int, questions: list[dict]) -> list[dict]:
    """整批替换题目（重新识别或家长改完都走这里）。返回带 uid 的题目。"""
    c = connect()
    try:
        c.execute("DELETE FROM questions WHERE paper_id=?", (pid,))
        for i, q in enumerate(questions):
            c.execute(
                "INSERT INTO questions(paper_id,q_no,auto_no,section,qtype,text,options,"
                "blanks,score,confidence,needs_review,manual_fixed,source_lines,ord,images)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, q.get("q_no"), q.get("auto_no"), q.get("section", ""),
                 q.get("qtype", "unknown"), q.get("text", ""),
                 json.dumps(q.get("options") or [], ensure_ascii=False),
                 int(q.get("blanks") or 0), float(q.get("score", 1.0) or 1.0),
                 float(q.get("confidence", 0) or 0),
                 1 if q.get("needs_review") else 0, 1 if q.get("manual_fixed") else 0,
                 json.dumps(q.get("source_lines") or [], ensure_ascii=False), i,
                 json.dumps(q.get("images") or [], ensure_ascii=False)))
        c.execute("UPDATE questions SET auto_no=ord+1 WHERE paper_id=? AND auto_no IS NULL", (pid,))
        c.commit()
    finally:
        c.close()
    return get_questions(pid)


def add_question(pid: int, q: dict, after_uid: str | None = None) -> dict:
    """校对页「加一道题」。after_uid 给了就插在那题后面，否则追加到末尾。"""
    c = connect()
    try:
        rows = c.execute("SELECT id,ord FROM questions WHERE paper_id=? ORDER BY ord", (pid,)).fetchall()
        if after_uid:
            anchor = next((r["ord"] for r in rows if f"q{r['id']}" == str(after_uid)), None)
            if anchor is None:
                raise ValueError(f"找不到题目 {after_uid}")
            c.execute("UPDATE questions SET ord=ord+1 WHERE paper_id=? AND ord>?", (pid, anchor))
            new_ord = anchor + 1
        else:
            new_ord = len(rows)
        cur = c.execute(
            "INSERT INTO questions(paper_id,q_no,auto_no,section,qtype,text,options,"
            "blanks,score,confidence,needs_review,manual_fixed,source_lines,ord,images)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, q.get("q_no"), q.get("auto_no"), q.get("section", ""),
             q.get("qtype", "fill"), q.get("text", ""),
             json.dumps(q.get("options") or [], ensure_ascii=False),
             int(q.get("blanks") or 0), float(q.get("score", 1.0) or 1.0),
             1.0,                       # 人工新增的题 = 最高置信度，不该再标"需校对"
             0, 1,                      # manual_fixed=1
             json.dumps(q.get("source_lines") or []), new_ord,
             json.dumps(q.get("images") or [], ensure_ascii=False)))
        c.execute("UPDATE questions SET auto_no=ord+1 WHERE paper_id=?", (pid,))
        c.commit()
        nid = int(cur.lastrowid)
    finally:
        c.close()
    return next((x for x in get_questions(pid) if x["uid"] == f"q{nid}"), {"uid": f"q{nid}"})


def delete_question(pid: int, uid: str) -> int:
    """删题。返回删掉的行数（0 表示 uid 不属于这张卷——不能让他卷上误删）。
    删完把 ord/auto_no 重排一遍：留着空洞的话，题号和屏幕上的序号会对不上。"""
    c = connect()
    try:
        n = c.execute("DELETE FROM questions WHERE paper_id=? AND id=?",
                      (pid, _row_id(uid))).rowcount
        rows = c.execute("SELECT id FROM questions WHERE paper_id=? ORDER BY ord,id", (pid,)).fetchall()
        for i, r in enumerate(rows):
            c.execute("UPDATE questions SET ord=?, auto_no=? WHERE id=?", (i, i + 1, r["id"]))
        c.commit()
        return n
    finally:
        c.close()


def _row_id(uid: str) -> int:
    s = str(uid or "")
    if not s.startswith("q") or not s[1:].isdigit():
        raise ValueError(f"题目号不合法：{uid!r}")
    return int(s[1:])


def set_question_images(pid: int, uid: str, images: list[dict]) -> None:
    c = connect()
    try:
        c.execute("UPDATE questions SET images=?, manual_fixed=1 WHERE paper_id=? AND id=?",
                  (json.dumps(images or [], ensure_ascii=False), pid, _row_id(uid)))
        c.commit()
    finally:
        c.close()


def get_questions(pid: int) -> list[dict]:
    c = connect()
    try:
        rows = c.execute("SELECT * FROM questions WHERE paper_id=? ORDER BY ord", (pid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("options", "source_lines", "images"):
                try:
                    d[k] = json.loads(d.get(k) or "[]")
                except (json.JSONDecodeError, TypeError):
                    d[k] = []
            d["uid"] = f"q{d['id']}"           # 批改/答案/作答共用的稳定键
            d["needs_review"] = bool(d.get("needs_review"))
            d["manual_fixed"] = bool(d.get("manual_fixed"))
            d.pop("paper_id", None)
            out.append(d)
        return out
    finally:
        c.close()


def update_question(pid: int, uid: str, **fields: Any) -> None:
    """家长校对单题。改了内容就置 manual_fixed=1（PRD：可人工校对）。"""
    qid = int(str(uid).lstrip("q")) if str(uid).startswith("q") else None
    if qid is None:
        return
    allowed = {"q_no", "auto_no", "section", "qtype", "text", "options", "blanks",
               "score", "confidence", "needs_review", "images"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    for k in ("options", "images"):
        if k in sets:
            sets[k] = json.dumps(sets[k], ensure_ascii=False)
    if "needs_review" in sets:
        sets["needs_review"] = 1 if sets["needs_review"] else 0
    sets["manual_fixed"] = 1
    c = connect()
    try:
        c.execute(f"UPDATE questions SET {','.join(k + '=?' for k in sets)}"
                  " WHERE id=? AND paper_id=?", [*sets.values(), qid, pid])
        c.commit()
    finally:
        c.close()


# ---------------- answer keys ----------------

def save_key(pid: int, answers: dict) -> int:
    """保存标准答案（PRD §5.3 方式 2：家长自己做一遍→另存为标准答案）。"""
    c = connect()
    try:
        cur = c.execute("INSERT INTO answer_keys(paper_id, answers, created_at) VALUES(?,?,?)",
                        (pid, json.dumps(answers or {}, ensure_ascii=False), _now()))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def latest_key(pid: int) -> dict:
    c = connect()
    try:
        r = c.execute("SELECT answers FROM answer_keys WHERE paper_id=? ORDER BY id DESC LIMIT 1",
                      (pid,)).fetchone()
        try:
            return json.loads(r["answers"]) if r else {}
        except json.JSONDecodeError:
            return {}
    finally:
        c.close()


# ---------------- submissions ----------------

def add_submission(pid: int, class_name: str, student_name: str,
                   answers: dict, grade_result: dict) -> int:
    c = connect()
    try:
        cur = c.execute(
            "INSERT INTO submissions(paper_id,class_name,student_name,answers,score,total,"
            "results,graded_at) VALUES(?,?,?,?,?,?,?,?)",
            (pid, class_name or "", student_name or "",
             json.dumps(answers or {}, ensure_ascii=False),
             float(grade_result.get("score", 0)), float(grade_result.get("total", 0)),
             json.dumps(grade_result, ensure_ascii=False), _now()))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def list_submissions(pid: int) -> list[dict]:
    c = connect()
    try:
        rows = c.execute("SELECT id,class_name,student_name,answers,score,total,results,graded_at"
                         " FROM submissions WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("answers", "results"):
                try:
                    d[k] = json.loads(d.get(k) or "{}")
                except json.JSONDecodeError:
                    d[k] = {}
            out.append(d)
        return out
    finally:
        c.close()


def get_submission(sid: int) -> dict | None:
    c = connect()
    try:
        r = c.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("answers", "results"):
            try:
                d[k] = json.loads(d.get(k) or "{}")
            except json.JSONDecodeError:
                d[k] = {}
        return d
    finally:
        c.close()
