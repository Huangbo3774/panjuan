"""题目配图：把题干旁边的图形/表格/平面图裁下来，挂到对应题目上（用户硬需求）。

为什么必须做：二年级卷大量题目是"看图列式""在平面图上标方向""连一连"，
图没了这道题根本没法做。OCR 只能拿到文字，图形区域在文本里就是空洞。

做法（对扫描页、文字层页、单张照片统一）：
  1. 每道题在源页上占一个区间：**栏的 x 范围 × [本题首行顶, 同栏下一个锚点顶)**；
     锚点 = 同栏的下一道题，或下一个大题题头（一、二、三…）；
  2. 把该区间【限制在这一栏内】栅格化，挖掉这一栏里的文字行框，剩下的墨就是图形；
  3. 剩余墨做连通域分组（膨胀半径 DILATE_PT），一题里有两张不相干的图就出两张；
     ⚠️ 第 2 步挖掉的文字行会在图中间打洞，把一张完整的平面图切成左右两半
        （用户原话"你把应该一页的弄成多页了"），所以第三步后还有一道**补洞合并**；
  4. 尺寸/墨量/形状三重门槛（细长条＝装订线、空心框＝表格线），
     外加"**跨页重复出现的固定位置**"＝页眉 logo / 页脚装饰，不是题图；
  5. 图存到 data/figures/<paper>/，不能放 var/ —— 服务启动会清空 var/。

⚠️ 判据是"墨"而不是"OCR 有没有读到字"：图形里常常也带文字（"北""东"、表头），
   那些字会被 OCR 读成行、被第 2 步挖掉，剩下的线条/形状才是我们要的图。

⚠️ 第 1、2 步的"栏"是这一版重写的全部原因：旧版取整页宽的纵向条带，
   横版两张 A4 并排的真实卷（综合实践单元.pdf 841×653pt）因此把隔壁半页的图
   一起框了进来，用户原话"图片和题目不对应，都对应错了""你区分不了左右区域吗"。
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from .rules import is_furniture_text

# ── "什么算墨"的门限：每页按 Otsu 自适应，夹在 [150, 215] ──────────────
# 四份真实卷逐页量下来 Otsu 落在 171–210，固定 160 一直在系统性漏墨：
# 5·3 天天练那种淡蓝框线的地铁线路图、书法馆路线图整张图只剩几行字 → 裁不出图 → 题做不了。
# 上限 215 是防拍照页/脏底把整页当墨（周末作业有 21% 像素低于 210 的页）。
INK_THR_MIN = 150
INK_THR_MAX = 225
INK_THR_FIXED = 160        # numpy/cv2 不可用时的兜底（就是老行为）
INK_FRAC_MAX = 0.12        # 一页最多认这么多比例是墨（拍照页防"整页当图"）

MIN_FIG_PT = 42.0          # 图形最小边长（pt），小于这个多半是标点残影或表格线头
# 面积下限取 1200pt²（≈55×22）：数轴、线段图这类"又长又扁"的图是真实存在的，
# 阈值定成 51×51 那一类方块会把它们整批判成"没有图"（自测夹具实测命中）。
MIN_FIG_AREA_PT = 1200.0
MIN_INK_PT2 = 26.0         # 框内【真实墨迹】面积下限：空心大框（表格线、边框线）不是图
DILATE_PT = 7.0            # 连通域膨胀半径：把"图 + 旁边的箭头/标注小字"连成一块
MERGE_GAP_PT = 14.0        # 两个候选框近到这个程度就并成一张图
ROW_PEER_MIN_OVERLAP = 0.6  # "同一行"的判定：和图框的竖直重叠占短边 60% 以上
ROW_PEER_MAX_GAP_PT = 40.0  # 同行小块最多隔这么远才并回来（再远就是另一道式子）
SIDE_STITCH_MIN_Y_SHARE = 0.5   # 横向缝合：竖直重叠至少要占较矮那块的一半
SIDE_STITCH_MAX_GAP_PT = 80.0   # 横向缝合：两个并排钟面隔 236pt，不该并
# 一题最多挂几张。3 → 4 的实测依据：四份真实卷里 3 张会挤掉真图
# （第三单元练习题 第 2 题的三只蘑菇只剩两只），放到 4 之后图数 +3、
# 打印页数一张没变（14 页 / 3 页照旧）—— 也就是说这 3 张本来就没占地方。
MAX_PER_QUESTION = 4
DPI_PROBE = 100            # 探测图形用的分辨率（快）
DPI_CROP = 200             # 真正裁图用的分辨率（清晰）

# ── 补洞合并（"一张图被切成两块"的解药）───────────────────────────────
# 第 2 步会把文字行从墨迹里挖掉，可图里本来就带字：平面图的"蔬菜基地"、
# 记录单的表头 —— 挖掉这些字，一张完整的图就从字的位置裂成左右两半。
# 判据只用一条：**缝是我们自己挖出来的，才许补**。真空着的缝不许并，
# 否则一道题里两张分开的图（两个钟面）会被并成一个横跨半页的巨框。
BRIDGE_MIN_OVERLAP = 0.40    # 副轴重叠至少要占较矮那块的 40%（否则是斜着不相干的两块）
BRIDGE_MAX_GAP_RATIO = 1.5   # 缝宽 ≤ 1.5 × 较小那块的边长
BRIDGE_MAX_GAP_PT = 22.0     # 或缝宽 ≤ 22pt（碎片只有 2pt 高时只能用绝对值，见 _can_bridge）
BRIDGE_MIN_HOLE_RATIO = 0.35  # 缝里【被挖掉的文字】面积占比下限

# ── 页上家具（页眉 logo / 页脚装饰 / 竖排装订栏）────────────────────────
# 单一位置阈值不可靠（logo 有大有小），所以要求两条同时成立：
# ① 同样的框在【另一页】的同样位置也出现（±12pt、尺寸差 <15%）；② 贴着页边。
FURNITURE_TOL_PT = 12.0
FURNITURE_SIZE_TOL = 0.15
EDGE_ZONE_PT = 22.0
# 竖排装订栏 / 左右侧边栏（学校·班级·姓名·学号、"综合实践·画校园路线图"色块）：
# 贴在物理页边 45pt 以内、自己又窄又长。
# 真实卷实测（综合实践单元.pdf 页宽 841 / 综合实践课.pdf 页宽 595）：
#   左栏 (0,315)-(36,514) 36×199、(18,197)-(36,315) 18×117、(18,36)-(70,145) 52×109
#   右栏 (549,137)-(589,236) 40×98、(787,241)-(815,351) 28×110、(755,362)-(815,546) 60×184
# 同批真图（48×73 指南针、239×69 平面图、195×169 房屋图）都不满足"贴边 + 窄长"。
MARGIN_EDGE_PT = 45.0
MARGIN_MAX_W_PT = 60.0
MARGIN_MIN_ASPECT = 1.5
# 文字残影判定：容差 = 该行文字框高度 × 这个倍数（容差是"一行高"，不是固定像素，
# 因为 OCR 行框的偏差量级就是一行高）
TEXT_RESIDUAL_LINE_PAD = 1.0
# 只有"一行字高、横向铺开、框里没有长横线"的墨才当文字残影砍掉。
# 三个数都来自两张真实卷的读数表（var/_diag_runs.py）：
#   该砍的：242×14 最长横线 10.1pt、122×13 9.4pt、148×11 10.8pt
#   该留的：数轴/线段图（连续横线几十～上百 pt）、64×32 地铁站框、56×27 记录单格子
TEXT_MAX_H_PT = 16.0      # ≈ 一行字高
TEXT_MIN_W_PT = 60.0      # 再窄就是一坨符号，不是"一行字"
TEXT_MIN_RUN_PT = 18.0    # 比一个字宽（≈10pt）留一倍余量
# 图边被我们自己挖的文字行切掉一行时，允许把【紧贴图边】的那行标签吸回来（pt）。
# 8pt ≈ 半行高：真实卷上"西瓜基地—葡萄基地—草莓基地"那行的下沿和剩下的墨只差 3pt，
# 容差取 3pt 点不到（第一版就是这么漏的），再大就开始往正文里爬。
GROW_TOUCH_PT = 8.0
GROW_MAX_ROWS = 2         # 一张图最多吸两行标签，再多就是在吃正文
GROW_MIN_BELOW_TOP_LINES = 0.5   # 区间第一行是题干，永不吸
GROW_MIN_ROW_SHARE = 0.7         # 这行至少要有图宽的七成才算"图内的标签行"
GROW_ROW_OVERHANG_PT = 6.0       # 标签行允许比图宽出多少（pt）；题干行超出的是几十 pt
# 紧贴图边的小标点框（一个括号）也要圈进裁图，否则算式少半个括号
SHORT_MARK_MAX_PT = 90.0        # 一对空（“（      ），实测 56pt）也要箈进去；整句题干是 150-300pt，超过就不是“小标点”
SHORT_MARK_GAP_PT = 8.0
# 小标点的"内容"关：宽度不够挡（小版面换行正文也就 80–90pt 宽），必须看它写的是什么
SHORT_MARK_TEXT_RE = re.compile(r"^[（）()〔〕〈〉《》\[\]□○◇△☆√×÷＋－+\-·、,。．…—\s]{1,14}$")
# 行内碎片：OCR 把"题干 + 图里的标注"合并成同一行时，整行挖掉＝把图注从图里挖走，
# 整行吸回＝把题干吸进图里，两头都错（真实卷：综合实践单元(1).pdf 第 1 页 第 4 题，
# "4.如右图所示，两名同学玩背靠背夹" 和气泡里的 "我面向东。" 被读成一行 → 这道题没图做不了）。
FRAG_GAP_PT = 6.0          # 行内空白 ≥ 这个宽度才算两坨不相干的东西（≈ 一个字宽）
FRAG_MIN_W_PT = 16.0       # 比两个字还窄的碎片多半是一个汉字/一个括号，不算"图注"
FRAG_MAX_W_PT = 45.0       # 只把这么短的碎片吸进图；整句题干的碎片是 70–300pt
# 跨题缝合：题号边界穿过一张图时，上下两半重新拼成一张（围棋盘实测）
STITCH_GAP_PT = 2.0            # 只缝"上下重叠或几乎贴上"的：题界是一条线，不会留下真空隙
STITCH_MIN_X_SHARE = 0.6
STITCH_MIN_W_RATIO = 0.6       # 两半宽度比值下限：差太多就是两张图，不是一张被劈开
STITCH_MAX_UNION_PT = 240.0        # 缝合后的图最大边长（pt）：超过就是"整页缝一张"了
# 尺寸门槛的参照栏宽（pt）：A4 竖版两栏时一栏 ≈280pt，MIN_FIG_* 就是在这上面量的
GATE_REF_COL_PT = 280.0
# 裁框盖住【本题第一行文字】这么多比例，就算「图里重复了一遍题目」
STEM_IN_FIG_COVER = 0.8

# ── 栏目横幅 / 答题框块：不是题图（用户截图里的两种废图）─────────────────
# 栏目横幅（"第二步 练变式"的橙底白字色块）：OCR 读成文字、被 is_furniture_text
# 认成家具行 → 进了 wall；可色块比那行字高，上下两条边留在墙外，膨胀 + 14pt
# 近邻合并又把它们连成一个 111×37 的候选。判据只看墨落在哪：
#   第三单元练习题 实测：横幅候选 89.1% 的墨在墙里；同卷 37 张真图最高 30.5%
#   （"3×21 读作"那张，右沿压到竖排装订栏），次高 6.9% → 0.60 两边各留 30 点。
WALL_INK_SHARE_MAX = 0.60
# 答题框块（`□×□＝□`）：那是【作答位置】，不是画。它和"图形代表数"的题图
# 长得像，所以不能只看"方框出现"——四条同时成立才砍：
#   ① ≥2 个 ≥12pt 的空心方框（用题干符号重建的同一个分类器，星/圆不算方框）；
#   ② 方框的墨占全框墨 ≥40%（实测真卷四个样本 0.49–0.84）；
#   ③ 高 ≤90pt（两行 `□×□＝□` 实测 72pt，单行 38–39pt）；
#   ④ 没有 ≥38pt 的其他墨、也没有星/圆/三角/菱形等形状（那才是题图）。
# 六份真实 PDF 全量跑：命中的正是用户截图的 4 张答题框，真图 0 误伤。
ANSWER_BOX_MIN_SQUARES = 2
ANSWER_BOX_MIN_PT = 12.0
ANSWER_BOX_MIN_SHARE = 0.40
ANSWER_BOX_MAX_H_PT = 90.0
ANSWER_BOX_MAX_OTHER_PT = 38.0


def _ink_threshold(gray) -> int:
    """这一页"什么算墨"的门限：**让最黑的 12% 像素算墨**，夹在 [150, 225]。

    为什么不能写死 160：5·3 天天练那种淡蓝框线的地铁线路图、书法馆路线图、
    星星月亮算式图，线本身灰度 180–215；固定 160 下整张图只剩几行字 →
    裁不出图，题做不了。

    为什么是"分位数"而不是 Otsu（两个都实测过才敢定）：
      · Otsu 是"文字 vs 背景"的双峰分割，它【不知道】淡色图形的存在：
        纯文字层页 Otsu≈170，淡蓝线（194）照样看不见 —— 夹具实测裁不出图。
      · Otsu 在拍照页上又太激进：周末作业(1).pdf 第 3 页 Otsu=202 → 21.6% 的像素
        算墨，"图"变成整页宽的一条。
      · "最黑 12% 的分位"两头都对：干净页放到 225 时墨占比也只有 3.2%
        （实测，不会把背景吃进来）；脏页自动压到 170 上下，墨占比钉死在 12%。
    """
    try:
        import numpy as np
        t = float(np.percentile(gray, INK_FRAC_MAX * 100.0))
        return int(min(INK_THR_MAX, max(INK_THR_MIN, t)))
    except Exception:
        return INK_THR_FIXED


class PageSource:
    """一页源材料：统一成"pt 坐标 + 可栅格化 + 可裁剪"。"""

    def __init__(self, page_no: int, width_pt: float, height_pt: float,
                 gray: Any, crop: Callable[[tuple[float, float, float, float], str], None],
                 ink_thr: int | None = None):
        self.page_no = page_no
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.gray = gray                       # numpy 二维数组，DPI_PROBE 下的灰度图
        self.crop = crop                       # (x0,y0,x1,y1) in pt, out_path
        # 墨门限在构造时算一次：每页一个值，不能每个候选框重算（慢，且同一页必须同判据）
        self.ink_thr = int(ink_thr if ink_thr is not None else _ink_threshold(gray))


def page_source_from_pdf(path: str, page_no: int, dpi_probe: int = DPI_PROBE) -> PageSource | None:
    import pymupdf
    doc = pymupdf.open(path)
    try:
        if page_no - 1 >= doc.page_count:
            return None
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi_probe, colorspace=pymupdf.csGRAY)
        import numpy as np
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        w_pt, h_pt = page.rect.width, page.rect.height

        def crop(rect: tuple[float, float, float, float], out: str) -> None:
            d2 = pymupdf.open(path)
            try:
                pg = d2[page_no - 1]
                k = 72.0 / dpi_probe
                clip = pymupdf.Rect(rect[0], rect[1], rect[2], rect[3])
                pg.get_pixmap(dpi=DPI_CROP, clip=clip).save(out)
                del k
            finally:
                d2.close()

        return PageSource(page_no, w_pt, h_pt, gray, crop)
    finally:
        doc.close()


def page_source_from_image(path: str, page_no: int = 1,
                           dpi_probe: int = DPI_PROBE) -> PageSource | None:
    """单张作业照片。页面尺寸按图片像素反推（1px = 1pt 的虚拟页面，
    裁剪时再按真实像素比例换算），保证 OCR 的 px 坐标和这里一致。"""
    import numpy as np
    from PIL import Image
    try:
        im = Image.open(path)
    except Exception:
        return None
    im_w, im_h = im.size
    w_pt = im_w * 72.0 / dpi_probe
    h_pt = im_h * 72.0 / dpi_probe
    gray = np.asarray(im.convert("L"))
    k = dpi_probe / 72.0                     # pt → 探测图 px（这里 1pt = 1px @dpi_probe）

    def crop(rect: tuple[float, float, float, float], out: str) -> None:
        box = (max(0, int(rect[0] * k)), max(0, int(rect[1] * k)),
               min(im_w, int(rect[2] * k)), min(im_h, int(rect[3] * k)))
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        with Image.open(path) as raw:
            raw.convert("L").crop(box).resize(
                (int((box[2] - box[0]) * DPI_CROP / dpi_probe),
                 int((box[3] - box[1]) * DPI_CROP / dpi_probe)),
                Image.LANCZOS).save(out)

    im.close()
    return PageSource(page_no, w_pt, h_pt, gray, crop)


def _merge_boxes(boxes: list[list[float]], gap: float, wall=None, np=None) -> list[list[float]]:
    """把重叠或靠得近的候选框并成一张：图和它的标注箭头不该被切成两半。

    ⚠️ 但【中间横着一道墙】（页脚、扫描 app 的 logo 那行字）时不许并 ——
       膨胀半径 7pt + 近邻半径 14pt 正好能把"图 → 页脚 → 页底二维码"这 22pt 的
       空隙接上，实测成品图上就带着"夸克扫描王"的广告。
    """
    bs = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, b = bs[i], bs[j]
                if (a[0] - gap <= b[2] and b[0] - gap <= a[2] and
                        a[1] - gap <= b[3] and b[1] - gap <= a[3]):
                    bs[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    bs.pop(j)
                    changed = True
                    break
            if changed:
                break
    return bs


def _components(band, k: float, np, cv2, wall=None) -> list[list[float]]:
    """墨迹掩码 → 候选图形框（像素坐标）。

    为什么用连通域而不是"剩余墨的总外接盒"：后者会把一栏里所有不相干的东西
    并成一个巨框（中间的大片空白也一起框进来），一题有两张小图时更是直接糊成一条。

    `wall`（页脚/那类印刷家具占的行）在【膨胀之后】再抹一次：不抹的话，
    膨胀半径 7pt 会把图直接接到墙下面那块墨上，两张不相干的东西变成一个连通域。
    """
    ink = band.astype(np.uint8) * 255
    if cv2 is None:
        ys, xs = np.nonzero(band)
        return [] if len(xs) == 0 else [[int(xs.min()), int(ys.min()),
                                         int(xs.max()) + 1, int(ys.max()) + 1]]
    r = max(3, int(round(DILATE_PT * k)))
    dil = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (r, r)))
    if wall is not None:
        dil[wall] = 0
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(dil, connectivity=8)
    out: list[list[float]] = []
    for i in range(1, n):
        x, y, w, h, _area = [int(v) for v in stats[i]]
        out.append([x, y, x + w, y + h])
    return out


def _max_h_run(sub, k: float, np) -> float:
    """框内最长的【连续水平墨线】（pt）。

    这是"图里的横线"和"没挖干净的文字行"之间唯一可靠的差别：
    图形的边框线、连线、箭头是几十 pt 一根的连续墨，汉字笔画最多一个字宽（≈10pt）。
    """
    best = 0
    for row in sub:
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        if len(starts):
            best = max(best, int((ends - starts).max()))
    return best / k


def span_box(src: PageSource, s: dict[str, Any]) -> tuple[float, float, float, float]:
    """这道题能用的矩形：【自己那一栏的 x 范围】×【区间 y0..y1】。

    探测带和裁图裁剪共用这一处（以前两处各写一遍，改一处忘一处就是"跨栏串图"）。
    缺栏信息时退回整页宽 —— 那正是旧 bug 的形状，所以这里必须被测试钉住。
    """
    return (float(s.get("x0") or 0), float(s["y0"]),
            float(s.get("x1") or src.width_pt), float(s.get("y1") or src.height_pt))


def _scan(src: PageSource, s: dict[str, Any], np, cv2) -> dict[str, Any] | None:
    """一道题的区间 → 栏内墨迹 / 挖掉的文字洞 / 近邻合并后的碎片框。

    拆成独立函数有两个原因：
      1. `hole` 必须留着 —— 补洞合并的判据是"这道缝是我们自己挖的"，没有它就分不清
         "图里的标注字"和"两张图之间的真空白"；
      2. 诊断脚本要能拿到同一份中间量，不能另抄一遍裁图逻辑（抄一遍就会走样）。
    """
    k = DPI_PROBE / 72.0
    h_img, w_img = src.gray.shape
    # ── A) 栏边界：只在题目所属的那一栏里找图 ─────────────────
    bx0, by0, bx1, by1 = span_box(src, s)
    cx0 = int(max(0.0, bx0) * k)
    cx1 = int(min(float(w_img), bx1) * k)
    y0 = int(max(0.0, by0) * k)
    y1 = int(min(float(h_img), by1) * k)
    if cx1 - cx0 < 8 or y1 - y0 < 8:
        return None
    band = (src.gray[y0:y1, cx0:cx1] < src.ink_thr)
    raw_band = band.copy()           # 挖字之前的墨：碎片判定要用（见 _row_fragments）
    hole = np.zeros(band.shape, dtype=bool)      # 【图里的标注】挖的洞 —— 补洞合并只认这个
    punched = np.zeros(band.shape, dtype=bool)   # 所有文字行都要从墨里挖掉（含页脚/logo）
    wall = np.zeros(band.shape, dtype=bool)      # 印刷家具占的行：连通域不许膨胀跨过去
    tb_px: list[list[float]] = []
    tb_wall: list[bool] = []
    for tb in s.get("text_boxes", []):
        ty0 = max(0, int(float(tb["y"]) * k) - y0 - 2)
        ty1 = min(band.shape[0], int((float(tb["y"]) + float(tb["h"])) * k) - y0 + 2)
        tx0 = max(0, int(float(tb["x"]) * k) - cx0 - 2)
        tx1 = min(band.shape[1], int((float(tb["x"]) + float(tb["w"])) * k) - cx0 + 2)
        if ty1 <= ty0 or tx1 <= tx0:
            continue
        punched[ty0:ty1, tx0:tx1] = True
        furniture = is_furniture_text(str(tb.get("text") or ""))
        # ⚠️ 页脚 / 页码 / 扫描 app 的 logo 那几行【不算"我们自己挖的洞"】，而是算墙：
        #    算进洞里的话，补洞合并会理直气壮地把"图 + 页脚 + 二维码"缝成一张
        #    （实测：综合实践单元(1).pdf 第 2 页 书法馆路线图，成品带着"夸克扫描王"）。
        if furniture:
            wall[ty0:ty1, tx0:tx1] = True
        else:
            hole[ty0:ty1, tx0:tx1] = True
        tb_px.append([tx0, ty0, tx1, ty1])
        tb_wall.append(furniture)
    band = band & ~punched           # 洞单独留一份，补洞合并时才用得到
    comps = _merge_boxes(_components(band, k, np, cv2, wall), MERGE_GAP_PT * k)
    comps.sort(key=lambda b: (b[1], b[0]))
    return {"band": band, "raw": raw_band, "hole": hole, "wall": wall,
            "comps": comps, "tb": tb_px, "tb_wall": tb_wall, "k": k,
            "y0": y0, "cx0": cx0}


def _is_text_residual(box: list[float], tb_px: list[list[float]], band, k: float,
                      np) -> bool:
    """一条"只有一行字那么高、横向铺开、框里又没有一根像样的横线"的墨 → 文字残影。

    真实卷上的样子（综合实践课.pdf 第 3 页 第 4 题）：图旁边那行
    "再向东走到家；欢欢先向西走，再" 的 OCR 框在 y 623–640，字实际印在 y 638–652，
    差了整整一行高 —— 于是这行字的笔画留在原地，被膨胀半径连成 242×14 的"图"。
    一题凭空多出两张这种废图，用户看到的就是"应该一页的弄成多页"。

    四条同时成立才砍，每条挡一类误杀（阈值全部来自两张真实卷的读数表）：
      ① 整块墨落在某一行文字框（上下各放宽一行高）内 —— OCR 行框的偏差量级就是
         一行高，固定几像素对不准的卷完全失效；
      ② 高 ≤ TEXT_MAX_H_PT：只有一行字那么高。27pt 的记录单格子、47pt 的方格图不砍；
      ③ 宽 ≥ TEXT_MIN_W_PT：一小坨墨（标点、图里的符号）不砍；
      ④ 框内最长连续水平墨 < TEXT_MIN_RUN_PT：**数轴、线段图、带连线的表格**靠这条活下来
         —— 它们的横线是几十上百 pt 一根，汉字笔画最多一个字宽。
         （本模块最早踩的坑就是"又长又扁的真图被当噪声砍掉"，这条是它的反面保险。）
    """
    bx0, by0, bx1, by1 = [int(v) for v in box]
    if (by1 - by0) / k > TEXT_MAX_H_PT or (bx1 - bx0) / k < TEXT_MIN_W_PT:
        return False
    inside = False
    for t in tb_px:
        pad = (t[3] - t[1]) * TEXT_RESIDUAL_LINE_PAD
        if (bx0 >= t[0] - pad and by0 >= t[1] - pad
                and bx1 <= t[2] + pad and by1 <= t[3] + pad):
            inside = True
            break
    if not inside:
        return False
    return _max_h_run(band[by0:by1, bx0:bx1], k, np) < TEXT_MIN_RUN_PT


def _axis_measure(hole, a: list[float], b: list[float], axis: int) -> dict[str, Any] | None:
    """按某个主轴（0=左右、1=上下）量一对碎片：缝宽、副轴重叠、缝里的"洞"占比。

    ⚠️ 这里【只测量不判定】。判定单独放在 `_can_bridge`，为的是"先把真实卷上的
       数字打出来，再定阈值"—— 判据和驱动它的读数必须分两次实现（踩过太多次）。
    """
    if axis == 0:
        first, second = (a, b) if a[0] <= b[0] else (b, a)
        gap = second[0] - first[2]
        side = min(first[2] - first[0], second[2] - second[0])
        lo, hi = max(first[1], second[1]), min(first[3], second[3])
        ref = min(first[3] - first[1], second[3] - second[1])
    else:
        first, second = (a, b) if a[1] <= b[1] else (b, a)
        gap = second[1] - first[3]
        side = min(first[3] - first[1], second[3] - second[1])
        lo, hi = max(first[0], second[0]), min(first[2], second[2])
        ref = min(first[2] - first[0], second[2] - second[0])
    if side <= 0 or ref <= 0 or gap < 0:
        return None
    ov = max(0, hi - lo)
    ratio = 0.0
    if ov > 0 and gap > 0:
        strip = (hole[lo:hi, first[2]:second[0]] if axis == 0
                 else hole[first[3]:second[1], lo:hi])
        if strip.size:
            ratio = float(strip.mean())
    return {"axis": axis, "gap_pt": gap, "side_pt": side, "gap_ratio": gap / side,
            "ov_pt": ov, "ov_ratio": ov / ref, "hole_ratio": ratio}


def _pair_measures(hole, a, b) -> list[dict[str, Any]]:
    return [m for m in (_axis_measure(hole, a, b, 0), _axis_measure(hole, a, b, 1)) if m]


def _can_bridge(m: dict[str, Any]) -> bool:
    """该不该把两块并成一张 —— 缝里确实是被我们挖掉的文字、两块在副轴上真重叠、
    而且缝【相对这两块来说】不算长。

    ⚠️ 间距上限同时给绝对值和相对值，是因为真实碎片有两种量级：
      · 大图被劈成两半：两块各 150pt 宽，缝 20–40pt → 只有相对判据能并上；
      · 图框的上边线和下边线：各 2pt 高、缝 18pt → 相对判据算出来是 9 倍，
        只有绝对判据能并上（少了这条，一个空心方框会被切成上下两条线）。
    """
    near = (m["gap_pt"] <= BRIDGE_MAX_GAP_PT * (DPI_PROBE / 72.0)
            or m["gap_ratio"] <= BRIDGE_MAX_GAP_RATIO)
    return (m["hole_ratio"] >= BRIDGE_MIN_HOLE_RATIO
            and m["ov_ratio"] >= BRIDGE_MIN_OVERLAP and near)


def _bridge(comps: list[list[float]], hole) -> list[list[float]]:
    """把被文字行劈开的碎片补回一张图，直到没有可并的一对。"""
    bs = [list(c) for c in comps]
    while len(bs) > 1:
        best = None
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                for m in _pair_measures(hole, bs[i], bs[j]):
                    if _can_bridge(m) and (best is None or m["hole_ratio"] > best[0]["hole_ratio"]):
                        best = (m, i, j)
        if best is None:
            break
        _m, i, j = best
        a, b = bs[i], bs[j]
        bs[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        bs.pop(j)
    return bs


def _row_fragments(raw, t, k, np) -> list[list[float]]:
    """一行文字框 → 行内被空白隔开的【几坨墨】。只有一坨（或没墨）时返回 []。

    返回 [] 是刻意的：调用方拿 [] 就走老规矩（整行判定），一行正常的题干不会被
    这条新规则碰到。只有 OCR 把"题干 + 图注"并成一行、中间真空出一截时才有第二段。
    """
    if raw is None or np is None:
        return []
    x0, y0 = max(0, int(t[0])), max(0, int(t[1]))
    x1, y1 = min(raw.shape[1], int(t[2])), min(raw.shape[0], int(t[3]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return []
    cols = np.flatnonzero(raw[y0:y1, x0:x1].any(axis=0))
    if not cols.size:
        return []
    gap = FRAG_GAP_PT * k
    runs: list[tuple[int, int]] = []
    s = p = int(cols[0])
    for c in cols[1:]:
        c = int(c)
        if c - p > gap:
            runs.append((s, p))
            s = c
        p = c
    runs.append((s, p))
    if len(runs) < 2:
        return []
    out: list[list[float]] = []
    for a, b in runs:
        ax, bx = x0 + a, x0 + b + 1
        rows = np.flatnonzero(raw[y0:y1, ax:bx].any(axis=1))
        if not rows.size:
            continue
        out.append([float(ax), float(y0 + int(rows[0])),
                    float(bx), float(y0 + int(rows[-1]) + 1)])
    return out


def _absorb_label_rows(box: list[float], tb_px: list[list[float]], k: float,
                       raw=None, np=None, wall_flags=None,
                       absorbed_rows: list | None = None) -> list[float]:
    """把"图自己的那一行标签"吸回裁图范围。

    真实卷（综合实践课.pdf 第 3 页 第 3 题的实践基地平面图，就是用户截图那张）：
    第一行"西瓜基地—葡萄基地—草莓基地"被 OCR 当成整行文字挖掉，剩下的墨从第二行才开始，
    于是裁出来的图把第一行切成半截 —— 用户下一句必然是"图不完整"。

    ⚠️ 这条规则的失败模式比不吸更糟：把题干吸进图里，就是用户上一轮骂的
       "图片和题目不对应"。所以判据收到最紧，四条全中才吸：
      ① 紧贴图边（≤ GROW_TOUCH_PT）；
      ② 这行【完整落在图的横向范围内】（左右各只放宽 3pt）；
      ③ 这行自己至少有图宽的 GROW_MIN_ROW_SHARE —— 图内的标签行和图一样宽，
         而题干换行的半句（"的行驶方向。"只有图的两成宽）不满足；
      ④ 这行不是区间的第一行（区间顶就是题干第一行）。
      最多吸 GROW_MAX_ROWS 行。

    ⑤ 碎片例外（治"题干和图注被 OCR 并成一行"）：这种行永远过不了 ②（题干那截
       在图左边几十 pt 外），于是图注跟着被挖没。改成先按行内空白把这行切成碎片，
       只吸【紧贴图边、宽度 ≤ FRAG_MAX_W_PT、且这一侧还没吸过】的那一片。
       整句题干（70–300pt）和"每一侧只吸一片"就是它不吃正文的两道闸。

    实测（四份真实卷全跑一遍）：整条规则只在两处发生作用，两处都是该吸的 ——
    综合实践课.pdf 第 3 页 实践基地平面图（y0 424→407，把"西瓜基地—葡萄基地—草莓基地"
    那行接回来）、综合实践单元.pdf 第 2 页 酒店疏散图（y0 318→302）；
    其余候选一行都没吸，也就没有把题干吸进图里的情况。
    四条判据各由 tests/test_figures.py 的一条用例钉住，
    tests/break_figures.py 把每条单独打坏都要变红。
    """
    b = list(box)
    slack = GROW_TOUCH_PT * k
    edge = GROW_ROW_OVERHANG_PT * k
    used = [False] * len(tb_px)
    used_side: set[str] = set()
    absorbed = 0
    grew = True
    while grew and absorbed < GROW_MAX_ROWS:
        grew = False
        for idx, t in enumerate(tb_px):
            if used[idx]:
                continue
            if wall_flags is not None and idx < len(wall_flags) and wall_flags[idx]:
                continue                              # 页脚/页码那行是墙，永远不当"图注"吸
            frags = _row_fragments(raw, t, k, np)
            units = frags or [list(t)]
            for u in units:
                # 贴在图哪一侧（左右/上下）；哪都不贴就跳过
                side = None
                if abs(u[2] - b[0]) <= slack and u[3] > b[1] and u[1] < b[3]:
                    side = "left"
                elif abs(u[0] - b[2]) <= slack and u[3] > b[1] and u[1] < b[3]:
                    side = "right"
                elif abs(u[3] - b[1]) <= slack and u[2] > b[0] and u[0] < b[2]:
                    side = "above"
                elif abs(u[1] - b[3]) <= slack and u[2] > b[0] and u[0] < b[2]:
                    side = "below"
                if side is None or side in used_side:
                    continue                              # ① 不贴边 / 这一侧已经吸过一片
                if frags:                                 # ⑤ 碎片：够短、且至少两个字宽
                    if (u[2] - u[0]) > FRAG_MAX_W_PT * k:
                        continue
                    if (u[2] - u[0]) < FRAG_MIN_W_PT * k:
                        continue
                else:
                    if u[0] < b[0] - edge or u[2] > b[2] + edge:
                        continue                          # ② 必须整个在图的横向范围内
                    if (u[2] - u[0]) < (b[2] - b[0]) * GROW_MIN_ROW_SHARE:
                        continue                          # ③ 半句正文
                    line_h = t[3] - t[1]
                    if t[1] < GROW_MIN_BELOW_TOP_LINES * line_h:
                        continue                          # ④ 区间第一行＝题干
                b = [min(b[0], u[0]), min(b[1], u[1]), max(b[2], u[2]), max(b[3], u[3])]
                used_side.add(side)
                if not frags:
                    used[idx] = True                      # 整行吸过了，别再吸第二遍
                if absorbed_rows is not None:
                    absorbed_rows.append(idx)             # 下面 L) 规则要分清图注和题干
                absorbed += 1
                grew = True
                if absorbed >= GROW_MAX_ROWS:
                    break
            if absorbed >= GROW_MAX_ROWS:
                break
    return b


def probe_fragments(src: PageSource, s: dict[str, Any]) -> list[dict[str, Any]]:
    """诊断入口：这道题现在的碎片，以及两两之间的实测数字（含"会不会被并掉"）。"""
    import numpy as np
    try:
        import cv2
    except Exception:
        cv2 = None
    sgn = _scan(src, s, np, cv2)
    if not sgn:
        return []
    out: list[dict[str, Any]] = []
    for i in range(len(sgn["comps"])):
        for j in range(i + 1, len(sgn["comps"])):
            for m in _pair_measures(sgn["hole"], sgn["comps"][i], sgn["comps"][j]):
                out.append({**m, "a": sgn["comps"][i], "b": sgn["comps"][j],
                            "merge": _can_bridge(m)})
    return out


def _gate_scale(col_w: float) -> float:
    """尺寸门槛按【这一栏有多宽】缩放的比例：只放宽、不收紧。

    MIN_FIG_PT / MIN_FIG_AREA_PT 是在 A4 竖版那一栏（≈280pt）上量的。同一张插图
    印在 5·3 那种 64% 缩放的页面上（综合实践单元(1).pdf：栏宽 192pt）就只有
    52×22pt —— 按绝对值判"太小不值得裁"，孩子看到的就是"这道题没图，做不了"。
    上限 1.0 是保险：宽栏的卷子维持原判据，免得把已经调好的那几页垃圾放进来。
    """
    if col_w <= 0:
        return 1.0
    return max(0.5, min(1.0, col_w / GATE_REF_COL_PT))


def _absorb_row_peers(rect: tuple[float, float, float, float], peers: list,
                      box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """同一行里被"太小"闸门砍掉的小块，并回这张图。

    真实卷上的样子（第三单元练习题 第 1 页第 4 题「★＋★＝20」那道）：
    星星和加号连成一张 366×107 的图，可式子末尾的"（   ）"只有 11×22pt，
    被 small 闸门单独砍掉 → 裁图右边缘正好切在"＝（"上，
    孩子看不到"）"里要填什么。审计器的"切边"也看不见它：
    那条尺只看框外 6px 的贴边墨，而这里中间还隔着 26pt 空白。

    三条约束，一条都不能少：
      · 【同一行】竖直重叠 ≥60% —— 不然会把上下相邻的图一起拉进来；
      · 【水平间隙 ≤40pt】 —— 不然会把栏里另一道式子并进来；
      · 【夹回本题的栏区间】 —— 越栏就是用户骂过的"把右边跟他没关系的截过来"。
    ⚠️ 只【横向】长：竖直方向长出去就会撞回规则 L（裁框上沿不许吞本题起手句），
      而这一类缺陷本来就只发生在左右——式子被从中间截断。
    """
    r = rect
    changed = True
    while changed:
        changed = False
        for p in peers:
            ov = min(r[3], p[3]) - max(r[1], p[1])
            short = min(r[3] - r[1], p[3] - p[1])
            if short <= 0 or ov < ROW_PEER_MIN_OVERLAP * short:
                continue
            gap = max(r[0] - p[2], p[0] - r[2])
            if gap > ROW_PEER_MAX_GAP_PT:
                continue
            n = (min(r[0], p[0]), r[1], max(r[2], p[2]), r[3])
            n = (max(n[0], box[0] - 3), max(n[1], box[1] - 3),
                 min(n[2], box[2] + 3), min(n[3], box[3] + 3))
            if n != r:
                r = n
                changed = True
    return r


def _side_adjacent(r1, r2) -> bool:
    """两块是不是【同一行、横向挨得够近】—— 横向缝合的几何判据。"""
    ov = min(r1[3], r2[3]) - max(r1[1], r2[1])
    short = min(r1[3] - r1[1], r2[3] - r2[1])
    if short <= 0 or ov < SIDE_STITCH_MIN_Y_SHARE * short:
        return False
    return max(r1[0] - r2[2], r2[0] - r1[2]) <= SIDE_STITCH_MAX_GAP_PT


def _stitch_side_by_side(cands: list[dict[str, Any]],
                         report: list | None = None) -> list[dict[str, Any]]:
    """同一道题、同一行、被【文字行挖断】的几块，其实是一张图。

    真实卷（第三单元练习题.pdf 第 2 页第 1 题）：
        3 × 21 读作：（ ）        ← 一张"乘数 × 乘数 ＝ 积"的标注图
    OCR 的行框正好横穿这张图，按规矩文字行要从墨里挖掉，于是图被切成
    174×125 ＋ 59×47 ＋ 59×47 三块，每块只剩半个式子——用户指着说
    "图片中的字不全"。三块各自都过门槛，所以问题不在门槛，
    在【横向从来没有缝合】（上下方向早就有 _stitch_across_questions 治棋盘）。

    判据要严，两条各挡一类误伤：
      · 竖直重叠 ≥ 较矮那块的 50% —— 挡"上下本来就是两张图"被并成一张巨框；
      · 水平间隙 ≤ 80pt —— 挡两个并排钟面（实测间隙 236pt）被并成
        一张横跨半页的怪图（那是 test_figures 里现成的反例）。
    并且【只并同一道题的】：跨题并图会把邻题的图吞过来。

    ⚠️ 试过加第三条"缝里必须是我们自己挖的文字洞"（和上下补洞同一个原则），
      实测【不成立】：真卷那两道缝的重叠带里，洞只占 **4.5% / 4.8%**
      （复算见 tests/diag_hole_share.py；缝里绝大部分是算式上下两行之间的正常空白），
      门槛取 40% 时两张图又裂回三块。所以这条判据不接。
      代价说清楚：一题里两张【间距小于 80pt】的小图会被并成一张，
      这比"一张图被切成三块、每块只剩半个式子"划算，所以认了。
    """
    by: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in cands:
        by.setdefault((int(c["page"]), int(c["q_index"])), []).append(c)
    out: list[dict[str, Any]] = []
    for _key, g in sorted(by.items()):
        g = list(g)
        merged = True
        while merged:
            merged = False
            for i in range(len(g)):
                if merged:
                    break
                for j in range(i + 1, len(g)):
                    a, b = g[i], g[j]
                    if not _side_adjacent(a["rect"], b["rect"]):
                        continue
                    r = [min(a["rect"][0], b["rect"][0]), min(a["rect"][1], b["rect"][1]),
                         max(a["rect"][2], b["rect"][2]), max(a["rect"][3], b["rect"][3])]
                    a["rect"] = r
                    a["w_pt"] = round(r[2] - r[0], 1)
                    a["h_pt"] = round(r[3] - r[1], 1)
                    a["strict"] = bool(a.get("strict")) and bool(b.get("strict"))
                    g.pop(j)
                    if report is not None:
                        report.append({"q_index": a["q_index"], "page": a["page"],
                                       "kept": True, "rect": [round(v, 1) for v in r],
                                       "why": "side-stitch"})
                    merged = True
                    break
        out += g
    out.sort(key=lambda x: (x["page"], x["q_index"], x["rect"][1], x["rect"][0]))
    return out


def _size_gate(w_pt: float, h_pt: float, col_w: float) -> tuple[bool, bool]:
    """(这张能不能裁, 它是不是"严格合格")。"""
    s = _gate_scale(col_w)
    relaxed = (max(w_pt, h_pt) >= MIN_FIG_PT * s and w_pt * h_pt >= MIN_FIG_AREA_PT * s * s)
    strict = (max(w_pt, h_pt) >= MIN_FIG_PT and w_pt * h_pt >= MIN_FIG_AREA_PT)
    return relaxed, strict


def _prefer_strict(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """放宽门槛那一档【只在这道题一张严格合格的图都没有时】才生效。

    同一把尺放开也会把装订线碎墨、页脚那行字放进来（实测综合实践单元(1).pdf
    第 5 题因此多出一张"题干当配图"的怪图）。宁缺毋滥：有严的就只用严的。
    """
    byq: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in cands:
        byq.setdefault((c["page"], c["q_index"]), []).append(c)
    out: list[dict[str, Any]] = []
    for g in byq.values():
        hard = [c for c in g if c.get("strict")]
        out += hard if hard else g
    return out


def _is_margin_strip(rect: tuple[float, float, float, float], page_w: float) -> bool:
    """贴页边的窄长条＝装订栏 / 侧边栏，不是题图。"""
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w <= MARGIN_MAX_W_PT and (rect[0] <= 2.0 or rect[2] >= page_w - 2.0):
        # 窄框【齐着物理页边】＝装订线/侧栏被 ±3pt 外扩后顶到边上的那一条。
        # 真正的题图不会正好从 0 开始（±3pt 外扩也碰不到边），实测三份卷都验证过。
        return True
    if w > MARGIN_MAX_W_PT or h < MARGIN_MIN_ASPECT * w:
        return False
    return rect[0] <= MARGIN_EDGE_PT or rect[2] >= page_w - MARGIN_EDGE_PT


def _is_furniture(rect: tuple[float, float, float, float], page_no: int,
                  page_w: float, page_h: float, all_cands: list[dict[str, Any]]) -> bool:
    """页上家具＝同样的框在另一页的同样位置也出现，并且贴着页边。

    真实卷上这类东西有三种：左上角的 logo、页脚的装饰、左右两侧的竖排装订栏
    （学校/班级/姓名/学号）。它们每页都印一遍，位置几乎不差 —— 题目不会这样。
    """
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    touches_edge = (rect[0] <= EDGE_ZONE_PT or rect[2] >= page_w - EDGE_ZONE_PT
                    or rect[1] <= EDGE_ZONE_PT or rect[3] >= page_h - EDGE_ZONE_PT)
    if not touches_edge:
        return False
    for c in all_cands:
        if int(c["page"]) == int(page_no):
            continue
        r = c["rect"]
        rw, rh = r[2] - r[0], r[3] - r[1]
        if (abs(r[0] - rect[0]) <= FURNITURE_TOL_PT and abs(r[1] - rect[1]) <= FURNITURE_TOL_PT
                and abs(rw - w) <= w * FURNITURE_SIZE_TOL + 4
                and abs(rh - h) <= h * FURNITURE_SIZE_TOL + 4):
            return True
    return False


def _band_slice(rect: tuple[float, float, float, float], k: float, cx0: int, y0: int,
                shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """页面 pt 框 → 探测带上的像素切片，夹在边界内。

    ⚠️ 裁框允许比探测带外扩 3pt，直接相减会得到负下标；numpy 的负下标不是报错，
       而是静默从另一头切 —— 量出来的会是完全不相干的一块（这个坑实测踩过）。
    """
    hh, ww = shape
    return (max(0, int(rect[0] * k) - cx0), max(0, int(rect[1] * k) - y0),
            min(ww, int(rect[2] * k) - cx0), min(hh, int(rect[3] * k) - y0))


def _wall_ink_share(rect: tuple[float, float, float, float], raw, wall,
                    k: float, cx0: int, y0: int) -> float:
    """候选框里的墨，有多大比例落在【印刷家具行】的墙里（0 表示量不到）。

    为什么需要：栏目横幅（"第二步 练变式"的橙底色块）会被 OCR 读成一行文字、
    被 is_furniture_text 认成家具行而进 wall；但色块比那行字高，上下两条边留在
    墙外，膨胀 + 14pt 近邻合并又把它们连成一个 111×37 的"图"。
    判据只看墨落在哪，不看候选长什么样：
      真实卷实测 —— 横幅候选 89.1% 的墨在墙里；同卷 37 张真图最高 30.5%
      （右沿压到竖排装订栏的那张），次高 6.9%。阈值 0.60 两边各留 30 点。
    """
    if raw is None or wall is None:
        return 0.0
    px0, py0, px1, py1 = _band_slice(rect, k, cx0, y0, raw.shape)
    if px1 <= px0 or py1 <= py0:
        return 0.0
    sub = raw[py0:py1, px0:px1]
    total = int(sub.sum())
    if total <= 0:
        return 0.0
    return int((sub & wall[py0:py1, px0:px1]).sum()) / float(total)


def _is_answer_box_block(rect: tuple[float, float, float, float], raw,
                         k: float, cx0: int, y0: int, np) -> bool:
    """这个候选是不是【作答位置的答题框行】（`□×□＝□`），而不是题图。

    用户截图里 `4+4+4+3+5=□×□`、`□×□＝□` 被当成配图裁走，一题配图三四张，
    打印出来全是些小方框。它和"图形代表数"的题图确实长得像，所以四条同时成立才砍：
      ① ≥2 个边长 ≥12pt 的空心方框（用 symbols 里重建题干的同一个分类器，
         星/圆/三角/菱形都不算方框）；
      ② 这些方框的墨占全框墨 ≥40%（实测四个真样本 0.49–0.84）；
      ③ 整个候选高 ≤90pt（两行 `□×□＝□` 实测 72pt，单行 38–39pt）；
      ④ 框里没有 ≥38pt 的其他墨、也没有任何形状（那才是题图的主体）。
    六份真实 PDF 全量跑：命中的正是那 4 张答题框，真图 0 误伤。

    ⚠️ 已知不可分辨：如果卷面真的印了一道"只用方框和运算符"的图形算式题，
       它也会被这条砍掉。没有上下文时两者在像素上就是同一件东西；
       宁可少一张废图，不给每题塞四张答题框。
    """
    if raw is None:
        return False
    if rect[3] - rect[1] > ANSWER_BOX_MAX_H_PT:
        return False
    px0, py0, px1, py1 = _band_slice(rect, k, cx0, y0, raw.shape)
    sub = raw[py0:py1, px0:px1]
    if sub.size == 0:
        return False
    total = int(sub.sum())
    if total <= 0:
        return False
    import cv2
    from . import symbols as SY          # 和题干符号重建共用一把尺，别另写一份
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    n_sq, sq_area = 0, 0
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        w_pt, h_pt = w / k, h / k
        if max(w_pt, h_pt) >= ANSWER_BOX_MAX_OTHER_PT:
            return False                 # 还有一大块别的墨 → 是图的主体
        lab = SY.classify(SY.features(sub[y:y + h, x:x + w], np))
        if lab in SY.SHAPE_LABELS and lab != "square":
            return False                 # 星星/圆/三角/菱形…出来就不是答题框
        if lab == "square" and min(w_pt, h_pt) >= ANSWER_BOX_MIN_PT:
            n_sq += 1
            sq_area += area
    if n_sq < ANSWER_BOX_MIN_SQUARES:
        return False
    return sq_area / float(total) >= ANSWER_BOX_MIN_SHARE


def _covers(box_a, box_b) -> float:
    """box_a 盖住了 box_b 多少（交叠面积 ÷ box_b 面积）。"""
    ix = min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])
    iy = min(box_a[3], box_b[3]) - max(box_a[1], box_b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    area = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return (ix * iy) / area if area else 0.0


def _extend_to_short_marks(rect: tuple[float, float, float, float],
                           text_boxes: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """把紧贴图边的"小标点框"（一个括号、一个逗号）圈进裁图范围。

    为什么需要：图里的算式 "🌙=（ ）" 那对括号是【文字】，第 2 步会被挖掉，
    于是裁图框停在括号之前，印出来就是"🌙=(" —— 少半个括号，孩子看不出那是个空。
    实测（第三单元练习题 第 4 天 思维探究题）：图边外 4–9pt 处正好有这么一个 10pt 宽的"）"。

    ⚠️ 只吃"短框"：宽 ≤ SHORT_MARK_MAX_PT **且内容确实是个标点/括号**。光看宽度不够 ——
       小版面（综合实践单元(1).pdf 栏宽 192pt）的换行正文只有 86pt 宽，照样过宽度关，
       于是"的口令后，同学们将面向（ ）站立。"和页脚"157 综合实践(一)达标练习…"
       被一路串进装订栏那条 31pt 的碎墨里，裁出一张"题干当配图"的怪图。
       整句题干（150–300pt 宽）和"有字的框不是标点"就是这条不吃正文的两道闸。
    """
    r = list(rect)
    # 只走一轮：多轮会"顺着一个括号找到下一个括号"，实测把卷首 logo + 评价表
    # 一路串成 368×166 的大框，还盖住了下一道题的文字（审计器报"串题 1"就是它）。
    for _ in range(1):
        grew = False
        for tb in text_boxes:
            x0, y0 = float(tb["x"]), float(tb["y"])
            x1, y1 = x0 + float(tb.get("w") or 0), y0 + float(tb.get("h") or 0)
            if (x1 - x0) > SHORT_MARK_MAX_PT or (y1 - y0) > SHORT_MARK_MAX_PT:
                continue
            txt = str(tb.get("text") or "").strip()
            if len(txt) > 2 and not SHORT_MARK_TEXT_RE.match(txt):
                continue                              # 有内容的词/句不是"小标点"
            if (x1 - x0) * (y1 - y0) > (r[2] - r[0]) * (r[3] - r[1]) * 0.5:
                continue                              # 比图本身还大一半的，不是"小标点"
            near = (abs(x1 - r[0]) <= SHORT_MARK_GAP_PT or abs(x0 - r[2]) <= SHORT_MARK_GAP_PT
                    or abs(y1 - r[1]) <= SHORT_MARK_GAP_PT or abs(y0 - r[3]) <= SHORT_MARK_GAP_PT)
            if not near:
                continue
            # 副轴必须真的重叠：斜着挨着的一个逗号不算图的一部分
            if min(r[3], y1) - max(r[1], y0) <= 0 and min(r[2], x1) - max(r[0], x0) <= 0:
                continue
            n = [min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)]
            if n != r:
                r = n
                grew = True
        if not grew:
            break
    return tuple(r)


def _seam_has_ink(src: PageSource, a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float],
                  text_boxes: list[dict[str, Any]], np) -> bool:
    """两块中间的【接缝】上到底有没有墨：真被切开的一张图，图线会跨过接缝继续。

    这是把"一张图被题界劈开"和"两张本来就该分开的图上下相邻"分开的唯一硬证据。
    接缝取两块交界上下各 3pt 的一条，只看落在两块横向重叠范围内的部分，
    并且把文字行的框挖掉（题界那条线本身就是文字）。
    """
    k = DPI_PROBE / 72.0
    x0, x1 = max(a[0], b[0]), min(a[2], b[2])
    if x1 - x0 < 12:
        return False
    yj = max(a[1], b[1], min(a[3], b[3]))            # 交界（重叠时取重叠带上沿）
    y0 = int(max(0.0, yj - 3) * k)
    y1 = int(min(src.gray.shape[0], yj + 3) * k)
    bx0, bx1 = int(x0 * k), int(x1 * k)
    if y1 - y0 < 2 or bx1 - bx0 < 2:
        return False
    sub = src.gray[y0:y1, bx0:bx1] < src.ink_thr
    for tb in text_boxes:
        c, d = max(int(tb["y"] * k) - y0, 0), min(int((tb["y"] + tb["h"]) * k) - y0, sub.shape[0])
        e, f = max(int(tb["x"] * k) - bx0, 0), min(int((tb["x"] + tb["w"]) * k) - bx0, sub.shape[1])
        if d > c and f > e:
            sub[c:d, e:f] = False
    return int(sub.sum()) >= 12


def _band_share(u, band) -> float:
    """拼出来的图有多少落在某个区间里（纵向 pt 数）。"""
    lo, hi = max(u[1], float(band[1])), min(u[3], float(band[3]))
    return max(0.0, hi - lo)


def _stitch_across_questions(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import numpy as _np
    """同一栏里【上下紧挨着、横向基本对齐】的两块，其实是一张图被题界劈开。

    真实卷：第三单元练习题 第 5 页那张围棋盘，题号边界正好穿过棋盘中间，
    于是棋盘被切成"上半张挂第 21 题、下半张挂第 22 题"——
    两边都只看得到半个棋盘，谁都做不了。
    合并成一张，挂到【图落在谁区间里更多】的那道题上（两边一样多时挂靠前那道）。

    判据要严：必须同页同栏、上下间隙 ≤ STITCH_GAP_PT、横向重叠 ≥ 较窄那块的
    STITCH_MIN_X_SHARE，且属于不同的题。两张并排的钟面（横向分开）不满足。
    """
    by: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in cands:
        by.setdefault((c["page"], c["col"]), []).append(c)
    out: list[dict[str, Any]] = []
    for _key, g in sorted(by.items()):
        g = sorted(g, key=lambda x: (x["rect"][1], x["rect"][0]))
        used = [False] * len(g)
        for i, a in enumerate(g):
            if used[i]:
                continue
            r = list(a["rect"])
            qi = a["q_index"]
            own_band = a.get("band") or a["rect"]
            grew = True
            while grew:
                grew = False
                for j in range(i + 1, len(g)):
                    if used[j] or g[j]["q_index"] == qi:
                        continue                          # 同题的碎片由补洞合并管，这里只管跨题
                    b = g[j]["rect"]
                    gap = b[1] - r[3]
                    if gap > STITCH_GAP_PT or b[3] < r[1]:
                        continue
                    ov = min(r[2], b[2]) - max(r[0], b[0])
                    narrow = min(r[2] - r[0], b[2] - b[0])
                    if narrow <= 0 or ov < narrow * STITCH_MIN_X_SHARE:
                        continue
                    # ⚠️ 两半得【差不多宽】才像是同一张图被题界横着劈开。
                    #    真实反例（综合实践单元(1).pdf 第 1 页）：第 3 题的记录单 148pt 宽，
                    #    第 4 题那两个背靠背小孩 59pt 宽，正好叠在记录单右半边下面 ——
                    #    只看"横向重叠"就会缝成一张 148×76 的怪图，第 4 题从此没图。
                    #    正例是围棋盘那对：127pt 和 130pt，比值 0.98。
                    wide = max(r[2] - r[0], b[2] - b[0])
                    if narrow / wide < STITCH_MIN_W_RATIO:
                        continue
                    u = [min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3])]
                    # ⚠️ 必须有尺寸上限：拍照作业页（周末作业(1).pdf）每张图都是整页宽、
                    #    上下紧挨着，不加这条会一路缝成 595×788 的"整页一张图"，
                    #    实测配图 15 → 9、缺图 0 → 2、还冒出 4 条串题。
                    #    真正被题界劈开的图（围棋盘 127×35 + 130×87）拼起来才 130×117。
                    if (u[3] - u[1]) > STITCH_MAX_UNION_PT or (u[2] - u[0]) > STITCH_MAX_UNION_PT * 2:
                        continue
                    if not _seam_has_ink(a["src"], tuple(r), tuple(b),
                                         a["tbs"] + g[j]["tbs"], _np):
                        continue                      # 接缝上没有墨＝两张本来分开的图
                    # 挂给【图落在谁的区间里更多】那道题，不是无脑挂靠前那道：
                    # 真实卷（综合实践单元.pdf 第 1 页）第 4 题"背靠背夹球"那张图
                    # 顶到 441、底到 515，而第 3、4 题的分界在 466 —— 图有 48pt 属于
                    # 第 4 题、只有 25pt 属于第 3 题，按"靠前"就挂错了，
                    # 第 4 题的题干明明写着"如右图所示"却一张图都没有。
                    if _band_share(u, g[j].get("band") or b) > _band_share(u, own_band):
                        qi = g[j]["q_index"]
                        own_band = g[j].get("band") or b
                    r = u
                    used[j] = True
                    grew = True
            a = dict(a)
            a["rect"] = (r[0], r[1], r[2], r[3])
            a["w_pt"] = round(r[2] - r[0], 1)
            a["h_pt"] = round(r[3] - r[1], 1)
            a["q_index"] = qi
            out.append(a)
    return out


def _clip_stem_row(rect, text_boxes, absorbed_rows=()):
    """裁框把【本题第一行文字】整行盖住 → 把上沿收到这一行的下沿。

    照片卷/扫描卷上最常见的"图里又抄了一遍题目"：图就印在题干下面，
    而 OCR 的行框和真正的字常有半行错位（实测综合实践单元(1) 第 24 题：
    行框 155.8–161.3，字的墨却落在 157.7，±3pt 外扩后裁框顶到 154.7），
    于是裁出来的图整行框住了"2. 请为2号无人配送车设计一条行驶路线。"。

    两个"不收"的条件，都是宁可留着重复行也不能把图裁残：
      · 这一行是被规则⑤当【图注】吸回来的（气泡"我面向东。"和题干并成一行那种）；
      · 收完上沿就不够 8pt 高了。
    """
    if not text_boxes:
        return rect
    top_i = min(range(len(text_boxes)), key=lambda i: float(text_boxes[i]["y"]))
    if top_i in (absorbed_rows or ()):
        return rect
    tb0 = text_boxes[top_i]
    row0 = (float(tb0["x"]), float(tb0["y"]),
            float(tb0["x"]) + float(tb0.get("w") or 0),
            float(tb0["y"]) + float(tb0.get("h") or 0))
    if _covers(rect, row0) < STEM_IN_FIG_COVER:
        return rect
    cut = (rect[0], max(rect[1], row0[3] + 1.0), rect[2], rect[3])
    if cut[3] - cut[1] < 8 or cut[2] - cut[0] < 8:
        return rect                                 # 收完就没图了：宁可重复一行题干
    return cut


def find_figures(sources: dict[int, PageSource], spans: list[dict[str, Any]],
                 out_dir: str, report: list[dict[str, Any]] | None = None,
                 noise: list[dict[str, Any]] | None = None
                 ) -> dict[int, list[dict[str, Any]]]:
    """spans: [{q_index, page, col, y0, y1, x0, x1, text_boxes:[{x,y,w,h}]}]（单位 pt）
    返回 {q_index: [{path,name,page,w_pt,h_pt}]}。

    `report` 给诊断和测试用：每条被砍掉的候选都记下原因（hollow / text-residual /
    margin / furniture / cap）。没有它，"这张图为什么没出来"只能靠人眼猜。

    九条硬规矩（每条都是被真实卷打出来的，见 docs/V1.1-进度与实测.md）：
      A) 探测带**限制在题目所属栏的 x 区间内**。旧版是 `gray[y0:y1, :]` 整页宽，
         横版两张 A4 并排的卷子因此把隔壁半页的图一起框了进来。
      B) 区间下界来自【同栏的下一个锚点】（下一题或下一个大题题头），
         不是全局下一题 —— 旧版算出过 y0=514 → y1=34 的倒挂区间。
      C) 用连通域分组，一题里有两张图就出两张，不再并成一个巨框。
      D) 细长条（竖排装订线、横边框线）和空心大框（墨迹太少）一律不当图。
      E) 我们自己挖字挖出来的缝要补回去（`_bridge`）—— 否则一张平面图被切成
         两半，用户看到的就是"应该一页的弄成多页"。
      F) 跨页重复且贴页边的框是页上家具（每页都印的 logo / 页脚二维码），不当题图。
      G) 整块墨落在某一行文字框里的，是那行字没挖干净的残影，不当图。
      H) 贴物理页边的窄长条是装订栏 / 侧边栏，不当图。
      I) 紧贴图边、横向又在图范围内的那行文字（被挖掉的图内标签）要吸回裁图范围，
         否则裁出来的图缺最后一行。
      另）候选框的墨绝大多数落在"家具行"里（栏目横幅的色块）→ 不是题图；
          由 ≥2 个空心方框＋运算符组成的矮块是【作答位置】→ 不是图。
    """
    import numpy as np
    try:
        import cv2
    except Exception:                                   # cv2 是硬依赖，缺了也不能拖垮整卷识别
        cv2 = None

    # 被"太小"砍掉的小块先记下来：同一行里它们多半是式子的一部分
    # （括号、运算符），图框长出来一点比"算式少半个括号"划算得多。见 _absorb_row_peers。
    small_peers: dict[tuple[int, int], list] = {}

    def drop(qi: int, page: int, rect: tuple[float, float, float, float], why: str) -> None:
        if why == "small":
            small_peers.setdefault((page, qi), []).append(tuple(rect))
        if report is not None:
            report.append({"q_index": qi, "page": page, "kept": False,
                           "rect": [round(v, 1) for v in rect], "why": why})

    os.makedirs(out_dir, exist_ok=True)
    noise_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for m in noise or []:
        noise_by_page.setdefault(int(m.get("page", 1)), []).append(
            (float(m["x"]), float(m["y"]), float(m["x"]) + float(m.get("w") or 0),
             float(m["y"]) + float(m.get("h") or 0)))

    # ── 第一遍：只测量，不裁图。家具判定要看【全部】候选，单题循环里看不到另一页 ──
    cands: list[dict[str, Any]] = []
    for s in spans:
        src = sources.get(int(s["page"]))
        if src is None or src.gray is None:
            continue
        sgn = _scan(src, s, np, cv2)
        if not sgn:
            continue
        k, y0, cx0 = sgn["k"], sgn["y0"], sgn["cx0"]
        band, hole = sgn["band"], sgn["hole"]
        qi, pg = int(s["q_index"]), int(s["page"])
        # ── 尺寸门槛：跟着"这一栏有多宽"缩放（见 _gate_scale）──
        col_w = float(s.get("x1") or src.width_pt) - float(s.get("x0") or 0.0)
        gs = _gate_scale(col_w)
        min_ink = MIN_INK_PT2 * gs * gs      # 墨量下限跟着栏宽一起缩
        for bx0, by0, bx1, by1 in _bridge(sgn["comps"], hole):
            def to_pt(bx):        # 像素框 → 页面 pt 框（报告里要用，别写两遍）
                return ((cx0 + bx[0]) / k, (y0 + bx[1]) / k,
                        (cx0 + bx[2]) / k, (y0 + bx[3]) / k)
            # ── G) 补洞之后先剔文字残影：整块墨被某一行文字框装下的，是这行字没挖干净 ──
            if _is_text_residual([bx0, by0, bx1, by1], sgn["tb"], band, k, np):
                drop(qi, pg, to_pt((bx0, by0, bx1, by1)), "text-residual")
                continue
            # ── I) 图边被挖掉的那一行标签吸回来（否则裁出的图缺最后一行）──
            #     ⚠️ 必须在算 raw/rect 之前做：先算完再吸收，吸收就白做了（第一版实测漏吸）
            ate_rows: list[int] = []
            bx0, by0, bx1, by1 = _absorb_label_rows([bx0, by0, bx1, by1], sgn["tb"], k,
                                                    sgn.get("raw"), np, sgn.get("tb_wall"),
                                                    ate_rows)
            raw = to_pt((bx0, by0, bx1, by1))
            w_pt = (bx1 - bx0) / k
            h_pt = (by1 - by0) / k
            relaxed, strict = _size_gate(w_pt, h_pt, col_w)
            if not relaxed:
                drop(qi, pg, raw, "small")
                continue                                  # 标点残影，小到不值得裁
            # strict 那一档见 `_prefer_strict`：放宽门槛只在这道题一张严格合格的
            # 图都没有时才生效，宁缺毋滥。
            ink_pt2 = float(band[int(by0):int(by1), int(bx0):int(bx1)].sum()) / (k * k)
            if ink_pt2 < min_ink:
                drop(qi, pg, raw, "hollow")
                continue                                  # 空心框：表格线、页边框
            if w_pt < 26.0 and h_pt > 3.0 * w_pt:
                drop(qi, pg, raw, "thin-vertical")
                continue                                  # 竖排装订线 / 侧边栏
            if h_pt < 12.0 and w_pt > 6.0 * h_pt:
                drop(qi, pg, raw, "thin-horizontal")
                continue                                  # 一条横线
            rect = (max(0.0, raw[0] - 3), max(0.0, raw[1] - 3),
                    min(src.width_pt, raw[2] + 3), min(src.height_pt, raw[3] + 3))
            # ── K) 紧贴图边的小标点框圈进来（算式不能少半个括号）──
            #     ⚠️ 圈完必须夹回这道题自己的栏区间：横版两张 A4 的卷子一旦越栏，
            #     就又是用户骂过的"把右边跟他没关系的截过来"。
            rect = _extend_to_short_marks(rect, s.get("text_boxes") or [])
            lbx0, lby0, lbx1, lby1 = span_box(src, s)
            rect = (max(rect[0], lbx0 - 3), max(rect[1], lby0 - 3),
                    min(rect[2], lbx1 + 3), min(rect[3], lby1 + 3))
            # ⚠️ 试过"把框外紧贴的图形墨吃进来"（_grow_to_ink）来治审计器的"切边"，
            #    实测两头不讨好：周末作业确实 切边 1→0、含题干 3→1，
            #    但第三单元练习题 配图 57→50、缺图 0→2、切边 2→5 ——
            #    因为长出去的框被这道题的区间边界夹住，反而把邻题的图挤没了。
            #    结论：宁可少长 3pt，不可丢图——这条判据不接。
            # ── L) 裁框不许把「本题的起手句」整行框进图里 ─────────────
            #   照片卷/扫描卷上最常见的那种脏：图就印在题干下面，裁框上沿顶到区间
            #   第一行（＝题干第一行），印出来图里又重复一遍「2. 请为2号无人配送车…」。
            #   ⚠️ 一个例外：这一行被规则⑤当【图注】吸回来的（气泡「我面向东。」和题干
            #     并成一行那种），它是图的一部分，裁掉就把图裁残。
            cut = _clip_stem_row(rect, s.get("text_boxes") or [], ate_rows)
            if cut != rect:
                rect = cut
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "stem-clipped"})
            if rect[2] - rect[0] < 8 or rect[3] - rect[1] < 8:
                continue
            # ── J) 候选的墨绝大多数在【家具行】里 → 是栏目横幅，不是图 ──────
            #    横幅色块比 OCR 读到的那行字高，上下沿逃过了 wall，膨胀后才连成候选。
            if _wall_ink_share(rect, sgn.get("raw"), sgn.get("wall"),
                               k, cx0, y0) >= WALL_INK_SHARE_MAX:
                drop(qi, pg, rect, "furniture-row")
                continue
            # ── J2) 矮矮的一排空心方框＋运算符＝答题位置（`□×□＝□`）───────
            #    它和"图形代表数"的题图在像素上几乎同形，四条判据见 _is_answer_box_block。
            if _is_answer_box_block(rect, sgn.get("raw"), k, cx0, y0, np):
                drop(qi, pg, rect, "answer-boxes")
                continue
            # 装订栏框【只记一笔提醒，不砍候选】：试过"盖住装订栏字样就丢"，
            # 结果横版卷右半的地铁图/路线图因为右边 45pt 正好是装订栏而被整张砍掉
            # （综合实践单元(1).pdf 配图 11 → 4，缺图 5 → 9）。
            # 判据要回答的是"这块墨是不是图"，不是"它挨着谁"。
            for nb in noise_by_page.get(pg, []):
                if report is not None and _covers(rect, nb) >= 0.5:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "margin-touch"})
                    break
            cands.append({
                "q_index": qi, "page": pg,
                "strict": strict,
                "src": src, "col": int(s.get("col", 0)), "rect": rect,
                "tbs": s.get("text_boxes") or [],
                "w_pt": round(rect[2] - rect[0], 1), "h_pt": round(rect[3] - rect[1], 1),
                # rect 是给测试和"这图到底从哪儿裁的"留的凭据：
                # 没有它，"有没有跨栏"这种断言就只能靠人眼看图猜。
                "band": [round(float(s.get("x0") or 0), 1), round(y0 / k, 1),
                         round(float(s.get("x1") or src.width_pt), 1),
                         round(float(s.get("y1") or src.height_pt), 1)],
            })

    # ── 第二遍：跨题缝合 → 过滤页上垃圾 → 每题按【面积大到小】限量 → 按阅读顺序编号裁图 ──
    cands = _stitch_across_questions(cands)
    ok: list[dict[str, Any]] = []
    for c in sorted(cands, key=lambda x: (x["page"], x["q_index"], x["rect"][1], x["rect"][0])):
        src = c["src"]
        if _is_margin_strip(c["rect"], src.width_pt):
            drop(c["q_index"], c["page"], c["rect"], "margin")
            continue                                      # 装订栏 / 侧边栏
        if _is_furniture(c["rect"], c["page"], src.width_pt, src.height_pt, cands):
            drop(c["q_index"], c["page"], c["rect"], "furniture")
            continue
        ok.append(c)

    ok = _prefer_strict(ok)                 # 放宽那一档只在没严格图时才生效

    # 同一行被"太小"砍掉的括号/运算符并回图框（治"算式被从中间截断"）
    for c in ok:
        peers = small_peers.get((c["page"], c["q_index"])) or []
        if not peers:
            continue
        box = (c["band"][0], c["band"][1], c["band"][2], c["band"][3])
        grown = _absorb_row_peers(c["rect"], peers, box)
        if grown != c["rect"]:
            c["rect"] = grown
            c["w_pt"] = round(grown[2] - grown[0], 1)
            c["h_pt"] = round(grown[3] - grown[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"], "kept": True,
                               "rect": [round(v, 1) for v in grown], "why": "row-peer"})

    # 同一行被文字行挖断的几块并回一张（见 _stitch_side_by_side 的真卷说明）
    ok = _stitch_side_by_side(ok, report)

    # 限量必须【先按面积挑、再按阅读顺序排】。按 y 直接截断会出这种事：
    # 第三单元练习题 第 5 题的 453×109 大图被三个 58×46 的小块挤掉，
    # 因为小块的 y 更靠上 —— 用户看到的就是"大题没图，图给了小题"。
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in ok:
        groups.setdefault((c["page"], c["q_index"]), []).append(c)
    ordered: list[dict[str, Any]] = []
    for (_pg, _qi), g in sorted(groups.items()):
        big = sorted(g, key=lambda x: -((x["rect"][2] - x["rect"][0]) * (x["rect"][3] - x["rect"][1])))
        for c in big[MAX_PER_QUESTION:]:
            drop(c["q_index"], c["page"], c["rect"], "cap")
        ordered += sorted(big[:MAX_PER_QUESTION], key=lambda x: (x["rect"][1], x["rect"][0]))

    out: dict[int, list[dict[str, Any]]] = {}
    for kept, c in enumerate(ordered, start=1):
        src = c["src"]
        fp = os.path.join(out_dir, f"p{c['page']}_q{c['q_index']}_{kept}.png")
        try:
            src.crop(c["rect"], fp)
        except Exception:                              # 裁图失败不能拖累整卷
            continue
        if not os.path.exists(fp) or os.path.getsize(fp) < 200:
            continue            # 裁出空图就跳过（编号留个空洞无所谓，名字里有页码+题号）
        out.setdefault(c["q_index"], []).append({
            "name": os.path.basename(fp), "page": c["page"], "col": c["col"],
            "rect": [round(v, 1) for v in c["rect"]], "band": c["band"],
            "w_pt": c["w_pt"], "h_pt": c["h_pt"],
        })
    return out
