"""V1.1 链路冒烟：上传 → 识别题型 → 录标准答案 → 提交作答 → 批改。

只验证 API 层能跑通并给出可核对的数字；PRD F12–F15 的正式验收在
tests/acceptance_v11.py（要等做题页和模式 B/C 导出做完）。

用法: py -3.11 tests/smoke_papers_api.py [样本名]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import urllib.request                                            # noqa: E402

PORT = 8779
BASE = f"http://127.0.0.1:{PORT}"
_PRIVATE = os.path.join(ROOT, "samples", "private")
_PUBLIC = os.path.join(ROOT, "samples", "public")
_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".docx")
S = _PRIVATE if (os.path.isdir(_PRIVATE) and
                 any(f.lower().endswith(_EXT) for f in os.listdir(_PRIVATE))) else _PUBLIC


def req(method, path, body=None, headers=None):
    r = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        r.add_header("Content-Type", "application/json")
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, data=body, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:300]}


def upload(files: list[tuple[str, bytes]]) -> dict:
    boundary = "----panjuansmoke"
    parts = []
    for name, data in files:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="files"; filename="{name}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        parts.append(data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    r = urllib.request.Request(BASE + "/api/tasks", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_task(tid: str, timeout=240) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, s = req("GET", f"/api/tasks/{tid}")
        if s.get("status") in ("done", "partial", "failed"):
            return s
        time.sleep(0.4)
    raise TimeoutError(f"任务 {tid} 超时")


def main(names: list[str]) -> int:
    if not os.path.isdir(S) or not os.listdir(S):
        print("没有样本，先跑 py -3.11 scripts/make_public_samples.py")
        return 2
    files = []
    for n in names or sorted(os.listdir(S))[:2]:
        p = os.path.join(S, n)
        if os.path.isfile(p) and os.path.splitext(n)[1].lower() in _EXT:
            files.append((n, open(p, "rb").read()))
    if not files:
        print("样本里没有可用文件"); return 2

    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    bad = 0
    try:
        for _ in range(40):
            st, h = req("GET", "/api/health")
            if st == 200:
                if h.get("pid") != proc.pid:
                    print(f"端口 {PORT} 上是别人起的服务（pid {h.get('pid')} ≠ {proc.pid}），"
                          f"测的是旧代码，先杀掉占用进程")
                    return 1
                break
            time.sleep(0.6)
        else:
            print("服务起不来"); return 1

        for name, data in files:
            print(f"\n=== {name} ===")
            t0 = time.time()
            r = upload([(name, data)])
            s = wait_task(r["task_id"])
            print(f"  出卷 {round(time.time()-t0, 1)}s 状态 {s['status']}")
            st, pr = req("POST", f"/api/papers/{s['task_id']}/parse")
            if st != 200:
                print(f"  ✗ 识别失败 {st} {pr}"); bad += 1; continue
            qs = pr["questions"]
            print(f"  识别：{len(qs)} 题（试卷号 {pr['paper_id']}）"
                  f" 需校对 {pr['needs_review']} 噪声 {pr['dropped_noise']}"
                  f" 大题 {len(pr['sections'])} OCR置信 {pr['ocr']['conf']}")
            for q in qs[:3]:
                print(f"     {q['uid']} {q['q_no']}. [{q['qtype']}] {q['text'][:40]}"
                      f"{' | ' + '/'.join(o[:10] for o in q['options'][:4]) if q['options'] else ''}")
            if not qs:
                print("  ✗ 一题都没切出来"); bad += 1; continue

            # 录标准答案：按题型给一个可核对的答案（这步模拟家长「自己做一遍另存为答案」）
            key = {}
            for q in qs:
                if q["qtype"] == "choice" and q["options"]:
                    key[q["uid"]] = q["options"][0][:1]
                elif q["qtype"] == "judge":
                    key[q["uid"]] = "√"
                elif q["qtype"] == "fill":
                    key[q["uid"]] = "东"
                else:
                    key[q["uid"]] = "参考答案文本"
            st, kr = req("POST", f"/api/papers/{pr['paper_id']}/key", {"answers": key})
            print(f"  标准答案：{'存成功 key_id=' + str(kr.get('key_id')) if st == 200 else f'✗ {st} {kr}'}")

            # 一半照抄答案、一半故意答错
            ans, wrong = {}, 0
            for i, q in enumerate(qs):
                if i % 2 == 0:
                    ans[q["uid"]] = key[q["uid"]]
                else:
                    ans[q["uid"]] = "显然不对的作答" if q["qtype"] not in ("judge",) else "×"
                    wrong += 1
            st, sub = req("POST", f"/api/papers/{pr['paper_id']}/submissions",
                          {"answers": ans, "class_name": "二(1)班", "student_name": "示例"})
            if st != 200:
                print(f"  ✗ 提交失败 {st} {sub}"); bad += 1; continue
            print(f"  批改：得分 {sub['score']}/{sub['total']}"
                  f"（待确认 {sub['pending_max']}）对 {sub['counts']['correct']} "
                  f"错 {sub['counts']['wrong']} 待确认 {sub['counts']['pending']}")
            st, g = req("GET", f"/api/papers/{pr['paper_id']}/grade")
            same = st == 200 and g.get("score") == sub["score"]
            print(f"  再取批改结果：{'一致' if same else f'✗ 不一致 {st} {g}'}")
            if not same:
                bad += 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("\n冒烟结果：", "通过" if not bad else f"{bad} 处异常")
    return 1 if bad else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(args))
