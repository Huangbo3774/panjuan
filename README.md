# 磐卷 PaperForge

[English](README.md) · **[中文](README.zh-CN.md)**

> **Whatever the teacher sends, print it as one clean A4.**
> 老师发什么，磐卷印什么——一张干净 A4。

Turn the PDFs, photos and Word files your kid's teacher dumps into the group chat into **one standard A4 exam paper PDF** — ready to print, or to be answered on screen, auto-graded, and sent back to the teacher as a PDF with the score on it.

![A phone photo of homework → a clean A4 paper produced by PaperForge](docs/img/compare-photo-to-a4.png)

## Why

It is 10pm on Saturday. The teacher posts three photos of a maths worksheet: *"needed by 9am tomorrow."* The print shop is closed. Your printer has been out of ink for a month. You are staring at a crooked, grey, unreadable photo.

Or: it is Sunday morning and there are seven parents queueing at the print shop, each holding a photo of the same worksheet.

**Kids are not short of exercises. They are short of one clean, standard, printable sheet of A4.**

## Before / After

| Before | After |
|---|---|
| Print shop closed at night and on weekends | A standard A4 paper in 1–2 seconds, any hour |
| Blurry, grey, crooked photos | Automatic clean-up: grey background removed, deskewed, cropped, enhanced |
| One PDF + two photos + a Word doc, stitched by hand | Drop them all in together, merged into one paper, zero layout work |
| Hundreds of dollars a year on printing and ink | Grayscale-first, ink-saver mode, adjustable font size, 2-up duplex |
| Re-do the homework photo loop to hand it in | (V1.1) answer on screen → auto-grade → export a graded PDF |

## Quick start

```powershell
# Windows — right-click, Run with PowerShell.
# Finds Python 3.11+, creates a venv, installs deps, opens your browser.
.\scripts\setup.ps1
```

```bash
# Any platform
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://127.0.0.1:8000/
```

Requires **Python 3.11+**. `setup.ps1` searches for 3.11+ explicitly rather than trusting whatever `python` resolves to on PATH.

## Privacy-first, and I mean it

Children's homework is minors' data. This tool:

- runs entirely on your own machine — no uploads, no accounts, no telemetry
- makes **zero external network requests**, including no CDN on the frontend
- keeps task data in memory only; restart clears everything
- ships its real-world test fixtures out of the repo (`samples/private/` is gitignored)

The code is MIT-licensed and auditable. That is the whole privacy policy.

## What it does today (measured, not promised)

| | Status |
|---|---|
| A · clean printable A4 paper | ✅ shipped (V1.0) |
| B · answer on screen | 🚧 V1.1 |
| C · auto-grade and send back | 🚧 V1.1 |

Verified against real teaching material with `py -3.11 tests/acceptance.py` — **11/11 acceptance cases pass**, and they pass both with real samples and with only the synthetic ones that ship in the repo (so a stranger who clones this gets the same result):

```
F01 phone photo → A4 in 1.1s (limit 10s)      F07 header row toggles on/off
F02 mixed formats merged into one paper        F08 corrupt file reported, others unaffected
F03 text PDF reflowed, 0 garbled chars         F09 100 pages, 0 lines lost, 59MB RAM
F04 scanned PDF cleaned and embedded           F10 preview renders
F05 ink-saver: page whiteness 7.8% → 85.5%     F11 footer attribution can be turned off
F06 2-up: 3 pages → 2
```

## Known limits (stated up front, so you don't wait for them)

- **No `.doc`** (Word 2003 and earlier). Save as `.docx`.
- **No handwriting recognition.** "Photograph the completed worksheet and auto-grade it" is a paid commercial API category, not an open-source one. The path this project takes instead: let the kid **answer on screen**, which removes handwriting from the problem entirely.
- **No pretty maths typesetting.** Formulas are handled as text or image blocks.

## Stack

FastAPI + uvicorn · PyMuPDF (PDF parsing) · Pillow + OpenCV (image clean-up) · ReportLab (A4 output, embeds a subset of the system CJK font) · RapidOCR (planned for V1.1) · plain HTML/CSS/JS frontend, zero build step, zero CDN

## For developers

Read `docs/` before changing layout code. It records **hypotheses that measurement disproved**, not design wishes — for example why column detection must run on raw fragments rather than merged text lines, why image clean-up must be keyed on sharpness rather than pixel count, and why you cannot use OCR accuracy as the acceptance test for print quality. Skipping those will cost you a day each.

Run everything: `scripts/check.bat` (Windows) or the individual `py -3.11 tests/*.py`.

## License

MIT — free forever, no ads, no paid tier.

> If your kid also prints homework every week, a ⭐ helps this reach the next parent.
