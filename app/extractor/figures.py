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

import math
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
# 表格/图框的底边线：文字从墨里挖走之后，它常被单独切成一条宽而薄的横线，
# 掉在小块里（真实卷：综合实践单元 p1 第 3 题两张记录单，底边 114×6.4pt）。
# 判定见 _absorb_row_peers 的"边框条"分支。
BORDER_STRIP_MIN_H_PT = 3.0
BORDER_STRIP_MAX_H_PT = 12.0
BORDER_STRIP_MIN_W_SHARE = 0.30
BORDER_STRIP_MAX_GAP_PT = 10.0
SIDE_STITCH_MIN_Y_SHARE = 0.5   # 横向缝合：竖直重叠要占【较高】那块的一半（见下）
SIDE_STITCH_MAX_H_RATIO = 1.5   # 两块高度比上限：真·同一张图的两半 1.004；答题框行:货架 1.70
SIDE_STITCH_MAX_GAP_PT = 80.0   # 横向缝合：两个并排钟面隔 236pt，不该并
# 同一题里小框整块落在另一个大框里＝同一张图被裁了两遍（见 _drop_contained）
CONTAIN_COVER_MIN = 0.90        # 小框面积有 90% 落进大框才算被罩住
CONTAIN_AREA_RATIO = 1.3        # 大框至少是小框的 1.3 倍面积（两块几乎同大时不互相踢）
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
# 齐着【物理页边】的框放宽到 100pt。真实卷证据（九份材料全量扫，见
# var/_edge_scan.py）：贴左边且宽度 ≤140 的保留候选只有一张 —— 第三单元练习题
# 第 2 页的 88×125 左栏残片（蓝色"第三单元"侧栏 + 橙色横幅 + 题干碎字）。
# 它宽 88 > 60、长宽比 125/88=1.42 < 1.5，原来两条判据都差一点，漏了。
# 真图不会从 0 开始：±3pt 外扩要碰到 x=0，原图必须已经印在页边上。
MARGIN_FLUSH_W_PT = 100.0
MARGIN_MIN_ASPECT = 1.5
# 页边竖排密封线被切掉后只剩窄条：这一列单字自己连成的候选，宽度实测 13–16pt
# （达标B q3/q4）。真图被切掉密封列后剩下的主体远宽于此，不会误伤。
SEAL_COLUMN_MAX_W = 40.0
# ── 页边装饰 / 扫描阴影 ────────────────────────────────────────────────
# 彩色练习册在左右页边印波浪边框（周末作业(1).pdf 第 4 页：蓝边 + 装订阴影），
# 灰度 120–188 之间，会被 ink_thr 算成"墨"，再经膨胀/近邻合并就连进旁边的表格，
# 裁出来的图右边多一条波浪边、左边多一条 61pt 的"边框 + 题干碎字"。
# 判据（十份材料逐页逐列实测，var/_diag_edge_profile.py）：
#   ① 外 30pt 的弱墨占比 ≥0.06 —— 只有真的有装饰才动手；空白页边是 0.000
#      （实测触发：周末 p4 L/R 0.187/0.260、第三单元 p2 L 0.102、p5 R 0.088、
#        综合实践课 p1 R 0.079；同一批的空白页边全部 ≤0.057）
#   ② 从页边向内扫到第一列"真墨"（<120，且一列 ≥10px）为止，这段叫死区；
#      死区里真墨占比 ≤0.01 —— 有正文/表格线就立刻停，不会吃进内容
#      （周末 p4 死区 47.5/47.5pt，真墨占比 0.0000/0.0001）
#   ③ 死区弱墨占比 ≤0.30 —— 一大片淡色插画不算装饰，不许整段抹掉
EDGE_SCAN_PT = 60.0
EDGE_DECOR_BAND_PT = 30.0
EDGE_DECOR_MIN_SHARE = 0.06
EDGE_DARK_LEVEL = 120
EDGE_DARK_MIN_PX = 10
EDGE_DEAD_MIN_PT = 8.0
EDGE_DEAD_DARK_MAX = 0.01
EDGE_DEAD_WEAK_MAX = 0.30
# 候选框罩住一整行【页面家具】文字（页脚/扫码广告/栏目横幅）≥ 这个比例 → 不是题图。
# 真卷证据：周末作业(1) 第 1 页 q1 巨框 [63,255,573,773] 含"智慧加油站"，
# 第 3 页底部卡 [0,711,586,885]、第 4 页 q5 卡 [0,549,586,855] 含"夸克扫描王/极速扫描；
# 其余九份材料 0 命中（十份材料全量复跑，见 var/_diag_furniture_rows.py）。
FURNITURE_ROW_COVER_MIN = 0.50
FURNITURE_ROW_MIN_W_PT = 24.0
# 家具行贴在候选框的哪一头才能"切掉它、留下图"：只认最外 35%。
# 夹在中间的横幅切不干净（切一刀会把真图劈成两半）—— 那种仍然整框丢。
# 真实卷（周末作业(1) 第 1 页第 4 题"观察下图"）：操场大图正下方就是绿色
# "智慧加油站"横幅，旧规则把整框判成页脚卡 → 图没了，题面还在问"观察下图"。
FURNITURE_TRIM_EDGE = 0.35
FURNITURE_TRIM_GAP_PT = 2.0
FURNITURE_TRIM_MIN_KEEP = 0.40   # 切完至少要留下原高度的 40%，否则就是一张横幅
# 小图把【两整行以上】文字从右边切断 → 是文字残片，不是图。
# 综合实践单元(1).pdf 第 2 页第 19 题：64×31 的框里只有两行"8505的人向( )…"的
# 左半截 + 一个蓝色装饰，右边 72pt 的字全在框外；这种框裁出来谁都看不懂。
# 只认"行从框内开始、伸到框外 ≥20pt、竖向 ≥60% 落在框内"的行，且要 ≥2 行。
# 十份材料全量读数（var/_diag_cut_lines.py）：
#   命中 2 行的只有这一张；命中 1 行的有 5 张，全部是带气泡/地图标签的真图
#   （q4 对话气泡、q9/q11 路线图、q10 地图），所以门槛必须是 2 行。
TEXT_CUT_MIN_ROWS = 2
TEXT_CUT_MIN_CHARS = 8
TEXT_CUT_OVER_PT = 20.0
TEXT_CUT_MIN_VSHARE = 0.60
# 图文同排：地图/示意图在左、题干在右，OCR 把两者拼成同一行（"喷泉 游乐场 是（ )。"），
# 候选框把题干也框进图里 → 随后整行被当"图内重复文字"删掉，题干只剩半句。
# 真实卷：综合实践单元(1) p2 第 1 题，框 [25,29,183,84]，地图到 x≈105、指北针 115–129、
# 题干从 134 起；列墨在 131.8–133.9 有一条 2.1pt 的贯通空白缝（左 70.6% 墨）。
# 判据：框内一条 ≥2pt 的空白竖缝，左侧 ≥40% 宽、右侧 ≥22% 宽、左墨 ≥50%，
# 且至少一行正文从缝左跨到缝右 ≥12pt → 右沿收到缝的右边。收完还要把只露半个字的
# 行（上一大题题头 / 下一题起手句）从上下沿切出去。
SIDE_SPLIT_MIN_W_PT = 60.0
# 100dpi 探测图上一个 2pt 宽的缝经常只剩 1 个纯白像素列（两侧抗锯齿），
# 所以门槛按"至少 1 列全空"；右侧宽度下限升到 30% —— 否则会从
# 正文里 2.1pt 的空格处切进去（实测 138.1 处就是"1."后面的缝）。
SIDE_SPLIT_GAP_PT = 0.7
SIDE_SPLIT_MIN_LEFT = 0.40
SIDE_SPLIT_MIN_RIGHT = 0.30
SIDE_SPLIT_LEFT_INK = 0.50
# 裁框上下沿压住一行字的多少才算"半个字"。正常 45%；正文行从框左沿之外伸进来时
# 放宽到 60% —— 真实卷 综合实践单元(1) p1 第 5 题，下一题起手句 x=205.4、图框
# x=206.5，被切 2.7/5.5pt（49%），按 45% 漏收，图底留一条半字黑边。
SLIVER_ROW_FRAC = 0.45
SLIVER_ROW_CROSS_LEFT_FRAC = 0.60
SIDE_SPLIT_ROW_CHARS = 8
SIDE_TEXT_OVER_PT = 12.0
# 混排行行首的短图注：≤4 个汉字、后随 ≥2 个空格（"喷泉      游乐场            是（"）。
SIDE_LABEL_MAX_CHARS = 4
SIDE_BODY_MIN_CHARS = 4
# 二维码：教辅页脚的"扫码看讲解"是页上家具，不是题图。
# 用 OpenCV 的专用检测器，只在 24–200pt 的近似方块上跑（十份材料实测：
# 周末作业 p1 页脚二维码命中，其余 9 张保留图全部不命中）。
QR_MIN_PT = 24.0
QR_MAX_PT = 200.0
QR_ASPECT_MIN = 0.60
# 检测器会在"金鱼群"这种高对比小图案上误报（第三单元练习题 p5 实测：detect=True、
# 但 decode 为空）。真二维码是黑白模块，暗墨占比 0.24–0.27；金鱼图只有 0.05。
# 判据取 detect + 暗墨占比 ≥0.15，两头都留足余量。
QR_DARK_MIN = 0.15
# ── 整题截图：文字归题干、图里只留真正的图形 ─────────────────────────────
# 用户原话："整题截图导致的「含题干 2」…下一轮做图文分离"。
# 达标A q1 是故事题整块截图：5 行题干全在框里，文字块下面只剩 15pt 纸边
#   → 整框不要（题干里的字一个不少，pinyin/空格都还在）。
# 达标B q8 是作文题截图：提示语 + 词语提示 + 写作格；文字块下面还有 200pt 格子
#   → 把顶部文字块切掉，只留格子（否则打印出来没有作答区）。
# 判据要同时满足 ≥2 行、其中一行 ≥15 字：图内的对话气泡/地图标签都是短句，
# 且题干起手句通常印在图框上方，不会整行落进图里。十份材料实测只有这两张命中。
ECHO_ROW_COVER_MIN = 0.80
# 只被裁框【横向切掉一截】的题干行（达标A q1：行框 177–437，裁框右沿 361.6，
# 覆盖 0.71）也算文字块的一部分：干净区必须从它的下沿开始量。否则下面那
# 43pt 的同一道练习会被当成"图下面的空白"，截图的右半截就留了下来。
ECHO_ROW_EDGE_MIN = 0.50
ECHO_ROW_MIN_CHARS = 8
ECHO_SENTENCE_MIN_CHARS = 15
ECHO_MIN_ROWS = 2
ECHO_CLEAN_MIN_PT = 60.0
# 矮框不是"整题截图"：一个多行故事题截下来至少 120pt 高（达标A q1 实测 177）。
# 气泡/说明框、图文同排的短块（综合实践单元 q20/q22/q23，实测 39–99pt）
# 一旦被 L0 整框丢掉，右半边的方格图/地图也跟着没了。短框交给后面的
# L/L2b 修边和图文分离处理；L0 只认"整道题都被拍进一张图"的高块。
STEM_SCREENSHOT_MIN_H_PT = 120.0
ECHO_TRIM_GAP_PT = 2.0
# 图被栏边界切断：竖线/表格伸进隔壁【没有题目】的页边带时，把连续的墨接回来。
# 达标B q8 的写作格右框线在 820pt、栏界 810.9pt，裁出来缺 6pt，
# 审计报"右+2795px"。只接"从框边起连续有墨"的条带，最多 40pt；
# 隔壁栏只要还有题，栏界仍是硬墙（横版两张 A4 的越栏事故不能再出现）。
EDGE_EXTEND_MAX_PT = 40.0
EDGE_EXTEND_GAP_PX = 1
# ── 图形算式整行：题干行里夹着"一个汉字大"的图标（番茄/黄瓜/苹果），OCR 读不出它们 ──
# 第三单元练习题 p7 第 31 题实测：一行 7 个图标（23–27×25–30pt，填充率 0.67–0.78），
# OCR 只读出"如果            =16,            =16,那么"——两处 12 个空格就是图标位置。
# 按普通图形裁，图标先被 OCR 行框从中间挖断，再裁出来只剩上下两截碎片；
# 打印出来题干是"如果 =16, =16,那么"，图是几块番茄皮，这道题没法做。
# 处理：命中"整行图形算式"时，不再按墨块裁，而是把这一整行（文字+图标+括号）
# 原样裁成一张【原图】，挂在题下；题干里补一句"图形见原图"。
# 这样孩子看到的是卷面原样，系统不猜图标是什么、更不编一行算式。
# 判据（十份材料全量扫过，只有第 31 题命中；q11 的空心方框/椭圆填充率 0.1–0.3 被挡）：
#   ① 同一 OCR 行里至少 3 个"字符级大图标"：短边 ≥18pt、长边 ≤42pt、
#      面积 ≥600px@100dpi、填充率 ≥0.50；
#   ② 这一行 OCR 文本里带 =，且有 ≥4 个连续空格的缺口（图标被 OCR 跳过的地方）；
#   ③ 图标横向铺开 ≥120pt；整块高 ≤120pt；块里不许再罩住别的 OCR 行。
GRAPHIC_ICON_MIN_PT = 18.0
GRAPHIC_ICON_MAX_PT = 42.0
GRAPHIC_ICON_MIN_AREA_PX = 600
GRAPHIC_ICON_FILL_MIN = 0.50
GRAPHIC_ICON_MAX_ASPECT = 2.2
GRAPHIC_EQ_MIN_ICONS = 3
GRAPHIC_EQ_MIN_GAP = 4
GRAPHIC_EQ_MIN_RUNS = 1
GRAPHIC_EQ_SPREAD_PT = 120.0
GRAPHIC_EQ_TAIL_PT = 120.0
GRAPHIC_EQ_CONT_PT = 55.0
GRAPHIC_EQ_MAX_H_PT = 120.0
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
# 共享图被题界切开时，底下那块常是地图最下面的一个方框（凉亭/图例），
# 和主体之间本来就有 10pt 左右的印刷空隙，并不是"两张图"。
# 只放宽这一种：同左沿、上块贴着自己的区间下沿（＝被题界切开）、
# 下块是薄片（≤30pt 高）。其它情况仍要求 ≤2pt 的贴边。
STITCH_SHARED_GAP_PT = 15.0
STITCH_SHARED_STRIP_H_PT = 30.0
# 接缝的"贯穿"判据：题目区间上下各留 3pt 边，会让【两张各自完好、只是贴在一起】
# 的图左右各自探出去 3pt 在题界上重叠 6pt。真实卷（第三单元练习题 第 4 页）：
# 第 2 题的连环画底边 446、第 3 题的操场图顶边 451.5，本来差 5.5pt，
# 被区间边一夹就"接上"了，第 3 题的裁图把第 2 题的图整个吞进来。
# 被题界真正劈开的图（围棋盘），笔画会从上半块穿过接缝继续到下半块；
# 两张分开的图只有各自的边框和零星墨点 —— 按【两侧都有连续笔画的列】数区分。
SEAM_CROSS_MIN_COLS = 6            # 至少这么多列在两半都有 ≥2px 的竖向笔画
SEAM_CROSS_WIDTH_SHARE = 0.02      # 且不少于接缝宽度的 2%（宽图按比例抬门槛）
SEAM_CROSS_MIN_RUN_PX = 2
# 被题界切下来的【一条薄片】例外：同宽的圆点阵被题界从两行之间切开时，
# 上面那行圆点和下面几行之间本来就没有笔画跨过接缝（圆点是断开的），
# 但薄片 + 同宽 + 紧贴已经足够证明是同一张图（第三单元练习题 第 4 页第 4 题：
# 上面 99.6×24.7pt 一行圆点、下面 99.6×85.4pt 三行圆点，被劈成两道题）。
# 两张完整的大图贴在一起不算：Q2 连环画 118pt、Q3 操场 122pt，都远高于这条。
STITCH_SLIVER_MAX_PT = 32.0
STITCH_SLIVER_MIN_W_RATIO = 0.9
# 尺寸门槛的参照栏宽（pt）：A4 竖版两栏时一栏 ≈280pt，MIN_FIG_* 就是在这上面量的
GATE_REF_COL_PT = 280.0
# 裁框盖住【本题文字行】这么多比例，就算「图里重复了一遍题目」
STEM_IN_FIG_COVER = 0.8
# 只处理【贴着裁框上沿】的那一行：行框顶比裁框顶低不超过 4pt。
# 真实卷（第三单元练习题 第 2 页第 3 题）裁框顶 436.9、行框顶 436.7；而图
# 内部自己的标注行（"北""西瓜基地"）上方一定还有图的墨，不会正好贴着裁框顶。
STEM_TOP_TOL_PT = 4.0
# 非第一行的额外门槛：行首必须贴着裁框左沿（≤ 24pt）才算题干行。
# 题干行从正文左边界起排；图自己贴在右上角的标注不是。真实卷三处反例：
#   综合实践课 第 2 题 "开心公园   北"：行首 423.3，裁框左沿 96.4（差 327pt）
#   第三单元练习题 第 3 题 "+2+2…"：行首 91.6，裁框左沿 42.4（差 49pt）
#   第三单元练习题 第 2 题 "加法算式:"：行首 289.9，裁框左沿 84.8（差 205pt）
# 三处都是图的一部分，旧规则只裁第一行时都没事；放宽到"任意贴顶行"后全被切掉。
# 正例（该裁）：第三单元达标练习题B 第 1 题读文行，行首 90.7 / 裁框 79.1（差 11.6）。
STEM_LEFT_TOL_PT = 24.0
# 裁框下沿把【最后一行题干】整行盖住时，行底离裁框下沿允许多远（pt）。
# 上沿那条是 4pt（OCR 行框和字几乎贴着）；下沿不一样：行框底下常留着
# 标点/行距的墨，裁框会再往下探几个点。真实卷（第三单元练习题 第 8 页第 30 题）
# 行底 422.0、裁框下沿 430.7，差 8.7pt —— 4pt 的门槛对它完全瞎。
STEM_BOTTOM_TOL_PT = 12.0
# 框底压着【多行】题干/阅读材料时，从末行往上把紧挨着的续行一起收。
# 真实卷（综合实践单元(1) 第 23 题）：三行阅读材料只有末行带句号，
# 旧版只收末行 → 前两行被当"图内重复文字"删掉，题干只剩一个孤零零的 ")"。
# 6pt 是 OCR 行框之间的正常行距上限（实测 4.1–5.5pt）。
STEM_BOTTOM_JOIN_PT = 6.0
# 裁框下沿把【图自己的标签行】切成半截时，把下沿放到标签行底下。
# 真实卷（周末作业(1) p1 第 3 题）：四个选项小图下方那行"？个 ?根 ？元 ?根"
# 与小图重叠 5pt，裁框正好从字中间切过 —— 图上留半截字、题干又留一整行。
# 阈值只要求"这一行确实压在这张图的横向范围内"：一行标签横跨四个选项小图时，
# 单张图只占它的 15–35%（四个候选都要各自往下放，否则拼回来仍缺一截）。
LABEL_STRADDLE_OVERLAP_MIN = 0.10
# 判断一行字是否印在【闭合边框】里（左右两个双栏插图框、表格）。
# 真实卷（周末作业(1) p2 第 2 题）：白菜/小兔两个绿框里的说明行被当成
# "图下方紧跟的题干末行"削掉，裁框从 540 收到 515，第二行说明整行丢失。
# 判据：行上方 ≤120pt 与行下方 ≤12pt 各有一条横线，且各自横跨这行宽度的 55%。
BORDER_COVER_MIN = 0.55
BORDER_LOOK_DOWN_PT = 12.0
BORDER_LOOK_UP_PT = 120.0

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
# 作答圆圈（`50-55 ○ 3×9`）：比大小的圆圈也是【作答位置】，不是图。
# L2 中期评估模拟卷 p1 第 2 题实测 42.7×65.7pt：两个 22pt 空心圈 + 几块
# 5–10.1pt 的算式残角（OCR 只盖住一部分），裁出来就是一张"两个圆圈"的废图。
# 判据（全部成立才砍）：
#   · 小窄条：宽 ≤60pt、高 ≤90pt、墨密度 ≤15%、总墨 ≤1000pt²；
#   · ≥2 个 12–40pt 的【空心】圈（必须有 ≥8pt 的圆洞，实心点/方框不算）；
#   · 圆圈墨占全框 ≥30%（残角再多也认得出来）；
#   · 其余墨块都 ≤14pt（真图主体、照片、大符号都会否决）。
ANSWER_CIRCLE_MAX_W_PT = 60.0
ANSWER_CIRCLE_MAX_H_PT = 90.0
ANSWER_CIRCLE_MIN_PT = 12.0
ANSWER_CIRCLE_MAX_PT = 40.0
ANSWER_CIRCLE_MIN_HOLE_PT = 8.0
ANSWER_CIRCLE_MIN_RINGS = 2
ANSWER_CIRCLE_MIN_SHARE = 0.30
ANSWER_CIRCLE_MAX_OTHER_PT = 14.0
ANSWER_CIRCLE_MAX_INK_PT2 = 1000.0
ANSWER_CIRCLE_MAX_DENSITY = 0.15
# 扫描墨迹会把相邻的 `□×□` 连成【一个】连通域：第三单元练习题 第 4 题实测
# 65.5×25.2pt 一块、内部 3 个洞（2 个是方框内腔），形状分类器只能叫它 minus。
# 这种"一行空方框"要按洞来数，否则永远只数到旁白那个独立方框（n_sq=1）。
# 只认【矮、宽、洞也是方的】那一种，免得把乘法阵列/方格图当成答题框。
MERGED_SQUARE_MAX_H_PT = 35.0
MERGED_SQUARE_MIN_ASPECT = 1.5
MERGED_SQUARE_MIN_HOLE_PT = 8.0
MERGED_SQUARE_MIN_HOLES = 2
# 空白作答行：卷面上印的 `读作:( )` / `写作:( )` 两对括号加虚线引导，
# 不是图 —— 第三单元练习题 p2 第 1 题实测 181×49pt、只有 4 个括号和 8 个点。
# 判据宁窄勿宽：任何一个 ≥18pt 的墨块都说明"这里有东西"，不砍。
BLANK_ROW_MAX_H_PT = 60.0
BLANK_ROW_MAX_PIECE_PT = 18.0
BLANK_ROW_MIN_PAREN_PAIRS = 1
BLANK_ROW_MAX_DENSITY = 0.06
BLANK_ROW_MAX_INK_PT2 = 500.0
BLANK_ROW_DOT_PT = 4.0
BLANK_ROW_ALLOWED = ("paren_open", "paren_close")
# 空白作答横线：`你会对爷爷说：“ ______ ”` 下面那种两三条长横线。
# 第三单元达标练习题B 第 5 题实测 320×38pt：两条长线（292pt / 88pt）＋
# 几块 OCR 没挖干净的 5–10.1pt 字角（行尾的闭合引号 `”`，OCR 行框只盖到 x=378）。
# 它不是图，印出来只是把题目里的作答线又画了一遍（与 `读作:( )` 的空白块同一类）。
# 判据：文字挖掉之后，除了 2–4 条长横线，只剩 ≤12pt 的碎点；
# 至少 1 条占框宽一半 —— 数轴只有 1 条长轴，不会被误砍。
# 12pt 的由来：实测引号残角 10.1pt，留 2pt 余量；14pt 以上的实墨块仍会否决。
BLANK_RULE_MAX_H_PT = 60.0
BLANK_RULE_MIN_LINES = 2
BLANK_RULE_MAX_LINES = 4
BLANK_RULE_MIN_LINE_PT = 30.0
BLANK_RULE_MAX_THICK_PT = 2.5
BLANK_RULE_MAX_OTHER_PT = 12.0
BLANK_RULE_LONG_SHARE = 0.5
# 纯文字块：两行以上的文字被拼成一个窄块（OCR 行框只盖住 86% 的墨，
# 剩下的字角连成候选）。第三单元练习题 p7 第 2 题实测 82×53pt、文字覆盖 86%，
# 同一份卷里真图的覆盖率最高 64%（气球图）—— 85% 就是按这个断层定的。
# 只认【小窄块】：整题截图（达标A 第 1 题 324×178pt、覆盖 70%）不在范围内。
TEXT_BLOCK_MIN_W_PT = 30.0
TEXT_BLOCK_MAX_W_PT = 160.0
TEXT_BLOCK_MIN_H_PT = 10.0
TEXT_BLOCK_MAX_H_PT = 90.0
TEXT_BLOCK_COVER_MIN = 0.85
# 大块虚线作答区（"问题一："/"问题二："那种 200×90pt 的虚线框）不是图。
# 第三单元练习题 第 4 页第 3 题实测：左框 195×101pt、墨密度 0.031、最长横线 13pt；
# 右框 229×135pt、0.048、18pt；同页真正的操场插图 436×117pt、0.247、100.8pt。
# 四条同时成立才算空白作答区，缺一条都不动（宁可留一张废图，不砍真图）：
#   · 框够大：宽 ≥100pt、高 ≥50pt；
#   · 框里几乎没有墨：密度 ≤6%；
#   · 框里没有长横线：最长连续横线 <20pt（实线表格/边框会超过）；
#   · 框线的短划都 ≤15pt（虚线每段实测 1.4–7.2pt；18pt 的圆点是下一题的图，必须留下）。
BLANK_AREA_MIN_W_PT = 100.0
BLANK_AREA_MIN_H_PT = 50.0
BLANK_AREA_MAX_DENSITY = 0.06
BLANK_AREA_MAX_RUN_PT = 20.0
BLANK_AREA_DASH_MAX_PT = 15.0


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


def _edge_dead_px(gray, ink_thr: int, k: float, np, side: str) -> int:
    """从物理页边向内量出"只有装饰/阴影"的宽度（像素）；0＝不动。

    只有在【外 30pt 确实有一片弱墨】时才启动（空白页边占比 0.000，不值得动刀），
    然后逐列找第一列"真墨"（<120 且该列 ≥10 个像素）—— 那一列就是内容的起点。
    死区里真墨必须近乎为零、弱墨不能铺满，否则说明是一张淡色插画，整段都不碰。
    阈值与十份材料的实测读数见常量区注释。
    """
    h, w = gray.shape
    span = min(w, int(EDGE_SCAN_PT * k))
    band = min(span, int(EDGE_DECOR_BAND_PT * k))
    if span < int(EDGE_DEAD_MIN_PT * k) or band < 4:
        return 0
    outer = gray[:, :band] if side == "left" else gray[:, w - band:]
    if float((outer < ink_thr).sum()) / max(1, outer.size) < EDGE_DECOR_MIN_SHARE:
        return 0
    cols = gray[:, :span] if side == "left" else gray[:, w - span:]
    strong = np.nonzero((cols < EDGE_DARK_LEVEL).sum(axis=0) >= EDGE_DARK_MIN_PX)[0]
    if side == "left":
        dead = int(strong[0]) if strong.size else span
        sub = cols[:, :dead]
    else:
        dead = int(span - 1 - strong[-1]) if strong.size else span
        sub = cols[:, span - dead:] if dead > 0 else cols[:, :0]
    if dead < int(EDGE_DEAD_MIN_PT * k):
        return 0
    area = int(sub.size)
    if area <= 0:
        return 0
    if float((sub < EDGE_DARK_LEVEL).sum()) / area > EDGE_DEAD_DARK_MAX:
        return 0
    if float((sub < ink_thr).sum()) / area > EDGE_DEAD_WEAK_MAX:
        return 0
    return dead


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


def _max_v_run(col, np) -> int:
    """一列里最长的【连续竖向墨迹】（px）。接缝判据用。"""
    if not col.any():
        return 0
    d = np.diff(np.concatenate(([0], col.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return int((ends - starts).max()) if len(starts) else 0


def _strip_blank_answer_areas(band, wall, k: float, np, cv2):
    """大块虚线作答区（"问题一："那种框）从墨里剔掉，只剔框线的短划。

    不剔的后果（第三单元练习题 第 4 页第 3 题，真实卷）：
      · 左边 195×101pt 的虚线框和自己的插图被补洞连成一张 442×246pt 的巨图，
        图里印着"观察图片…"和"问题一："，孩子拿到一张带题干的空白答题框；
      · 右边虚线框又把下一题点阵图的顶行连走，点阵在题界处被劈成两半。

    判据（见 BLANK_AREA_* 常量）：框大、墨稀、没有长横线。
    只剔 ≤15pt 的小短划；点阵里 18pt 的圆点、框里真正的大块图都留下 ——
    所以"框 + 下一题顶行"这种混在一起的候选，剔完框线后还能被跨题缝合接回去。
    """
    if cv2 is None or not band.any():
        return band, wall
    r = max(3, int(round(DILATE_PT * k)))
    dil = cv2.dilate(band.astype(np.uint8) * 255,
                     cv2.getStructuringElement(cv2.MORPH_RECT, (r, r)))
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(dil, connectivity=8)
    out = band.copy()
    walls = wall.copy()
    for i in range(1, n):
        x, y, w, h, _area = [int(v) for v in stats[i]]
        sub = band[y:y + h, x:x + w]
        if sub.size == 0 or not sub.any():
            continue
        nr, _l, st, _c = cv2.connectedComponentsWithStats(
            sub.astype(np.uint8) * 255, connectivity=8)
        small = []
        for j in range(1, nr):
            sx, sy, sw, sh, _sarea = [int(v) for v in st[j]]
            if max(sw, sh) / k <= BLANK_AREA_DASH_MAX_PT:
                small.append((sx, sy, sw, sh))
        if len(small) < 8:
            continue                      # 只有三五个小点的不是虚线框
        # 短划自己的外接框才是"框"：同一个连通域里可能还粘着下一题的圆点
        # （真实卷 q17 右框下面就是点阵顶行），用连通域的 bbox 会把框底算到圆点下面。
        dx0 = min(s[0] for s in small)
        dy0 = min(s[1] for s in small)
        dx1 = max(s[0] + s[2] for s in small)
        dy1 = max(s[1] + s[3] for s in small)
        dw, dh = dx1 - dx0, dy1 - dy0
        if dw / k < BLANK_AREA_MIN_W_PT or dh / k < BLANK_AREA_MIN_H_PT:
            continue
        frame = band[y + dy0:y + dy1, x + dx0:x + dx1]
        if frame.size == 0 or float(frame.mean()) > BLANK_AREA_MAX_DENSITY:
            continue
        if _max_h_run(frame, k, np) >= BLANK_AREA_MAX_RUN_PT:
            continue
        mx = max(3.0, 0.05 * dw / k) * k
        my = max(3.0, 0.05 * dh / k) * k
        dashes = []
        sides = [0, 0, 0, 0]                 # 上 / 下 / 左 / 右
        for sx, sy, sw, sh in small:
            cx, cy = sx + sw / 2.0, sy + sh / 2.0
            near = []
            if cy - dy0 <= my:
                near.append(0)
            if dy1 - cy <= my:
                near.append(1)
            if cx - dx0 <= mx:
                near.append(2)
            if dx1 - cx <= mx:
                near.append(3)
            for kk in near:
                sides[kk] += 1
            dashes.append((sx, sy, sw, sh, bool(near)))
        on_edge = sum(1 for d in dashes if d[4])
        # 短划必须【围在框边上】：点状纹理是铺满整块的，不能当虚线框剔。
        if on_edge / float(len(dashes)) < 0.80:
            continue
        if min(sides) < 2:
            continue                      # 四条边都得有，缺边的是别的东西
        for sx, sy, sw, sh, near in dashes:
            if not near:
                continue
            out[y + sy:y + sy + sh, x + sx:x + sx + sw] = False
            walls[y + sy:y + sy + sh, x + sx:x + sx + sw] = True
    return out, walls


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
    # ── 页边装饰/扫描阴影：从【物理页边】量死区，再映射回探测带 ──────────
    #    必须对 band 和 raw_band 同时生效：只看 band 的话，raw 里的波浪边
    #    仍会参与 _wall_ink_share / 文字覆盖判定，等于没删。
    dead_l = _edge_dead_px(src.gray, src.ink_thr, k, np, "left") if cx0 <= 0 else 0
    # ⚠️ 不能用 `cx1 >= w_img`：span 的 x1 是 595.2pt，乘 k 取整后是 826，
    #    比图像宽 827 少 1px —— 判据看似等价，实测直接让右页边抑制失效
    #    （周末作业 p4 的表格框仍伸到 595pt，波浪边原样带进成品）。
    dead_r = (_edge_dead_px(src.gray, src.ink_thr, k, np, "right")
              if cx1 >= w_img - 2 else 0)
    if dead_l:
        dl = max(0, dead_l - cx0)
        if dl:
            band[:, :min(band.shape[1], dl)] = False
            raw_band[:, :min(raw_band.shape[1], dl)] = False
    if dead_r:
        # 死区从【物理页边】向内算；探测带可能比页边早 1–2px 结束，要换算回带内坐标。
        dr0 = max(0, (w_img - dead_r) - cx0)
        if dr0 < band.shape[1]:
            band[:, dr0:] = False
            raw_band[:, dr0:] = False
    hole = np.zeros(band.shape, dtype=bool)      # 【图里的标注】挖的洞 —— 补洞合并只认这个
    punched = np.zeros(band.shape, dtype=bool)   # 所有文字行都要从墨里挖掉（含页脚/logo）
    wall = np.zeros(band.shape, dtype=bool)      # 印刷家具占的行：连通域不许膨胀跨过去
    tb_px: list[list[float]] = []
    tb_txt: list[str] = []
    tb_wall: list[bool] = []
    for tb in s.get("text_boxes", []):
        # 落在页边死区里的 OCR 行是装饰被误读（波浪边常被读成一行"字"）：
        # 不挖、不当墙、更不许当图注吸回裁图。
        if dead_l and float(tb["x"]) + float(tb["w"]) <= dead_l / k + 1.0:
            continue
        if dead_r and float(tb["x"]) >= (w_img - dead_r) / k - 1.0:
            continue
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
        tb_txt.append(str(tb.get("text") or ""))
        tb_wall.append(furniture)
    band = band & ~punched           # 洞单独留一份，补洞合并时才用得到
    # 大块虚线作答区先剔掉：不剔就会把"插图 + 空白框"补成一张巨图，
    # 或者把下一题的点阵图顶行连走（第三单元练习题 第 4 页第 3 题）。
    band, wall = _strip_blank_answer_areas(band, wall, k, np, cv2)
    comps = _merge_boxes(_components(band, k, np, cv2, wall), MERGE_GAP_PT * k)
    comps.sort(key=lambda b: (b[1], b[0]))
    return {"band": band, "raw": raw_band, "hole": hole, "wall": wall,
            "comps": comps, "tb": tb_px, "tb_txt": tb_txt,
            "tb_wall": tb_wall, "k": k,
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


def _is_text_covered_block(box: list[float], raw, tb_px: list[list[float]],
                           k: float, np) -> bool:
    """一小块窄框里的墨几乎全落在 OCR 文字行框里 → 是文字，不是图。

    真实卷（第三单元练习题 p7 第 2 题）：选项 ① 的右半截被 OCR 行框盖住 86%，
    剩下的字角散成候选、bbox 横跨 82×53pt，`_is_text_residual` 只认"一行高"
    于是放过了它 —— 成品里这幅"图"就是半句重复的选项文字。
    判据只有两条：
      · 覆盖：框里的墨 ≥85% 落在某一行文字框里（同卷真图最高 64%，断层 21 个点）；
      · 尺寸：30–160pt 宽、10–90pt 高。整题截图/材料框都比这个大，且覆盖率更低。
    """
    if raw is None or not tb_px:
        return False
    w_pt, h_pt = (box[2] - box[0]) / k, (box[3] - box[1]) / k
    if not (TEXT_BLOCK_MIN_W_PT <= w_pt <= TEXT_BLOCK_MAX_W_PT
            and TEXT_BLOCK_MIN_H_PT <= h_pt <= TEXT_BLOCK_MAX_H_PT):
        return False
    bx0, by0 = max(0, int(box[0])), max(0, int(box[1]))
    bx1, by1 = min(raw.shape[1], int(box[2])), min(raw.shape[0], int(box[3]))
    if bx1 - bx0 < 4 or by1 - by0 < 4:
        return False
    sub = raw[by0:by1, bx0:bx1]
    total = int(sub.sum())
    if total <= 0:
        return False
    inside = np.zeros(sub.shape, dtype=bool)
    for t in tb_px:
        a, b = max(int(t[0]) - bx0, 0), min(int(t[2]) - bx0, sub.shape[1])
        c, d = max(int(t[1]) - by0, 0), min(int(t[3]) - by0, sub.shape[0])
        if b > a and d > c:
            inside[c:d, a:b] = True
    return int((sub & inside).sum()) / float(total) >= TEXT_BLOCK_COVER_MIN


PROSE_PUNCT_RE = re.compile(r"[。，、；;？?！!：:]")


def _is_prose_row(text: str) -> bool:
    """一整行像不像"正文句子"：够长 + 带句读标点。

    记录表/表格里的标签行（"艺术楼 教学楼"、"( ) ( )"）不长也没有句读，
    不能拿来证明"这是一块文字框"；路线指示/对话气泡/描述框里是整句，
    才有资格被判成文字框。
    """
    t = re.sub(r"\s+", "", str(text or ""))
    return len(t) >= 12 and bool(PROSE_PUNCT_RE.search(t))


def _is_text_frame_block(box: list[float], raw, tb_px: list[list[float]],
                         k: float, np, tb_txt: list[str] | None = None) -> bool:
    """带花边的文字框：两条以上题干整行 + 只有边框/小花 → 不是配图。

    真实卷（综合实践单元(1) p2 第 3 题）："路线一…/路线二…" 两行填空指示印在
    一个圆角蓝框里，框里除文字外只有一圈细边框和右下角一朵小花。OCR 行框装不住
    边框，覆盖率 80.9% 够不着 text-block 的 85%，整行就被裁成图从题干里删掉。
    判据（五条同时成立）：
      · 尺寸像一块文字框（60–260pt 宽、15–90pt 高）；
      · ≥2 个 OCR 行框 ≥85% 落在这块里（是整行正文，不是图里短标签）；
      · 其中 ≥2 行是【整句正文】（≥12 个字且带句读，见 _is_prose_row）——
        记录表/表格的标签行没有句读，否则会把 q3 的记录表整块删掉（真实卷实测）；
      · 框外墨 ≤ 总墨 30%（只是一点边角，不是楼/人/路）；
      · 框外的每一团：要么是小装饰（≤22pt），要么是一圈贴边的细框（fill ≤0.25）。
    反例：图里有两个整行文字、另外还有一栋实心楼（fill 高）→ 保留；
          表格的内部横线不贴裁框边 → 保留；只有两行表格标签 → 保留。
    """
    if raw is None or not tb_px:
        return False
    w_pt, h_pt = (box[2] - box[0]) / k, (box[3] - box[1]) / k
    if not (60.0 <= w_pt <= 260.0 and 15.0 <= h_pt <= 90.0):
        return False
    bx0, by0 = max(0, int(box[0])), max(0, int(box[1]))
    bx1, by1 = min(raw.shape[1], int(box[2])), min(raw.shape[0], int(box[3]))
    if bx1 - bx0 < 8 or by1 - by0 < 8:
        return False
    # 没拿到 OCR 原文就当作"证不出是文字框"：宁可留一张图，也不删错记录表。
    if not tb_txt or len(tb_txt) != len(tb_px):
        return False
    prose = 0
    inside = np.zeros((by1 - by0, bx1 - bx0), dtype=bool)
    for t, txt in zip(tb_px, tb_txt):
        tw, th = float(t[2] - t[0]), float(t[3] - t[1])
        if tw <= 1 or th <= 1:
            continue
        iw = min(bx1, int(t[2])) - max(bx0, int(t[0]))
        ih = min(by1, int(t[3])) - max(by0, int(t[1]))
        if iw <= 0 or ih <= 0:
            continue
        if (iw * ih) / (tw * th) >= 0.85 and _is_prose_row(txt):
            prose += 1
        a, b = max(int(t[0]) - bx0, 0), min(int(t[2]) - bx0, bx1 - bx0)
        c, d = max(int(t[1]) - by0, 0), min(int(t[3]) - by0, by1 - by0)
        if b > a and d > c:
            inside[c:d, a:b] = True
    # 两条整句正文（prose 只数完全落在框里的行，自然蕴含 rows ≥ 2）。
    if prose < 2:
        return False
    sub = raw[by0:by1, bx0:bx1]
    total = int(sub.sum())
    if total <= 0:
        return False
    out = (sub.astype(bool) & ~inside)
    if int(out.sum()) / float(total) > 0.30:
        return False
    import cv2
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
        out.astype("uint8") * 255, connectivity=8)
    thin_frame = 0
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        cw, ch = w / k, h / k
        if max(cw, ch) <= 22.0:
            continue                                     # 小花/小装饰
        fill = area / float(max(1, w * h))
        # 一圈细框：面积只占外接框一小撮。框可能离裁框边有十几 pt 的留白
        # （真实卷实测框心留白 15pt），所以不能要求它贴着裁框边。
        # 只允许【一圈】：表格的内部横线/竖线也细，但会是一圈以上 → 保留成图。
        if fill <= 0.25 and thin_frame == 0:
            thin_frame += 1
            continue
        return False                                     # 楼/桌子/内部横线：这是真图
    return True


def _is_blank_rule_row(rect: tuple[float, float, float, float], band,
                       k: float, cx0: int, y0: int, np) -> bool:
    """文字挖掉之后只剩两三条长横线 → 是作答横线，不是图。

    `band` 必须是【已经挖过文字】的那一层：这一块的文字本来就会被 OCR 行框盖住，
    残留的字角允许 ≤10pt；要判定的是"除文字外还有什么"。
    """
    if band is None:
        return False
    if (rect[3] - rect[1]) / k > BLANK_RULE_MAX_H_PT:
        return False
    bx0, by0, bx1, by1 = _band_slice(rect, k, cx0, y0, band.shape)
    if bx1 - bx0 < 8 or by1 - by0 < 4:
        return False
    sub = band[by0:by1, bx0:bx1]
    if not sub.any():
        return False
    import cv2
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    w_pt = (bx1 - bx0) / k
    n_lines = 0
    longest = 0.0
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        cw, ch = w / k, h / k
        if ch <= BLANK_RULE_MAX_THICK_PT and cw >= BLANK_RULE_MIN_LINE_PT:
            n_lines += 1
            longest = max(longest, cw)
            continue
        if max(cw, ch) > BLANK_RULE_MAX_OTHER_PT:
            return False                     # 有字/图/表格竖线 → 不是空白横线
    return (BLANK_RULE_MIN_LINES <= n_lines <= BLANK_RULE_MAX_LINES
            and longest >= w_pt * BLANK_RULE_LONG_SHARE)


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
       只吸【贴在图的左右两侧、宽度 ≤ FRAG_MAX_W_PT、且这一侧还没吸过】的那一片。
       整句题干（70–300pt）和"每一侧只吸一片"就是它不吃正文的两道闸。
       ⚠️ 上下两侧不适用 ⑤：正上方那片多半是正文行被切出来的尾巴。真实卷
          第三单元练习题 第 2 页第 3 题，题干第二行最左 44.6pt 的碎片距叶子图
          只有 5.8pt，吸进来后裁框顶从 457.1 抬回 439.9，整行题干又进了图。

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
                if frags:                                 # ⑤ 碎片：只收左右两侧的图注
                    # 上下两侧的碎片不算图注。真实卷反例（第三单元练习题 第 2 页第 3 题）：
                    # 题干第二行"不能用2×4表示的是( ).(填序号)"被 OCR 切成三片，最左一片
                    # 44.6pt 正好落在叶子图上方 5.8pt 处 → 被当图注吸进来，裁框顶从 457.1
                    # 一路抬到 439.9，整行题干又进了图里（用户截图"真图蹭到半行题干字"）。
                    # 图注是标语/气泡，挂在图的左右；正上/正下那是一片正文的尾巴。
                    if side not in ("left", "right"):
                        continue
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


def _extend_bottom_label_row(rect, text_boxes, y_limit: float | None = None):
    """裁框下沿正好从【图自己的短标签行】中间切过 → 把下沿放到标签行底下。

    真实卷（周末作业(1) p1 第 3 题）：四个选项小图共用一行标签
    "？个 ?根 ？元 ?根"，裁框下沿 540.1 落在标签行（535.0–553.7）里 ——
    图上留着半截字，题干里还留着同样一行（人眼看到的就是"重复又不完整"）。

    只认短标签行（≥3 段、每段 ≤3 字、不含句读/括号/下划线），题干末行永远
    不会是这个形状；而且只往下放，不动左右边界、不跨本题区间下界。
    """
    x0, y0, x1, y1 = [float(v) for v in rect]
    bottom = y1
    for tb in text_boxes or []:
        row = (float(tb["x"]), float(tb["y"]),
               float(tb["x"]) + float(tb.get("w") or 0),
               float(tb["y"]) + float(tb.get("h") or 0))
        if not (row[1] < y1 - 0.5 and row[3] > y1 + 2.0):
            continue                                  # 不是"骑在下沿上"的行
        text = str(tb.get("text") or "")
        # 页脚/栏目横幅也不是图注：达标B 两页并排的页脚
        # "199 第三单元达标练习第3页（共4页） … 第4页（共4页） 200"
        # 分成三段后每段都短，会被 _looks_like_label_row 认成标签行，
        # 裁框于是往下一路吃到 623pt，把整条页脚裁进写作格里。
        if is_furniture_text(text):
            continue
        if not _looks_like_label_row(text):
            continue                                  # 题干末行不会被当成标签
        overlap = (max(0.0, min(row[2], x1) - max(row[0], x0))
                   / max(1e-6, row[2] - row[0]))
        if overlap < LABEL_STRADDLE_OVERLAP_MIN:
            continue
        if y_limit is not None and row[3] > float(y_limit) + 1.0:
            continue                                  # 越过本题区间：那是下一题
        bottom = max(bottom, row[3] + 2.0)
    return (x0, y0, x1, bottom) if bottom > y1 else rect


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
                      box: tuple[float, float, float, float],
                      flags: list | None = None) -> tuple[float, float, float, float]:
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
            # 边框条：宽而薄、整条落在图的横向范围内、紧贴框的上沿或下沿。
            # 这是表格/图框自己的底边线被文字洞切断后剩下的那一截 ——
            # 不并回来的话，裁出来的表格缺底边，审计的"切边"也会响。
            pw, ph = p[2] - p[0], p[3] - p[1]
            if (BORDER_STRIP_MIN_H_PT <= ph <= BORDER_STRIP_MAX_H_PT
                    and pw >= (r[2] - r[0]) * BORDER_STRIP_MIN_W_SHARE
                    and p[0] >= r[0] - 3.0 and p[2] <= r[2] + 3.0):
                vgap = max(p[1] - r[3], r[1] - p[3])
                # 允许 2pt 重叠：边框条和主体常常只压住一丝（实测 0.1pt），
                # 那一丝不够"同行"门槛，却正说明它是同一张表的底边。
                if -2.0 <= vgap <= BORDER_STRIP_MAX_GAP_PT:
                    n = (r[0], min(r[1], p[1]), r[2], max(r[3], p[3]))
                    n = (max(n[0], box[0] - 3), max(n[1], box[1] - 3),
                         min(n[2], box[2] + 3), min(n[3], box[3] + 3))
                    if n != r:
                        if flags is not None:
                            flags.append("bottom" if p[1] >= r[3] - 2.0 else "top")
                        r = n
                        changed = True
                        continue
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
    tall = max(r1[3] - r1[1], r2[3] - r2[1])
    if short <= 0 or tall > short * SIDE_STITCH_MAX_H_RATIO:
        return False
    if ov < SIDE_STITCH_MIN_Y_SHARE * tall:
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

    判据要严，三条各挡一类误伤：
      · 高度比 ≤ 1.5 —— 同一张图被挖断的两半高度几乎一样（真卷中缝实测 1.004）；
        而 第三单元练习题 第 2 页第 4 题的答题框行（外扩后 37.7pt 高）和胡萝卜
        货架（74.4pt 高）比值 1.70，不是一张图。早先没有这条，两块的竖直重叠
        有 50.7%，刚过 50% 的重叠关 → 并成一张 459×74 的框，左上角就蹭到了
        "4.(1)一共有多少根胡萝卜?" 那半行题干字（用户截图）。
      · 竖直重叠 ≥【较高那块】的 50% —— 挡"上下本来就是两张图"被并成一张巨框。
        早先只比【较矮】那块，31.7pt 的答题框行被货架 100% 罩住，等于没判。
        重叠加高度比两道一起才把它挡在门外：单看重叠是 50.7%，离阈值只差 0.7 个点，
        单看比值则差 0.2；两条各留一点余量，不靠一个擦边数字。
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
                    if a.get("graphic") or b.get("graphic"):
                        continue          # 整行原图已经是最完整的裁框，不再和别人缝
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


def _drop_contained(cands: list[dict[str, Any]],
                    report: list | None = None) -> list[dict[str, Any]]:
    """同一题里，小框整块落在大框里＝同一张图裁了两遍，只留大框。

    真实卷（第三单元练习题.pdf 第 2 页第 5 题）：蘑菇图把顶部那行补回来之后
    高 109.6pt，右侧答题框（190×67）有 **95.7%** 落在它里面。横向缝合的高度比
    1.63 已超过 SIDE_STITCH_MAX_H_RATIO=1.5（那条是为"答题框行 + 胡萝卜货架"
    定的，不能放），于是两块各自出图：第二张只剩答题框那半截，正是用户截图里
    "多出来一张莫名其妙的图"。

    为什么不是提高高度比：实测放到 1.8 会同时并掉两对不相干的块
    （综合实践单元 ratio=1.52 gap=10；第三单元另一对 ratio=1.75 gap=-198），
    而"罩住"是几何关系，不靠调阈值。两块几乎同大时不互踢（面积比要 ≥1.3），
    免得近似重复的两张真图互相吃掉；跨题的罩住不管（可能真是邻题的图）。
    """
    by: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in cands:
        by.setdefault((int(c["page"]), int(c["q_index"])), []).append(c)
    out: list[dict[str, Any]] = []
    for _key, g in sorted(by.items()):
        keep: list[dict[str, Any]] = []
        for c in sorted(g, key=lambda x: -((x["rect"][2] - x["rect"][0])
                                          * (x["rect"][3] - x["rect"][1]))):
            if c.get("graphic"):
                keep.append(c)          # 整行原图是唯一该留的那张，不许被"罩住"吃掉
                continue
            r = c["rect"]
            area = max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
            swallowed = False
            for k in keep:
                kr = k["rect"]
                karea = max(0.0, kr[2] - kr[0]) * max(0.0, kr[3] - kr[1])
                if area <= 0 or karea < area * CONTAIN_AREA_RATIO:
                    continue
                iw = min(r[2], kr[2]) - max(r[0], kr[0])
                ih = min(r[3], kr[3]) - max(r[1], kr[1])
                if iw <= 0 or ih <= 0:
                    continue
                if iw * ih >= area * CONTAIN_COVER_MIN:
                    swallowed = True
                    break
            if swallowed:
                if report is not None:
                    report.append({"q_index": c["q_index"], "page": c["page"],
                                   "kept": False,
                                   "rect": [round(v, 1) for v in c["rect"]],
                                   "why": "contained"})
                continue
            keep.append(c)
        out += keep
    out.sort(key=lambda x: (x["page"], x["q_index"], x["rect"][1], x["rect"][0]))
    return out


def _drop_shot_fragments(cands: list[dict[str, Any]],
                         shot_rects: dict[tuple[int, int], list[tuple]],
                         report: list | None) -> list[dict[str, Any]]:
    """整题截图已经整框丢掉 → 同一页同一题里纵向落在它范围内的候选是碎片，一起丢。

    真实卷（达标A q1）：截图 [16.4,161.9,361.6,339.2] 里有个 86×46 的
    "míng zi" 答题格，截图没被丢时它由 `_drop_contained` 当"同一张图裁两遍"
    处理；截图先被 L0 丢掉后，它就成了成品里一张没头没尾的空格子图。
    """
    if not shot_rects:
        return cands
    out: list[dict[str, Any]] = []
    for c in cands:
        if not c.get("graphic"):
            r = c["rect"]
            inside = any(
                (min(r[3], sr[3]) - max(r[1], sr[1])) / max(1e-6, r[3] - r[1]) >= 0.80
                and min(r[2], sr[2]) - max(r[0], sr[0]) >= 0.50 * (r[2] - r[0])
                for sr in shot_rects.get((int(c["page"]), int(c["q_index"])), ()))
            if inside:
                if report is not None:
                    report.append({"q_index": c["q_index"], "page": c["page"],
                                   "kept": False,
                                   "rect": [round(v, 1) for v in r],
                                   "why": "contained"})
                continue
        out.append(c)
    return out


def _reclip_stem_after_merge(cands: list[dict[str, Any]],
                             report: list | None) -> list[dict[str, Any]]:
    """横向缝合之后，若上沿又长回到本题题干首行，再按同一判据收一次。

    真实卷（周末作业(1) 第 1 页第 3 题）：先是 [85.6,472.2,…] 的图，随后
    与上面含题号徽标/首行字符的候选 `side-stitch` 成 [85.6,442.4,…]，上沿
    正好盖住「3.下面哪些问题可以用3×4解决？（」整行 → 审计报"含题干"，
    孩子印出来的图顶上还多一行题目。候选阶段已经收过一次上沿，但缝合在它
    之后发生，所以必须按最终形状复检（与 _recheck_merged 同一个道理）。
    """
    out: list[dict[str, Any]] = []
    for c in cands:
        if c.get("graphic"):
            out.append(c)                     # 整行原图故意含文字，不许修边
            continue
        rect = c["rect"]
        cut = _clip_stem_row(rect, c.get("tbs") or [], c.get("ate_rows") or ())
        if (cut != rect and cut[2] - cut[0] >= 8 and cut[3] - cut[1] >= 8):
            c["rect"] = cut
            c["w_pt"] = round(cut[2] - cut[0], 1)
            c["h_pt"] = round(cut[3] - cut[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"],
                               "kept": True,
                               "rect": [round(v, 1) for v in cut],
                               "why": "stem-clipped-final"})
        out.append(c)
    return out


def _recheck_merged(cands: list[dict[str, Any]], report: list | None,
                    np, cv2) -> list[dict[str, Any]]:
    """合并/缝合/吸收之后，按【最终裁框】把文字残影和空白横线再判一次。

    候选阶段那一眼看到的是碎片：`_absorb_row_peers` 把同行的小块并回来之后，
    框子会横着长一大截，形状已经和当初不是一回事了。真实卷里两处都是这样跑掉的：
      · 第三单元练习题 p7 第 2 题：选项文字被 OCR 行框盖住 86%，剩下的字角散成
        几块，被 row-peer 并成一个 82×53 的"图"；
      · 达标B 第 5 题：两条作答横线原本被 thin-horizontal 砍成几段，row-peer
        接起来之后成了 320×38 的框，越过了"矮块只剩横线"的判据。
    这里用同一份 `_scan` 重建 raw / 挖字后的 band / 文字框，再按最终 rect 跑
    G2 与 J4 —— 判据只有一份实现，这里只换量测对象，不另抄阈值。

    ⚠️ 只复检【整块仍在本栏区间内】的框。跨题缝合（_stitch_across_questions）
       允许框越过原题区间，那类框的 tbs 是另一道题的，拿来量覆盖率会误杀。
    """
    out: list[dict[str, Any]] = []
    cache: dict[tuple, Any] = {}          # 同题的多张候选共用一份 _scan（别重复扫整条带）
    for c in cands:
        if c.get("graphic"):
            out.append(c)                 # 整行原图本来就含文字行，复检的"文字残影"尺对它不适用
            continue
        src, rect = c.get("src"), c["rect"]
        band_box = c.get("band") or []
        inside = (len(band_box) == 4
                  and rect[0] >= band_box[0] - 3.0 and rect[1] >= band_box[1] - 3.0
                  and rect[2] <= band_box[2] + 3.0 and rect[3] <= band_box[3] + 3.0)
        if src is None or not inside:
            out.append(c)
            continue
        key = (c["page"], c["q_index"], tuple(band_box))
        if key in cache:
            sgn = cache[key]
        else:
            span = {"q_index": c["q_index"], "page": c["page"], "col": c.get("col", 0),
                    "x0": band_box[0], "y0": band_box[1],
                    "x1": band_box[2], "y1": band_box[3],
                    "text_boxes": c.get("tbs") or []}
            try:
                sgn = _scan(src, span, np, cv2)
            except Exception:
                sgn = None
            cache[key] = sgn
        why = None
        if sgn:
            k, cx0, y0 = sgn["k"], sgn["cx0"], sgn["y0"]
            px = _band_slice(rect, k, cx0, y0, sgn["band"].shape)
            if _is_text_covered_block(list(px), sgn.get("raw"),
                                      sgn.get("tb") or [], k, np):
                why = "text-block-final"
            elif _is_text_frame_block(list(px), sgn.get("raw"),
                                      sgn.get("tb") or [], k, np,
                                      sgn.get("tb_txt")):
                why = "text-frame-final"
            elif _is_blank_rule_row(rect, sgn.get("band"), k, cx0, y0, np):
                why = "answer-rules-final"
            elif _is_answer_circle_row(rect, sgn.get("raw"), k, cx0, y0, np):
                why = "answer-circles-final"
        if why:
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"],
                               "kept": False,
                               "rect": [round(v, 1) for v in rect],
                               "why": why})
            continue
        out.append(c)
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
    if w <= MARGIN_FLUSH_W_PT and (rect[0] <= 2.0 or rect[2] >= page_w - 2.0):
        # 框【齐着物理页边】＝装订线/侧栏被 ±3pt 外扩后顶到边上的那一条。
        # 真正的题图不会正好从 0 开始（±3pt 外扩也碰不到边），九份真卷全量验证过。
        # 60pt 只够挡住干净的装订栏；侧栏色块一旦和横幅/题干碎字连成 88×125
        # 这种复合块就漏了（真实卷见 MARGIN_FLUSH_W_PT 的注释），所以贴边放宽到 100。
        return True
    if w > MARGIN_MAX_W_PT or h < MARGIN_MIN_ASPECT * w:
        return False
    return rect[0] <= MARGIN_EDGE_PT or rect[2] >= page_w - MARGIN_EDGE_PT


def _is_text_cut_strip(rect: tuple[float, float, float, float],
                       page_boxes: list[dict[str, Any]]) -> bool:
    """小框把两整行以上的文字从右边切断 → 文字残片（见常量区 q19 的实测）。"""
    if rect[2] - rect[0] > 90.0 or rect[3] - rect[1] > 50.0:
        return False
    hits = 0
    for tb in page_boxes:
        text = re.sub(r"\s+", "", str(tb.get("text") or ""))
        if len(text) < TEXT_CUT_MIN_CHARS:
            continue
        x0, y0 = float(tb["x"]), float(tb["y"])
        x1, y1 = x0 + float(tb["w"]), y0 + float(tb["h"])
        if y1 <= y0:
            continue
        v = min(rect[3], y1) - max(rect[1], y0)
        if v < TEXT_CUT_MIN_VSHARE * (y1 - y0):
            continue
        if rect[0] <= x0 < rect[2] - 10.0 and x1 > rect[2] + TEXT_CUT_OVER_PT:
            hits += 1
            if hits >= TEXT_CUT_MIN_ROWS:
                return True
    return False


# 很窄的一条（≤20pt）只由多行文字的【行框外字尾】拼成 → 文字残片。
# 真实卷（综合实践单元(1) 第 4 页附加题）：OCR 行框只框到 318/345pt，
# 最右边一列「）面」「长江的」留在框外，被连成 14×38pt 的"图"印在卷面上。
TEXT_EDGE_MAX_W_PT = 20.0
TEXT_EDGE_NEAR_PT = 9.0
TEXT_EDGE_MIN_ROWS = 2
TEXT_EDGE_MIN_CHARS = 6


def _is_text_edge_fragment(rect: tuple[float, float, float, float],
                           page_boxes: list[dict[str, Any]]) -> bool:
    """窄条恰好是两行以上正文的右端字尾 → 文字残片，不是配图。

    判据：
      · 框很窄（≤20pt）、有一定高度（≥16pt，排除单个标点）；
      · 与 ≥2 个正文行框在竖直方向重叠 ≥50%；
      · 这一条位于行框右端附近（距右端 ±9pt）或在行框右端的 20pt 以内。
    只认正文行（≥6 字），短标签/页码不算——避免拿一条真图旁边的短标注凑数。
    """
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w > TEXT_EDGE_MAX_W_PT or h < 16.0:
        return False
    hits = 0
    for tb in page_boxes:
        text = re.sub(r"\s+", "", str(tb.get("text") or ""))
        if len(text) < TEXT_EDGE_MIN_CHARS:
            continue
        x1 = float(tb["x"]) + float(tb.get("w") or 0)
        y0 = float(tb["y"])
        y1 = y0 + float(tb.get("h") or 0)
        if y1 <= y0:
            continue
        v = min(rect[3], y1) - max(rect[1], y0)
        if v < 0.5 * (y1 - y0):
            continue
        near_right = x1 - TEXT_EDGE_NEAR_PT <= rect[0] <= x1 + TEXT_EDGE_NEAR_PT
        inside_tail = (rect[0] < x1 - TEXT_EDGE_NEAR_PT
                       and x1 - rect[0] <= TEXT_EDGE_MAX_W_PT)
        if near_right or inside_tail:
            hits += 1
            if hits >= TEXT_EDGE_MIN_ROWS:
                return True
    return False


def _furniture_row_hits(rect: tuple[float, float, float, float],
                        page_boxes: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    """候选框罩住的【页面家具】文字行：[(y0, y1, 文本)]，按 y 排序。

    只看"像一行字"的框（宽 ≥24pt）且被罩住 ≥ FURNITURE_ROW_COVER_MIN；
    标点、页码两侧的装饰点不算。
    """
    out: list[tuple[float, float, str]] = []
    for tb in page_boxes:
        text = str(tb.get("text") or "")
        if not is_furniture_text(text):
            continue
        bx0, by0 = float(tb["x"]), float(tb["y"])
        bx1, by1 = bx0 + float(tb.get("w") or 0), by0 + float(tb.get("h") or 0)
        if bx1 - bx0 < FURNITURE_ROW_MIN_W_PT or by1 - by0 <= 0:
            continue
        iw = min(rect[2], bx1) - max(rect[0], bx0)
        ih = min(rect[3], by1) - max(rect[1], by0)
        if iw <= 0 or ih <= 0:
            continue
        if (iw * ih) / ((bx1 - bx0) * (by1 - by0)) >= FURNITURE_ROW_COVER_MIN:
            out.append((by0, by1, text))
    out.sort()
    return out


def _furniture_row_cover(rect: tuple[float, float, float, float],
                         page_boxes: list[dict[str, Any]]) -> tuple[float, str]:
    """候选框罩住某一行【页面家具】文字（页脚/扫码广告/栏目横幅）的比例。

    返回 (最大比例, 那行文字)。判据只有一份，见 `_furniture_row_hits`。
    """
    best: tuple[float, str] = (0.0, "")
    for tb in page_boxes:
        text = str(tb.get("text") or "")
        if not is_furniture_text(text):
            continue
        bx0, by0 = float(tb["x"]), float(tb["y"])
        bx1, by1 = bx0 + float(tb.get("w") or 0), by0 + float(tb.get("h") or 0)
        if bx1 - bx0 < FURNITURE_ROW_MIN_W_PT or by1 - by0 <= 0:
            continue
        iw = min(rect[2], bx1) - max(rect[0], bx0)
        ih = min(rect[3], by1) - max(rect[1], by0)
        if iw <= 0 or ih <= 0:
            continue
        share = (iw * ih) / ((bx1 - bx0) * (by1 - by0))
        if share > best[0]:
            best = (share, text)
    return best


def _trim_furniture_rows(rect: tuple[float, float, float, float],
                         page_boxes: list[dict[str, Any]]
                         ) -> tuple[tuple[float, float, float, float] | None, str]:
    """把候选框【贴边】的家具行切掉，留下真正的图；切不干净就返回 (None, "")。

    为什么不能一律整框丢：周末作业(1) 第 1 页第 4 题是操场大图，正下方紧贴
    "智慧加油站"绿色横幅；第 2 页第 3 题同样是桃子/苹果图 + 横幅。整框丢 = 题面
    让孩子"观察下图"，图却没有了（审计直接判"做不了"）。
    判据（两条都满足才切）：
      · 家具行在框的最外 35% 内（贴上沿或下沿）；
      · 切完剩余高度 ≥ max(42pt, 原高 40%) —— 只剩横幅的候选仍然整框丢。
    """
    hits = _furniture_row_hits(rect, page_boxes)
    if not hits:
        return None, ""
    x0, y0, x1, y1 = [float(v) for v in rect]
    h = y1 - y0
    if h <= 0:
        return None, ""
    top, bottom = y0, y1
    for by0, by1, _t in hits:
        cy = (by0 + by1) / 2.0
        if cy - y0 <= h * FURNITURE_TRIM_EDGE:
            top = max(top, by1 + FURNITURE_TRIM_GAP_PT)
        elif y1 - cy <= h * FURNITURE_TRIM_EDGE:
            bottom = min(bottom, by0 - FURNITURE_TRIM_GAP_PT)
        else:
            return None, ""                  # 夹在中间：切不了，交给整框丢弃
    new = (x0, top, x1, bottom)
    if new[3] - new[1] < max(MIN_FIG_PT, h * FURNITURE_TRIM_MIN_KEEP):
        return None, ""
    return new, "furniture-trim"


def _is_qr_block(rect: tuple[float, float, float, float], src, k: float,
                 qr_det) -> bool:
    """近似方块、24–200pt，且 OpenCV 真能识别出二维码 → 页脚扫码图，不是题图。"""
    if qr_det is None:
        return False
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if not (QR_MIN_PT <= w <= QR_MAX_PT and QR_MIN_PT <= h <= QR_MAX_PT):
        return False
    if w / max(1e-6, h) < QR_ASPECT_MIN or h / max(1e-6, w) < QR_ASPECT_MIN:
        return False
    px0 = max(0, int(rect[0] * k))
    py0 = max(0, int(rect[1] * k))
    px1 = min(src.gray.shape[1], int(rect[2] * k))
    py1 = min(src.gray.shape[0], int(rect[3] * k))
    if px1 - px0 < 20 or py1 - py0 < 20:
        return False
    sub = src.gray[py0:py1, px0:px1]
    if float((sub < EDGE_DARK_LEVEL).mean()) < QR_DARK_MIN:
        return False
    try:
        ok, _pts = qr_det.detect(sub)
    except Exception:
        return False
    return bool(ok)


def _ink_comps_pt(src, box: tuple[float, float, float, float], np, cv2
                  ) -> list[dict[str, float]]:
    """页面 pt 矩形里的连通域 → pt 坐标/面积/填充率。只读 src.gray，不改任何状态。"""
    k = DPI_PROBE / 72.0
    x0, y0, x1, y1 = box
    px0 = max(0, int(x0 * k))
    py0 = max(0, int(y0 * k))
    px1 = min(src.gray.shape[1], int(x1 * k))
    py1 = min(src.gray.shape[0], int(y1 * k))
    if px1 - px0 < 5 or py1 - py0 < 5:
        return []
    ink = (src.gray[py0:py1, px0:px1] < src.ink_thr).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(ink, 8)
    out: list[dict[str, float]] = []
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if w < 2 or h < 2:
            continue
        out.append({"x": (px0 + x) / k, "y": (py0 + y) / k,
                    "w": w / k, "h": h / k, "area": float(area),
                    "fill": area / float(max(1, w * h))})
    return out


def _is_inline_icon(c: dict[str, float]) -> bool:
    """"一个汉字大"的实心图标。空心方框/椭圆（作答框）填充率不够，进不来。"""
    w, h = c["w"], c["h"]
    lo, hi = min(w, h), max(w, h)
    return (lo >= GRAPHIC_ICON_MIN_PT and hi <= GRAPHIC_ICON_MAX_PT
            and hi / max(1e-6, lo) <= GRAPHIC_ICON_MAX_ASPECT
            and c["area"] >= GRAPHIC_ICON_MIN_AREA_PX
            and c["fill"] >= GRAPHIC_ICON_FILL_MIN)


def _graphic_equation_block(src, s: dict[str, Any], np, cv2
                            ) -> dict[str, Any] | None:
    """题干行里夹着多个大图标（图形算式）→ 返回整行原图框；不是这种行返回 None。

    只回答"这一行该不该整行成图"，不猜图标是什么、也不重建算式。
    参数与 `_scan` 同源（同一份 src.gray / ink_thr），避免两把尺读两张图。
    """
    tbs = [tb for tb in (s.get("text_boxes") or [])
           if str(tb.get("text") or "").strip()]
    anchor = None
    best = -1.0
    for tb in tbs:
        t = str(tb.get("text") or "")
        if "=" not in t and "＝" not in t:
            continue
        runs = [len(m.group(0)) for m in re.finditer(r"\s{2,}", t)]
        long_runs = [g for g in runs if g >= GRAPHIC_EQ_MIN_GAP]
        if len(long_runs) < GRAPHIC_EQ_MIN_RUNS:
            continue
        score = len(long_runs) * 10.0 + len(t)         # 缺口越多越像；同分取长行
        if score > best:
            best, anchor = score, tb
    if anchor is None:
        return None
    tb = anchor
    tx0, ty0 = float(tb["x"]), float(tb["y"])
    tw, th = float(tb.get("w") or 0), float(tb.get("h") or 0)
    if tw < 40.0 or th < 8.0:
        return None
    # 搜索带：以 OCR 行为中心。向上 24pt 够到图标顶（实测最高 5.4pt）；
    # 向右留 120pt 给 OCR 行框没覆盖到的尾巴（第 31 题"🍅=( )，"在行框外 107pt）。
    box = (max(0.0, tx0 - 8.0), max(0.0, ty0 - 24.0),
           min(src.width_pt, tx0 + tw + GRAPHIC_EQ_TAIL_PT),
           min(src.height_pt, ty0 + th + 24.0))
    comps = _ink_comps_pt(src, box, np, cv2)
    line_icons: list[dict[str, float]] = []
    for c in comps:
        if not _is_inline_icon(c):
            continue
        ov = min(c["y"] + c["h"], ty0 + th) - max(c["y"], ty0)
        if ov < 0.3 * min(c["h"], th):
            continue
        line_icons.append(c)
    if len(line_icons) < GRAPHIC_EQ_MIN_ICONS:
        return None
    ix0 = min(c["x"] for c in line_icons)
    ix1 = max(c["x"] + c["w"] for c in line_icons)
    if ix1 - ix0 < GRAPHIC_EQ_SPREAD_PT:
        return None
    # ── 续行：紧贴下一行、横向上落在图标带附近、且不在任何 OCR 行框里的图标 ──
    #    第 31 题第二行"🥬=( )。"整行只有图标和括号，OCR 一行都没读出来。
    low = max(c["y"] + c["h"] for c in line_icons)
    cont: list[dict[str, float]] = []
    cont_box = (max(0.0, ix0 - 40.0), low + 1.0,
                min(src.width_pt, ix1 + 40.0),
                min(float(s.get("y1") or src.height_pt), low + GRAPHIC_EQ_CONT_PT))
    for c in _ink_comps_pt(src, cont_box, np, cv2):
        if _is_inline_icon(c) and c["y"] >= low + 1.0:
            cont.append(c)
    # ── OCR 行框右边的尾巴：只认与这一行同高的墨，最多 120pt ──
    tail_x1 = tx0 + tw
    for c in comps:
        if c["x"] < tx0 + tw - 1.0 or c["x"] > tx0 + tw + GRAPHIC_EQ_TAIL_PT:
            continue
        ov = min(c["y"] + c["h"], ty0 + th) - max(c["y"], ty0)
        if ov > 0:
            tail_x1 = max(tail_x1, c["x"] + c["w"])
    icons = line_icons + cont
    x0 = max(0.0, min(tx0, min(c["x"] for c in icons)) - 4.0)
    x1 = min(src.width_pt,
             max(tx0 + tw, tail_x1, max(c["x"] + c["w"] for c in icons)) + 4.0)
    y0 = max(0.0, min(c["y"] for c in icons) - 3.0)
    y1 = min(float(s.get("y1") or src.height_pt),
             max(c["y"] + c["h"] for c in icons) + 3.0)
    if y1 - y0 < 20.0 or y1 - y0 > GRAPHIC_EQ_MAX_H_PT:
        return None
    if x1 - x0 < GRAPHIC_EQ_SPREAD_PT:
        return None
    # 块里不许再罩住别的 OCR 行：那说明它吃到了上一题/下一题的正文。
    for other in tbs:
        if other is tb:
            continue
        ox0, oy0 = float(other["x"]), float(other["y"])
        ox1 = ox0 + float(other.get("w") or 0)
        oy1 = oy0 + float(other.get("h") or 0)
        iw = min(x1, ox1) - max(x0, ox0)
        ih = min(y1, oy1) - max(y0, oy0)
        if iw > 0 and ih > 0 and iw * ih >= 0.5 * max(1.0, (ox1 - ox0) * (oy1 - oy0)):
            return None
    return {"rect": (x0, y0, x1, y1), "n_icons": len(icons),
            "n_rows": 1 + (1 if cont else 0), "anchor": tb, "span": s}


TERM_LABEL_RE = re.compile(r"^(?:乘数|因数|被乘数|加数|和|积)$")
TERM_FORM_MAX_GAP_PT = 80.0


def _term_diagram_block(src, s: dict[str, Any]) -> dict[str, Any] | None:
    """算式各部分名称的竖排图（`3 × 7 = 21` 下面用点线拉出「乘数（ ）（ ）（ ）」）
    → 返回整块原图框；不是这种结构返回 None。

    为什么必须整块成图：第三单元练习题 p2 第 1 题，OCR 只读到
    「3            21      读作：(」「:」「乘数」，×、7、=、省略号和括号全丢了。
    这些字符被读丢之后没有任何文本能重建——硬拼只会拼出"3 21 读作:("。
    判据看【结构】而不是看丢了几个字：
      · 有一行是独立的术语标签（「乘数」/「因数」/…）——正常句子不会单独一行只有它；
      · 它上方 80pt 内有一行含「读作」；
      · 两行之间还夹着 ≥1 行（合并后的 `3 21 读作：(` 或单独的冒号）。
    满足才整块裁，且裁框不许盖住本题题干行（否则图文分离会把题干也删了）。
    """
    tbs = [tb for tb in (s.get("text_boxes") or [])
           if str(tb.get("text") or "").strip()]
    labels = [tb for tb in tbs
              if TERM_LABEL_RE.match(re.sub(r"\s+", "", str(tb.get("text") or "")))]
    reads = [tb for tb in tbs if "读作" in str(tb.get("text") or "")]
    if not labels or not reads:
        return None
    best: tuple[float, dict, dict] | None = None
    for lab in labels:
        ly = float(lab["y"]) + float(lab.get("h") or 0)
        for rd in reads:
            gap = float(lab["y"]) - (float(rd["y"]) + float(rd.get("h") or 0))
            if gap < 0 or gap > TERM_FORM_MAX_GAP_PT:
                continue
            if float(lab["x"]) >= float(rd["x"]):
                continue                 # 标签在「读作」左边才是竖排图；其它排布不碰
            # 同一组里越靠下越像标签行；gap 小的优先
            if best is None or gap < best[0]:
                best = (gap, lab, rd)
    if best is None:
        return None
    _gap, lab, rd = best
    # 上面任何一行若压进「读作」这一行（底边越过它的上沿），说明 OCR 行框已经
    # 连成一片，整块裁会把题干行也裁进去 —— 不碰。
    for tb in tbs:
        if tb is rd or tb is lab:
            continue
        if float(tb["y"]) < float(rd["y"]) < float(tb["y"]) + float(tb.get("h") or 0) - 1.0:
            return None
    top = float(rd["y"]) - 3.5
    bottom = float(lab["y"]) + float(lab.get("h") or 0) + 3.0
    members = [tb for tb in tbs
               if float(tb["y"]) >= top - 0.5
               and float(tb["y"]) + float(tb.get("h") or 0) <= bottom + 0.5]
    if len(members) < 3:
        return None                      # 只有标签和读作两行：不是带中缀的竖排图
    x0 = max(float(s.get("x0") or 0.0),
             min(float(tb["x"]) for tb in members) - 4.0)
    x1 = min(float(s.get("x1") or src.width_pt),
             max(float(tb["x"]) + float(tb.get("w") or 0) for tb in members) + 4.0)
    y0 = max(float(s.get("y0") or 0.0), top)
    y1 = min(float(s.get("y1") or src.height_pt), bottom)
    if x1 - x0 < 80.0 or y1 - y0 < 24.0:
        return None
    # 不许把本题题干行整行罩进去（罩进去图文分离会把题干删掉，交白卷）
    for other in tbs:
        if other in members:
            continue
        ox0, oy0 = float(other["x"]), float(other["y"])
        ox1 = ox0 + float(other.get("w") or 0)
        oy1 = oy0 + float(other.get("h") or 0)
        iw = min(x1, ox1) - max(x0, ox0)
        ih = min(y1, oy1) - max(y0, oy0)
        if iw > 0 and ih > 0 and iw * ih >= 0.5 * max(1.0, (ox1 - ox0) * (oy1 - oy0)):
            return None
    return {"rect": (x0, y0, x1, y1), "n_rows": len(members),
            "anchor": lab, "span": s, "kind": "terms"}


MATCH_CUE_RE = re.compile(r"连一连|连起来|画线连")
MATCH_MIN_H_PT = 30.0
MATCH_MIN_INK_FRAC = 0.004
MATCH_ITEM_MAX_CHARS = 80
MATCH_ROW_GAP_PT = 40.0


def _match_layout_block(src, s: dict[str, Any]) -> dict[str, Any] | None:
    """「连一连」的匹配版式 → 整块原图（图 + 算式条目 + 连线空间都在里面）。

    为什么必须整块成图：周末作业(1) p1 第 1 题是两组水果图夹着一排 7 个算式椭圆，
    连线要跨三行。按连通域裁会拆成「两张水果小图 + 一行跑进题干的算式」，
    连线的两端分在两处，孩子根本没法作答；条目并段也是这么来的。

    只在结构明确时接管（宁可退回普通裁图，也不把正文吞进图）：
      · 题干里有一行出现「连一连」；
      · 这行本身没有空位/分值；
      · 它下面再没有空位/分值，也没有超过 80 字的长句（那些是正文，不是条目）；
      · 图文块到下一个断开的墨带就停，绝不把页脚广告/二维码一起裁进来。
    """
    tbs = [tb for tb in (s.get("text_boxes") or [])
           if str(tb.get("text") or "").strip()]
    anchor = None
    for tb in tbs:
        if MATCH_CUE_RE.search(re.sub(r"\s+", "", str(tb.get("text") or ""))):
            anchor = tb
            break
    if anchor is None:
        return None
    ta = re.sub(r"\s+", "", str(anchor.get("text") or ""))
    if re.search(r"[（(]\s*[）)]|[（(]\s*\d+\s*分", ta):
        return None
    top = float(anchor["y"]) + float(anchor.get("h") or 0) + 1.0
    for tb in tbs:
        if float(tb["y"]) < top - 0.5:
            continue
        t = re.sub(r"\s+", "", str(tb.get("text") or ""))
        if re.search(r"[（(]\s*[）)]|[（(]\s*\d+\s*分", t):
            return None
        if len(t) > MATCH_ITEM_MAX_CHARS:
            return None
    x0 = max(0.0, float(s.get("x0") or 0.0))
    x1 = min(float(src.width_pt), float(s.get("x1") or src.width_pt))
    y_limit = min(float(src.height_pt), float(s.get("y1") or src.height_pt))
    if y_limit - top < MATCH_MIN_H_PT or x1 - x0 < 80.0:
        return None
    k = DPI_PROBE / 72.0
    bx0, by0 = max(0, int(x0 * k)), max(0, int(top * k))
    bx1, by1 = min(src.gray.shape[1], int(x1 * k)), min(src.gray.shape[0], int(y_limit * k))
    if bx1 <= bx0 or by1 <= by0:
        return None
    sub = src.gray[by0:by1, bx0:bx1] < src.ink_thr
    if total := int(sub.size):
        if float((sub > 0).sum()) / total < MATCH_MIN_INK_FRAC:
            return None
    else:
        return None
    # 按整行有没有墨把图文切成横带，再把间隔 <40pt 的带并成一块：
    # 水果行、算式行、第二组水果行属于同一题；页脚二维码隔着一大片空白，自然断开。
    rows = [bool(v) for v in sub.any(axis=1)]
    bands: list[list[int]] = []
    start = None
    for i, on in enumerate(rows):
        if on and start is None:
            start = i
        elif not on and start is not None:
            bands.append([start, i])
            start = None
    if start is not None:
        bands.append([start, len(rows)])
    merged: list[list[int]] = []
    for a, b in bands:
        if merged and (a - merged[-1][1]) / k <= MATCH_ROW_GAP_PT:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    if not merged:
        return None
    # 锚点下面所有文字行必须都落进第一块；掉出去＝中间隔着大空白，结构不明确，不接管。
    first_end_pt = top + merged[0][1] / k
    for tb in tbs:
        ty = float(tb["y"])
        if ty >= top - 0.5 and ty > first_end_pt + 0.5:
            return None
    c0, c1 = merged[0]
    seg = sub[c0:c1, :]
    cols = [i for i, v in enumerate(seg.any(axis=0)) if v]
    if not cols:
        return None
    ix0 = x0 + cols[0] / k
    ix1 = x0 + (cols[-1] + 1) / k
    rect = (max(x0, ix0 - 6.0), top,
            min(x1, ix1 + 6.0), min(y_limit, top + c1 / k + 3.0))
    if rect[2] - rect[0] < 80.0 or rect[3] - rect[1] < MATCH_MIN_H_PT:
        return None
    return {"rect": rect, "kind": "match", "anchor": anchor, "span": s}


def _echo_full_sentence(raw: str, stem: str) -> bool:
    """这一行里真有一句 ≥15 字的成句（以。？！结尾），而且题干里原样找得到。"""
    t = re.sub(r"\s+", "", str(raw or ""))
    t = re.sub(r"^\d{1,3}[、.．]", "", t)
    for m in re.finditer(r"[^。！？]+[。！？]", t):
        seg = m.group(0)
        if len(seg) >= ECHO_SENTENCE_MIN_CHARS and seg in stem:
            return True
    return False


def _stem_echo_edit(rect: tuple[float, float, float, float],
                    text_boxes: list[dict[str, Any]],
                    q_text: str, src=None, k: float = 100 / 72.0
                    ) -> tuple[tuple[float, float, float, float] | None, str | None]:
    """整题截图 → 图文分离：切掉题干文字块，只留真正的图形。

    返回 `(新框, None)` / `(原框, None)` / `(None, "stem-screenshot")`。
    只在【裁框盖住了本题第一句成句题干】且还盖住 ≥2 行时动手 ——
    这一条把"整题截图"和"带填空的诗歌/题干盒"分开：
      · 达标A q1：起手句「下面是真真同学…（9分）」在框里 → 整题截图；
      · 达标A q3：起手句「2.用\画去不正确的字。（8分）」在框上方、没被盖住，
        框里只是诗歌和作答括号 → 这是真图，不许动。
    文字块上面或下面必须有 ≥60pt 的干净区域，否则整框不要。
    切上沿时贴着【文字块下方的第一行墨】切（不是固定留 2pt）：达标B q8
    词语提示的墨比 OCR 行框低 1px，留 2pt 会让审计的"切边"仍报 53px。
    """
    stem = re.sub(r"\s+", "", str(q_text or ""))
    if not stem:
        return rect, None
    first: tuple[float, float, float, float] | None = None
    first_raw = ""
    rows: list[tuple[tuple[float, float, float, float], int]] = []
    edge_rows: list[tuple[tuple[float, float, float, float], int]] = []
    for tb in text_boxes or []:
        t = re.sub(r"\s+", "", str(tb.get("text") or ""))
        # 行框常带题号（"2.用\画去不正确的字"），题干已经剥掉题号 ——
        # 不归一化，q3 的起手句就永远匹配不上，第一句会错认成诗歌里的句子。
        t = re.sub(r"^\d{1,3}[、.．]", "", t)
        if len(t) < ECHO_ROW_MIN_CHARS or t not in stem:
            continue
        bb = (float(tb["x"]), float(tb["y"]),
              float(tb["x"]) + float(tb.get("w") or 0),
              float(tb["y"]) + float(tb.get("h") or 0))
        raw = str(tb.get("text") or "")
        if (first is None and len(t) >= ECHO_SENTENCE_MIN_CHARS
                and re.search(r"[。？！]|[（(]\s*[）)]", raw)):
            first = bb
            first_raw = raw
        cov = _covers(rect, bb)
        if cov >= ECHO_ROW_COVER_MIN:
            rows.append((bb, len(t)))
        # 横向被裁框切掉一截的行也算文字块（见 ECHO_ROW_EDGE_MIN）：干净区
        # 要从它下沿量，不能从"整行都在框里"的最后一行量。
        if cov >= ECHO_ROW_EDGE_MIN:
            edge_rows.append((bb, len(t)))
    if first is None or _covers(rect, first) < ECHO_ROW_COVER_MIN:
        return rect, None
    # ⚠️ 起手行还必须是【一整句题干】，不能只是"有括号、够长"：
    #    两张综合实践卷的公园地图与子题并排（竹林/喷泉/游乐场 + 1.喷泉的西面是…），
    #    OCR 把地图标签和子题读成同一行，框住了"（ ）"却拼不出一句完整话。
    #    这两张图的起手行里没有 ≥15 字的成句，而是碎标签 —— 它们是【图】，
    #    扔了就没法判断东西南北。达标A q1 的「下面是真真同学…的故事。」才是截图。
    if not _echo_full_sentence(first_raw, stem):
        return rect, None
    if len(rows) < ECHO_MIN_ROWS:
        return rect, None
    top = min(bb[1] for bb, _n in edge_rows)
    bottom = max(bb[3] for bb, _n in edge_rows)
    regions: list[tuple[str, float, float]] = []
    if top - rect[1] >= ECHO_CLEAN_MIN_PT:
        regions.append(("above", rect[1], top))
    if rect[3] - bottom >= ECHO_CLEAN_MIN_PT:
        regions.append(("below", bottom, rect[3]))
    if not regions:
        return None, "stem-screenshot"
    side, _r0, _r1 = max(regions, key=lambda r: r[2] - r[1])
    new = list(rect)
    if side == "below":
        first_ink = None
        if src is not None:
            g = src.gray
            px0 = max(0, int(rect[0] * k))
            px1 = min(g.shape[1], int(rect[2] * k))
            py0 = max(0, int(bottom * k))
            py1 = min(g.shape[0], int(rect[3] * k) + 1)
            if px1 > px0 and py1 > py0:
                counts = (g[py0:py1, px0:px1] < src.ink_thr).sum(axis=1)
                for i, c in enumerate(counts):
                    if c >= 2:
                        first_ink = (py0 + i) / k
                        break
        new[1] = max(bottom + 1.0,
                     (first_ink - 1.0) if first_ink is not None else bottom + ECHO_TRIM_GAP_PT)
    else:
        new[3] = top - ECHO_TRIM_GAP_PT
    if new[3] - new[1] < ECHO_CLEAN_MIN_PT:
        return None, "stem-screenshot"
    new_t = (new[0], new[1], new[2], new[3])
    # 剩下的区域里不许再整行盖住题干 —— 那说明切错了地方，宁可整框不要
    for bb, _n in rows:
        if _covers(new_t, bb) >= ECHO_ROW_COVER_MIN:
            return None, "stem-screenshot"
    return new_t, "stem-trim"


def _extend_edge_ink(rect: tuple[float, float, float, float], src,
                     k: float, np, side: str, wall_pt: float) -> tuple[float, float, float, float]:
    """栏界把图切断了：把从框边起【连续有墨】的条带接回来（最多 40pt）。

    只用于图→页边（隔壁栏没有题）的方向；有题的那一栏仍是硬墙。
    实测：达标B q8 写作格的右框线在 820.1pt，栏界 810.9pt，
    裁框停在 813.7pt，审计报"右+2795px"（7 行横线 + 竖框线全被切掉 6pt）。
    ⚠️ 窄条（<60pt）不接：达标A q1 左边 38pt 宽的页边装饰被接宽后
       长宽比从 1.77 掉到 1.35，绕过了"装订栏"判据，垃圾条留了下来。
    """
    if rect[2] - rect[0] < 60.0:
        return rect
    g = src.gray
    h, w = g.shape
    py0 = max(0, int(rect[1] * k))
    py1 = min(h, int(rect[3] * k + 0.999))
    if py1 - py0 < 4 or w <= 0:
        return rect
    dark = g[py0:py1] < src.ink_thr
    if side == "right":
        start = min(w, int(rect[2] * k + 0.5))
        stop = min(w, int(min(wall_pt, rect[2] + EDGE_EXTEND_MAX_PT) * k))
        if stop <= start:
            return rect
        cols = np.flatnonzero(dark[:, start:stop].any(axis=0))
        if cols.size == 0:
            return rect
        last = -10
        end = -1
        for c in cols:
            c = int(c)
            if end < 0:
                if c > EDGE_EXTEND_GAP_PX + 1:
                    return rect                 # 框边先是空白：不是这张图的延续
                end = c
                last = c
                continue
            if c - last > EDGE_EXTEND_GAP_PX + 1:
                break
            last = c
            end = c
        if end < 0:
            return rect
        new_x = (start + end + 1) / k
        if new_x - rect[2] < 1.0:
            return rect
        return (rect[0], rect[1], min(src.width_pt, new_x), rect[3])
    start = max(0, int(rect[0] * k - 0.5))
    stop = max(0, int(max(wall_pt, rect[0] - EDGE_EXTEND_MAX_PT) * k))
    if start <= stop:
        return rect
    cols = np.flatnonzero(dark[:, stop:start].any(axis=0))
    if cols.size == 0:
        return rect
    first = -10
    end = -1
    for c in cols[::-1]:
        c = int(c)
        if end < 0:
            if (start - stop - 1) - c > EDGE_EXTEND_GAP_PX + 1:
                return rect
            end = c
            first = c
            continue
        if first - c > EDGE_EXTEND_GAP_PX + 1:
            break
        first = c
        end = c
    if end < 0:
        return rect
    new_x = (stop + first) / k
    if rect[0] - new_x < 1.0:
        return rect
    return (max(0.0, new_x), rect[1], rect[2], rect[3])


GLYPH_EDGE_MAX_PT = 6.0
GLYPH_EDGE_MAX_H_PT = 16.0


def _extend_cut_glyph(rect: tuple[float, float, float, float], src,
                      k: float, np, side: str = "right",
                      wall_pt: float | None = None) -> tuple[float, float, float, float]:
    """裁框正好从字中间切过：把漏在框外的这一笔接完（最多 6pt）。

    文字掩膜按 OCR 行擦墨，行末的图内标签（"乐乐 龙龙"）常被擦掉大半，
    候选框就停在字中间：打印出来标签只剩半个字（综合实践单元(1) p1 第 4 题，
    右沿 176.5pt，第二个"龙"字在 175.1–179.3pt，被切掉 80%）。
    与 _extend_edge_ink 的分工：那条接的是整栏的图（最长 40pt，窄图不接）；
    这条只补"框边落在墨里"的那一笔，要求：
      · 框边外 1px 内就有墨（否则是正常的外沿空白，不许动）；
      · 这一笔必须在 6pt 内断掉（连续到 6pt 还在＝可能是长横线/整行字，放弃）；
      · 这一笔的高度像字（2–16pt，整条框线/横线不归这条管）。
    """
    x0, y0, x1, y1 = [float(v) for v in rect]
    if side != "right" or x1 - x0 < 8.0:
        return rect
    g = src.gray
    h, w = g.shape
    py0 = max(0, int(y0 * k))
    py1 = min(h, int(y1 * k + 0.999))
    if py1 - py0 < 3 or w <= 0:
        return rect
    dark = g[py0:py1] < src.ink_thr
    start = min(w, int(x1 * k + 0.5))
    stop = min(w, int(min(src.width_pt, x1 + GLYPH_EDGE_MAX_PT) * k) + 1)
    if stop <= start:
        return rect
    cols = np.flatnonzero(dark[:, start:stop].any(axis=0))
    if cols.size == 0:
        return rect
    first = int(cols[0])
    if first > EDGE_EXTEND_GAP_PX + 1:
        return rect                      # 框边先空着：不是切字，是图的外沿
    last = first
    for c in cols[1:]:
        c = int(c)
        if c - last > EDGE_EXTEND_GAP_PX + 1:
            break
        last = c
    ext_pt = (start + last + 1) / k - x1
    if ext_pt >= GLYPH_EDGE_MAX_PT - 0.2:
        return rect                      # 墨一直连到上限：长横线/整行，别接
    # 这一笔的高度：只看切边处那一列，避免把旁边的腿/框线算进来
    edge_rows = np.flatnonzero(dark[:, start + first])
    if edge_rows.size == 0:
        return rect
    h_pt = (int(edge_rows[-1]) - int(edge_rows[0]) + 1) / k
    if not (2.0 <= h_pt <= GLYPH_EDGE_MAX_H_PT):
        return rect
    new_x = (start + last + 1) / k
    if new_x - x1 < 0.5:
        return rect
    if wall_pt is not None and new_x > wall_pt - 0.5:
        return rect
    return (x0, y0, min(src.width_pt, new_x), y1)


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


def _merged_square_units(patch, k: float, cv2, np) -> int:
    """一个连通域里藏着几个【方框内腔】。

    第三单元练习题第 4 题的 `□×□` 被扫描墨迹连成 65.5×25.2pt 一块，外形是减号，
    但内部有两个 ≥8pt 的方洞。只认同时满足下面几条的：
      · 整块矮（≤35pt）且明显横宽（≥1.5 倍高）—— 一行空方框；
      · 洞的短边 ≥8pt、长短边比 ≤2；
      · 洞的面积 ≥其外接框的一半（真的是空腔，不是笔画夹缝）。
    乘法阵列/方格图通常是多行多列，高度先过不了第一条；单行 1×N 方格图若
    只有方框没有别的墨，本来就会被原有"≥2 个方框＋墨占比"判据砍掉，口径一致。
    """
    ph, pw = patch.shape
    if ph <= 0 or pw <= 0:
        return 0
    h_pt, w_pt = ph / k, pw / k
    if h_pt > MERGED_SQUARE_MAX_H_PT or w_pt < h_pt * MERGED_SQUARE_MIN_ASPECT:
        return 0
    contours, hier = cv2.findContours(patch.astype("uint8") * 255,
                                      cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return 0
    n = 0
    for ci, c in enumerate(contours):
        if hier[0][ci][3] == -1:            # 没有父轮廓＝外轮廓，不是洞
            continue
        hx, hy, hw, hh = cv2.boundingRect(c)
        if min(hw, hh) / k < MERGED_SQUARE_MIN_HOLE_PT:
            continue
        if hw <= 0 or hh <= 0 or max(hw, hh) / float(min(hw, hh)) > 2.0:
            continue
        if cv2.contourArea(c) / float(hw * hh) < 0.50:
            continue
        # 洞里也是个【方框】才算：地铁线路图的圆站点内腔是圆的，
        # 用同一把形状分类器挡掉（第一版没挡，淡蓝线路图整张被当答题框砍了）。
        from . import symbols as SY
        hm = np.zeros(patch.shape, dtype="uint8")
        cv2.drawContours(hm, [c], -1, 1, -1)
        hole = hm[hy:hy + hh, hx:hx + hw].astype(bool)
        if SY.classify(SY.features(hole, np)) != "square":
            continue
        n += 1
    return n


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
        patch = sub[y:y + h, x:x + w]
        # 扫描墨把 `□×□` 连成一块时，形状分类器只会叫它 minus；
        # 按内腔数出这一排里有几个方框（见 _merged_square_units）。
        merged = _merged_square_units(patch, k, cv2, np)
        if merged >= MERGED_SQUARE_MIN_HOLES:
            n_sq += merged
            sq_area += area
            continue
        if max(w_pt, h_pt) >= ANSWER_BOX_MAX_OTHER_PT:
            return False                 # 还有一大块别的墨 → 是图的主体
        lab = SY.classify(SY.features(patch, np))
        if lab in SY.SHAPE_LABELS and lab != "square":
            return False                 # 星星/圆/三角/菱形…出来就不是答题框
        if lab == "square" and min(w_pt, h_pt) >= ANSWER_BOX_MIN_PT:
            n_sq += 1
            sq_area += area
    if n_sq < ANSWER_BOX_MIN_SQUARES:
        return False
    return sq_area / float(total) >= ANSWER_BOX_MIN_SHARE


def _round_holes(patch, k: float, cv2, np) -> int:
    """这个墨块里有几个 ≥8pt 的【圆洞】—— 空心圆圈的身份证明。

    只数内腔：实心点没有洞；方框的洞会被形状分类器叫成 square，不算。
    `50-55 ○ 3×9` 那两个作答圈的洞实测 20.9×20.2pt。
    """
    contours, hier = cv2.findContours(patch.astype("uint8") * 255,
                                      cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return 0
    from . import symbols as SY
    n = 0
    for ci, c in enumerate(contours):
        if hier[0][ci][3] == -1:              # 没有父轮廓＝外轮廓，不是洞
            continue
        hx, hy, hw, hh = cv2.boundingRect(c)
        if min(hw, hh) / k < ANSWER_CIRCLE_MIN_HOLE_PT:
            continue
        if hw <= 0 or hh <= 0 or max(hw, hh) / float(min(hw, hh)) > 1.6:
            continue
        if cv2.contourArea(c) / float(hw * hh) < 0.50:
            continue
        hm = np.zeros(patch.shape, dtype="uint8")
        cv2.drawContours(hm, [c], -1, 1, -1)
        hole = hm[hy:hy + hh, hx:hx + hw].astype(bool)
        if SY.classify(SY.features(hole, np)) in ("circle", "ring"):
            n += 1
    return n


def _is_answer_circle_row(rect: tuple[float, float, float, float], raw,
                          k: float, cx0: int, y0: int, np) -> bool:
    """两个空心圆圈夹着算式碎片＝比较大小的作答位置，不是图。

    真实卷（L2 中期评估模拟卷 p1 第 2 题）：42.7×65.7pt 的窄条，里面只有
    `100-55 ○ 100-65` 和 `4×6 ○ 3×9` 留下的两个 22pt 空心圈，外加几块
    5–10.1pt 的算式残角。它和"图形代表数"的图确实长得像，所以全部成立才砍：
      ① 小窄条：宽 ≤60pt、高 ≤90pt、墨密度 ≤15%、总墨 ≤1000pt²；
      ② ≥2 个 12–40pt 的空心圈（必须有 ≥8pt 的圆洞，实心点/方框都不算）；
      ③ 圆圈墨占全框墨 ≥30%；
      ④ 其余墨块都 ≤14pt。
    真图主体、照片、大符号会卡在①或④；实心点阵卡在②。

    ⚠️ 已知不可分辨：一道只用两个圆圈做图的题（例如两枚硬币的示意图）
       也会被砍。与 `□×□` 那条同理，宁可少一张废图。
    """
    if raw is None:
        return False
    if (rect[2] - rect[0] > ANSWER_CIRCLE_MAX_W_PT
            or rect[3] - rect[1] > ANSWER_CIRCLE_MAX_H_PT):
        return False
    px0, py0, px1, py1 = _band_slice(rect, k, cx0, y0, raw.shape)
    sub = raw[py0:py1, px0:px1]
    if sub.size == 0:
        return False
    total = int(sub.sum())
    if total <= 0:
        return False
    if total / float(sub.size) > ANSWER_CIRCLE_MAX_DENSITY:
        return False
    if total / (k * k) > ANSWER_CIRCLE_MAX_INK_PT2:
        return False
    import cv2
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    n_ring, ring_area = 0, 0
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        w_pt, h_pt = w / k, h / k
        patch = sub[y:y + h, x:x + w]
        holes = _round_holes(patch, k, cv2, np)
        if holes >= 1:
            n_ring += 1
            ring_area += area
            continue
        # 外圈不是空心圆时，只允许小残角（算式/标点/×）；更大的墨说明是图的主体。
        # 注：`_round_holes` 已经挡掉了实心点（没洞）和方框（洞是方的）。
        if max(w_pt, h_pt) > ANSWER_CIRCLE_MAX_OTHER_PT:
            return False
    if n_ring < ANSWER_CIRCLE_MIN_RINGS:
        return False
    return ring_area / float(total) >= ANSWER_CIRCLE_MIN_SHARE


def _is_blank_answer_row(rect: tuple[float, float, float, float], raw,
                         k: float, cx0: int, y0: int, np) -> bool:
    """这一块是不是【只有作答括号和虚线引导】的空白行，而不是图。

    第三单元练习题 p2 第 1 题实测 181×49pt：两对 `（ ）` 加两列虚线点，
    墨只占 1.6%，没有任何 ≥18pt 的东西。孩子看到这张"图"就是两个空括号，
    对它做不了题；删掉它，题干里的 `读作:( )` 反而更清楚。
    判据（全部成立才砍，宁窄勿宽）：
      · 高 ≤60pt；
      · 每个 ≥4pt 的墨块都 ≤18pt，且必须是括号；更小的点（虚线）放过；
      · 至少一对括号（这一行先被切成两半时，每半只有一对；缝合后才是两对）；
      · 墨密度 ≤6%，墨面积 ≤500pt²。
    任何一块 ≥18pt 的墨都直接否决 —— 真图、照片、算式主体都过不了这一条。
    """
    if raw is None:
        return False
    if rect[3] - rect[1] > BLANK_ROW_MAX_H_PT:
        return False
    px0, py0, px1, py1 = _band_slice(rect, k, cx0, y0, raw.shape)
    sub = raw[py0:py1, px0:px1]
    if sub.size == 0:
        return False
    total = int(sub.sum())
    if total <= 0:
        return False
    if total / float(sub.size) > BLANK_ROW_MAX_DENSITY:
        return False
    if total / (k * k) > BLANK_ROW_MAX_INK_PT2:
        return False
    import cv2
    from . import symbols as SY
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    n_open = n_close = 0
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        w_pt, h_pt = w / k, h / k
        if max(w_pt, h_pt) > BLANK_ROW_MAX_PIECE_PT:
            return False
        if min(w_pt, h_pt) <= BLANK_ROW_DOT_PT:
            continue                         # 虚线引导点，不是字
        lab = SY.classify(SY.features(sub[y:y + h, x:x + w], np))
        if lab not in BLANK_ROW_ALLOWED:
            return False                     # 有非括号的实墨 → 这不是空白行
        if lab == "paren_open":
            n_open += 1
        else:
            n_close += 1
    return min(n_open, n_close) >= BLANK_ROW_MIN_PAREN_PAIRS


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
    if int(sub.sum()) < 12:
        return False
    # 光有墨不算"同一张图被劈开"：两块各自的边框贴上来也会留下一片墨。
    # 必须找到【贯穿接缝】的笔画 —— 同一列在上半块和下半块都有连续竖向墨，
    # 且这样的列要够多（见 SEAM_CROSS_*）。两张独立的图贴在一起只有零星点。
    mid = int(round(yj * k)) - y0
    if mid <= 0 or mid >= sub.shape[0]:
        return False
    top, bot = sub[:mid], sub[mid:]
    cols = 0
    for c in np.flatnonzero(top.any(axis=0) & bot.any(axis=0)):
        if (_max_v_run(top[:, c], np) >= SEAM_CROSS_MIN_RUN_PX
                and _max_v_run(bot[:, c], np) >= SEAM_CROSS_MIN_RUN_PX):
            cols += 1
    need = max(SEAM_CROSS_MIN_COLS, int(round(SEAM_CROSS_WIDTH_SHARE * sub.shape[1])))
    return cols >= need


def _band_share(u, band) -> float:
    """拼出来的图有多少落在某个区间里（纵向 pt 数）。"""
    lo, hi = max(u[1], float(band[1])), min(u[3], float(band[3]))
    return max(0.0, hi - lo)


def _stitch_across_questions(cands: list[dict[str, Any]],
                             report: list | None = None) -> list[dict[str, Any]]:
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
                    if b[3] < r[1]:
                        continue
                    ov = min(r[2], b[2]) - max(r[0], b[0])
                    narrow = min(r[2] - r[0], b[2] - b[0])
                    # 侧栏共享图：地图/平面图贴着栏的左沿，题目分界线【横穿图身】。
                    # 真实卷（综合实践单元(1) p2 第三大题）：84×50 的公园地图被
                    # 第 1、2 题的分界切成 84×39 + 44×17 两块 —— 上半块还被
                    # text-cut 当成"切断文字"丢掉，第 1 题一张图都没有，第 2 题
                    # 只剩一小条。判据只有三条：同一左沿（±2pt）、后一块整个落在
                    # 前一块的 x 范围内、纵向是【交叠】而不是只贴边。
                    same_left = (abs(r[0] - b[0]) <= 2.0
                                 and b[2] <= r[2] + 1.0
                                 and (b[2] - b[0]) >= 0.35 * max(1.0, r[2] - r[0]))
                    band_bottom = float((own_band or r)[3])
                    strip_below = (same_left
                                   and 0.0 < gap <= STITCH_SHARED_GAP_PT
                                   and abs(r[3] - band_bottom) <= 3.0
                                   and (b[3] - b[1]) <= STITCH_SHARED_STRIP_H_PT)
                    if gap > STITCH_GAP_PT and not strip_below:
                        continue
                    if narrow <= 0:
                        continue
                    if not strip_below and ov < narrow * STITCH_MIN_X_SHARE:
                        continue
                    if same_left and (b[1] < r[3] - 2.0 or strip_below):
                        u = [min(r[0], b[0]), min(r[1], b[1]),
                             max(r[2], b[2]), max(r[3], b[3])]
                        if ((u[3] - u[1]) <= STITCH_MAX_UNION_PT
                                and (u[2] - u[0]) <= STITCH_MAX_UNION_PT):
                            # 缝起来的图归【图落在谁区间里更多】那道题 —— 和常规
                            # 缝合同一条规矩。反例（第三单元练习题 p4 第 4 题）：
                            # 4×4 圆点阵的第一行落在上一题区间里，缝完挂在上一题，
                            # 下一题题干写着"在图上圈一圈"却一张图都没有。
                            if (_band_share(u, g[j].get("band") or b)
                                    > _band_share(u, own_band)):
                                qi = g[j]["q_index"]
                                own_band = g[j].get("band") or b
                            r = u
                            used[j] = True
                            grew = True
                            if report is not None:
                                report.append({"q_index": qi, "page": a["page"],
                                               "kept": True,
                                               "rect": [round(v, 1) for v in r],
                                               "why": "side-shared"})
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
                    # 薄片 + 同宽：圆点阵被从两行之间切开的那一类。圆点彼此不连，
                    # 接缝上当然没有"贯穿的笔画"，但一条 25pt 高、和下面一样宽的
                    # 顶行圆点不可能是另一张完整的图（见 STITCH_SLIVER_*）。
                    sliver = (min(r[3] - r[1], b[3] - b[1]) <= STITCH_SLIVER_MAX_PT
                              and narrow / wide >= STITCH_SLIVER_MIN_W_RATIO)
                    if not sliver and not _seam_has_ink(a["src"], tuple(r), tuple(b),
                                                        a["tbs"] + g[j]["tbs"], _np):
                        continue                      # 接缝上没有贯穿笔画＝两张本来分开的图
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


TOP_GROW_MAX_PT = 45.0
TOP_GROW_GAP_PT = 5.0
TOP_GROW_MAX_W_PT = 40.0
TOP_GROW_MAX_H_PT = 40.0
TOP_GROW_CLUSTER_W_PT = 60.0   # 太阳 + 旁边一小段平线实测 46.1pt，40 会把太阳卡掉
TOP_GROW_CLUSTER_H_PT = 40.0
TOP_GROW_TOTAL_PT = 30.0      # 整条规则最多往上长多少（太阳实测 22.5pt）


def _grow_up_small_attached(rect, src, text_boxes, span_y0, np, cv2,
                            floor_top=0.0):
    """裁框贴着本题上沿时，把正上方【紧挨着的小图标】吃进来（太阳/月亮/星星）。

    真实卷（综合实践课.pdf 第 1 页第 1 题）：男孩举手的图在右上角，太阳在他头顶
    上方 1.4pt；题目区间从题干第一行开始，太阳落在区间外，裁出来只剩男孩 ——
    用户原话"太阳被裁在题干上面"。

    ⚠️ 旧的 `_grow_to_ink`（四面都长）已被实测否掉：周末作业切边降了，但第三单元
       配图 57→50、缺图 0→2。这里只长【上方】、只吃【小图标】，五条同时成立：
         · 裁框顶本来就贴着本题上沿（不是图中间）；
         · 正上方那一团墨【单个】≤40×40pt、【合起来】≤60×40pt，且离裁框顶 ≤5pt
           —— 共享地图的楼/人/路是一大片墨，合起来必然超 60，不许吃；
         · 整条规则最多长 30pt，不许连续三轮越拉越高；
         · 不许越过上一题的底边（floor_top），跨题的一律不长大；
         · 墨团不碰【整页】任何 OCR 文字框（原来只传本题的框，
           共享图会把上一题的题干/大题题头吃进图里，实测造成 做不了 2、串题 4）。
       够不着就原样返回；宁可少一个太阳，不再重演"长出去把邻图挤没"。
    """
    if rect[1] > float(span_y0) + 1.0:
        return rect
    k = DPI_PROBE / 72.0
    x0, top, x1, y1 = rect
    width_pt = x1 - x0
    if width_pt < 8 or y1 - top < 8:
        return rect
    tbs = []
    for tb in text_boxes or []:
        tbs.append((float(tb["x"]), float(tb["y"]),
                    float(tb["x"]) + float(tb.get("w") or 0),
                    float(tb["y"]) + float(tb.get("h") or 0)))
    limit = max(0.0, rect[1] - TOP_GROW_TOTAL_PT, float(floor_top or 0.0))
    for _ in range(3):
        yp1 = int(top * k)
        yp0 = max(0, int((top - TOP_GROW_MAX_PT) * k))
        xp0 = max(0, int(x0 * k))
        xp1 = min(src.gray.shape[1], int(x1 * k))
        if yp1 - yp0 < 2 or xp1 - xp0 < 2:
            break
        ink = (src.gray[yp0:yp1, xp0:xp1] < src.ink_thr)
        n, _lab, stats, _cent = cv2.connectedComponentsWithStats(
            ink.astype("uint8") * 255, connectivity=8)
        cands = []
        for i in range(1, n):
            x, y, w, h, area = [int(v) for v in stats[i]]
            if area < 20:
                continue
            cx0, cy0 = (xp0 + x) / k, (yp0 + y) / k
            cx1, cy1 = (xp0 + x + w) / k, (yp0 + y + h) / k
            if cy1 > top + 0.5 or top - cy1 > TOP_GROW_GAP_PT:
                continue
            if (cx1 - cx0) > TOP_GROW_MAX_W_PT or (cy1 - cy0) > TOP_GROW_MAX_H_PT:
                continue
            if h <= 2 and (cx1 - cx0) >= 0.80 * width_pt:
                continue                          # 页眉横线/页脚横线
            box = (cx0, cy0, cx1, cy1)
            if any(_covers(box, t) >= 0.20 for t in tbs):
                continue                          # 碰着 OCR 文字框：不是图
            cands.append(box)
        if not cands:
            break
        # 只吃"一个图标"：候选墨团合起来也得小。共享地图的楼/人/路合起来是一大片，
        # 一旦按最上面那一块去长，就会一路把上一题的图也卷进来（实测 98pt）。
        # ⚠️ 合起来的上限比单个墨团宽（60 vs 40）：真实太阳的圆和旁边一小段墨
        #    （14.4×2.9pt，离上沿 0.7pt）合起来 46.1×20.8pt，按 40 卡会把太阳挡在
        #    框外。60 仍远小于共享地图那一大片，且高度和总长（30pt）都没有放宽。
        ux0 = min(c[0] for c in cands)
        uy0 = min(c[1] for c in cands)
        ux1 = max(c[2] for c in cands)
        uy1 = max(c[3] for c in cands)
        if (ux1 - ux0) > TOP_GROW_CLUSTER_W_PT or (uy1 - uy0) > TOP_GROW_CLUSTER_H_PT:
            break
        new_top = max(0.0, uy0 - 1.0)
        if new_top < limit - 0.001:
            break                                 # 再长就跨题/超总长
        if new_top >= top - 0.5:
            break
        top = new_top
    if top >= rect[1] - 0.5:
        return rect
    return (x0, top, x1, y1)


def _looks_like_label_row(text: str) -> bool:
    """OCR 把几个短标签（人名/气泡/表头）并成一行 —— 这不是题干行。

    真实卷（综合实践单元.pdf 第 1 页第 6 题）：四个气泡被读成
    "兰兰     站在（    )面。            小红"，贴着裁框下沿、贴左沿、带空位、
    ≥8 字 —— 下沿那三条判据全过，旧版把它当末行题干削掉，四个气泡只剩上半截。
    题干行是连续句子/两栏阅读材料；不会由两个以上【不含括号/运算符的短标签】
    拼成。q23 的两栏材料与 q30 的算式空行都只有两段，不会被误拦。
    """
    parts = [p for p in re.split(r"\s{2,}", (text or "").strip()) if p.strip()]
    if len(parts) < 3:
        return False
    short = [p for p in parts
             if len(re.sub(r"\s+", "", p)) <= 3
             and not re.search(r"[（(）)□×＋+－=＝]", p)]
    return len(short) >= 2


def _h_run_cover(gray, y_pt: float, k: float, thr: int, x0: float, x1: float, np) -> float:
    """y 这一行上，横向墨线盖住了 [x0,x1] 的多大比例。

    只认连续墨：汉字笔画在 100dpi 下每字宽 ≈14px，一行字的覆盖率远低于 0.5；
    表格/插图框的边线是整段连续的，实测两条框线覆盖 0.87–0.99。
    """
    rowp = int(round(y_pt * k))
    if rowp < 0 or rowp >= gray.shape[0]:
        return 0.0
    row = gray[rowp] < thr
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    if not len(starts):
        return 0.0
    a = int(max(0, x0 * k))
    b = int(min(gray.shape[1], x1 * k))
    if b <= a:
        return 0.0
    cover = 0
    for s, e in zip(starts, ends):
        cover += max(0, min(int(e), b) - max(int(s), a))
    return cover / float(b - a)


def _row_in_border(src, row, k: float, np) -> bool:
    """这一行字是不是印在一个【闭合边框】里（双栏插图框 / 表格）。

    为什么必须单列：`_clip_stem_row_bottom` 的判据是"整行贴着裁框下沿、从正文
    左边界起排、带空位/句号"—— 图框里的说明行（"倍，一共有__棵白菜。"）每条都中，
    可它属于图，削掉就把插图下半截切走、题干还留着一整行重复。
    真实卷（周末作业(1) p2 第 2 题）：两个绿框的白菜/小兔图，说明行印在框内底部。

    判据只有一条（保守到只会"少削"，不会多削）：行上方 120pt 内有一条横线、
    行下方 12pt 内也有一条横线，两条都横跨这一行宽度的 ≥55% —— 这行在框里，
    不是框外紧跟的题干。真题干行上方是上一行字（覆盖 <0.5），下方没有横线。
    """
    if src is None or src.gray is None:
        return False
    x0, y0, x1, y1 = [float(v) for v in row]
    if x1 - x0 < 12 or src.gray is None:
        return False
    gray, thr = src.gray, src.ink_thr
    cover_b = 0.0
    for yy in range(int(y1) + 1, int(y1 + BORDER_LOOK_DOWN_PT) + 1):
        cover_b = max(cover_b, _h_run_cover(gray, yy, k, thr, x0, x1, np))
    if cover_b < BORDER_COVER_MIN:
        return False
    cover_t = 0.0
    for yy in range(max(0, int(y0 - BORDER_LOOK_UP_PT)), int(y0) - 1):
        cover_t = max(cover_t, _h_run_cover(gray, yy, k, thr, x0, x1, np))
    return cover_t >= BORDER_COVER_MIN


def _clip_stem_row_bottom(rect, text_boxes, absorbed_rows=(), src=None, k=None,
                          np=None):
    """裁框下沿把【本题的题干行】整行盖住 → 把下沿收到这一行的上沿。

    真实卷（第三单元练习题 第 8 页第 30 题）：青蛙跳数轴在上、题干第一段紧贴
    数轴下面，OCR 把这段行框 403.3–422.0 整行划进图，裁框下沿 430.7 ——
    印出来图里抄了半句题目，题干又留着完整的一句（审计 含题干 第 30 题）。

    只认同时满足的行（比上沿那条更紧，因为图底部常有真正的题注）：
      · 行底贴着裁框下沿（±4pt）；
      · 行首从图的左边界起排（≤24pt）—— 图自己的标注从图中间起；
      · 整行 ≥80% 落在框里，≥8 个字，且是成句/带空位（"图1 平面图"这种题注不收）；
      · 不是规则⑤吸回来的图注；收完还得有 ≥8pt 图。
      · 不在【闭合边框】里：框内的说明行是图的一部分（见 _row_in_border）。
    """
    if not text_boxes:
        return rect
    skip = set(absorbed_rows or ())
    first_i = min(range(len(text_boxes)), key=lambda i: float(text_boxes[i]["y"]))
    cut = rect
    while True:
        hits = []
        for i, tb in enumerate(text_boxes):
            if i in skip:
                continue
            row = (float(tb["x"]), float(tb["y"]),
                   float(tb["x"]) + float(tb.get("w") or 0),
                   float(tb["y"]) + float(tb.get("h") or 0))
            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:
                continue                              # 行底不在下沿：图内的字
            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:
                continue                              # 从图中间起句：图自己的标注
            t = str(tb.get("text") or "").strip()
            if len(re.sub(r"\s+", "", t)) < 8:
                continue
            if _looks_like_label_row(t):
                continue                              # 人名/气泡/表头并成一行，不是题干
            if not re.search(r"[。？?]|[（(]\s*[）)]", t):
                continue                              # 成句/带空位，不是"图1"这种题注
            if (src is not None and k and np is not None
                    and _row_in_border(src, row, k, np)):
                continue                              # 印在闭合边框里：图的说明行
            if _covers(cut, row) < STEM_IN_FIG_COVER:
                continue
            hits.append(row)
        if not hits:
            break
        top = min(r[1] for r in hits)
        # 阅读材料/多行题干常一起压在框底：命中行（带句号/空位）往上，
        # 把紧挨着、贴左沿、整行在框里的续行一并收掉（见 STEM_BOTTOM_JOIN_PT）。
        # 不往上收的话，未命中的前几行会留给"图内重复文字"清理，
        # 题干只剩半句（真实卷：三行材料删了两行，"（"没了、"）"还在）。
        while True:
            above = []
            for i, tb in enumerate(text_boxes):
                if i in skip:
                    continue
                row = (float(tb["x"]), float(tb["y"]),
                       float(tb["x"]) + float(tb.get("w") or 0),
                       float(tb["y"]) + float(tb.get("h") or 0))
                if not (top - STEM_BOTTOM_JOIN_PT <= row[3] <= top + 2.0):
                    continue                      # 不是紧挨在上一行
                if row[1] >= top - 0.5:
                    continue                      # 还是当前这一行，没得往上
                if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:
                    continue                      # 从图中间起句：图自己的标注
                if len(re.sub(r"\s+", "", str(tb.get("text") or ""))) < 8:
                    continue
                if _looks_like_label_row(str(tb.get("text") or "")):
                    continue                      # 图里的人名/气泡标签并成一行
                if _covers(cut, row) < STEM_IN_FIG_COVER:
                    continue
                above.append(row)
            if not above:
                break
            nxt = min(r[1] for r in above)
            if nxt >= top - 0.5:
                break
            top = nxt
        new_bottom = min(cut[3], top - 1.0)
        if new_bottom >= cut[3]:
            break
        cut = (cut[0], cut[1], cut[2], new_bottom)
        if cut[3] - cut[1] < 8 or cut[2] - cut[0] < 8:
            return rect                                 # 收完就没图了：宁可重复一行题干
    return cut


def _row_ink_in_rect(src, row, rect, k: float) -> int:
    """文字行与裁框的重叠区里有多少个墨点。

    用于"窄图贴着长题干右下角"：面积覆盖率低不代表框里没字，直接数墨。
    只在 100dpi 探测图上数，12 个点约等于半个汉字，足够把 OCR 行框的空白边
    和"只蹭到行框下沿"分开。
    """
    x0 = max(float(rect[0]), float(row[0]))
    y0 = max(float(rect[1]), float(row[1]))
    x1 = min(float(rect[2]), float(row[2]))
    y1 = min(float(rect[3]), float(row[3]))
    if x1 - x0 < 2.0 or y1 - y0 < 1.0:
        return 0
    H, W = src.gray.shape
    bx0, by0 = max(0, int(x0 * k)), max(0, int(y0 * k))
    bx1, by1 = min(W, int(x1 * k)), min(H, int(y1 * k))
    if bx1 <= bx0 or by1 <= by0:
        return 0
    return int((src.gray[by0:by1, bx0:bx1] < src.ink_thr).sum())


def _clip_stem_row(rect, text_boxes, absorbed_rows=(), src=None, k=None):
    """裁框把【贴着上沿的本题文字行】整行盖住 → 把上沿收到这一行的下沿。

    照片卷/扫描卷上最常见的"图里又抄了一遍题目"：图就印在题干下面，
    而 OCR 的行框和真正的字常有半行错位（实测综合实践单元(1) 第 24 题：
    行框 155.8–161.3，字的墨却落在 157.7，±3pt 外扩后裁框顶到 154.7），
    于是裁出来的图整行框住了"2. 请为2号无人配送车设计一条行驶路线。"。

    ⚠️ 旧版只看【区间第一行】（`min(y)`），所以只治"裁框顶到本题起手句"。
       真实卷 第三单元练习题 第 2 页第 3 题的裁框从【第二行】开始：
       起手句 y407.0–427.1 在裁框上方，裁框顶 436.9 正好压住第二行
       436.7–455.0 → `_covers` 99%，却因为不是第一行而整行留在图里。
       现在改成"找贴着当前上沿、且被裁框盖住 ≥80% 的行"，一行一行往上收。

    四个"不收"的条件，都是宁可留着重复行也不能把图裁残：
      · 这一行是被规则⑤当【图注】吸回来的（气泡"我面向东。"和题干并成一行那种）；
      · 这一行的行框顶已经在裁框顶下方超过 4pt —— 图内部自己的标注行，
        上方一定还有图的墨，不会正好贴着裁框顶；收下去就是切图；
      · 这一行不是本题第一行，行首又离裁框左沿超过 24pt —— 那是图里/图右的
        标注（"开心公园 北""+2+2…""加法算式:"），不是从正文左边界起排的题干行；
      · 收完上沿就不够 8pt 高了。

    ⚠️ 本题【第一行】还有一条单独的例外（周末作业(1) p2 第 3 题实测）：
       题干行 553.5–573.1，裁框上沿 560.0 正好从字中间切过，`_covers` 只有
       0.67，按 80% 的门槛永远收不掉 —— 印出来的图顶上留着半行题干和题号
       徽标。这一行是本题起手句，被上沿从中间切开时【必须】收。
       门槛从 0.8 降到 0.5，但不能再低：只蹭到行框下沿一点点（实测 0.24）时
       框里根本没有字，削这一刀只会把图顶切掉（原始反例见单测）。防误伤还有
       两条：行框顶确实在裁框顶上方（真被切了），且这一行本身像题干
       （≥8 字、带句末标点或空位）—— 图自己的顶部标注通常短、没有这些标点。
    """
    if not text_boxes:
        return rect
    skip = set(absorbed_rows or ())
    first_i = min(range(len(text_boxes)), key=lambda i: float(text_boxes[i]["y"]))
    cut = rect
    while True:
        hits = []
        for i, tb in enumerate(text_boxes):
            if i in skip:
                continue
            row = (float(tb["x"]), float(tb["y"]),
                   float(tb["x"]) + float(tb.get("w") or 0),
                   float(tb["y"]) + float(tb.get("h") or 0))
            if row[1] > cut[1] + STEM_TOP_TOL_PT:
                continue                              # 行框顶在图里面：是图自己的标注
            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:
                continue                              # 从图中间起句：图自己的标注
            cov = _covers(cut, row)
            if cov < STEM_IN_FIG_COVER:
                # 本题第一行被上沿从字中间切开：这行就是题干起手句，必须收。
                # 只认"顶在裁框上方 + 至少一半在框里 + 成句/带空位"的第一行，
                # 图自己的顶部标注挡在门外；只蹭到下沿一点点（cov 0.24）也不收。
                t = str(tb.get("text") or "").strip()
                first_cut = (i == first_i and row[1] < cut[1]
                             and row[3] > cut[1] + 1.0
                             and cov >= 0.50
                             and len(re.sub(r"\s+", "", t)) >= 8
                             and bool(re.search(r"[。？?]|[（(]\s*[）)]", t)))
                # 窄图贴在【一行长题干的右下角】时，面积覆盖率会低到 0.2：
                # 框里明明有"画一画。（6分）"这半行字，却因为"只蹭到一点"放过。
                # 真实卷（综合实践单元(1) p2 第 6 题）：裁框 [301.6,154.7,…]，
                # 题干行 155.8–161.3、横向只重叠 34pt（占整行 26%）。
                # 判据不看面积比例，直接看【重叠区里有没有墨】：有字就收到行下沿。
                # 前提仍是这一行从裁框上方压下来、本身像题干（≥8字且带句读/空位）。
                if not first_cut and src is not None and k:
                    # 题干和图内标签被 OCR 并成一行时，中间一定夹着一大段空白
                    # （"…背靠背夹    我面向东。"）。后段是气泡自己的字，不能
                    # 拿整行去收图顶，否则孩子头顶和气泡一起被切掉。
                    tail_cut = (row[1] <= cut[1] + STEM_TOP_TOL_PT
                                and row[3] > cut[1] + 1.0
                                and not re.search(r"\S[ \t\u3000]{3,}\S", t)
                                and len(re.sub(r"\s+", "", t)) >= 8
                                and bool(re.search(r"[。？?]|[（(]\s*[）)]", t))
                                and _row_ink_in_rect(src, row, cut, k) >= 12)
                    if tail_cut:
                        first_cut = True
                if not first_cut:
                    continue
            hits.append(row)
        if not hits:
            break
        bottom = max(r[3] for r in hits)
        new_top = max(cut[1], bottom + 1.0)
        if new_top <= cut[1]:
            break
        cut = (cut[0], new_top, cut[2], cut[3])
        if cut[3] - cut[1] < 8 or cut[2] - cut[0] < 8:
            return rect                                 # 收完就没图了：宁可重复一行题干
    return cut


RESIDUE_COVER_MIN = 0.90
RESIDUE_EDGE_MIN = 0.70
RESIDUE_EDGE_SLACK_PT = 6.0
RESIDUE_KEEP_FIRST_CHARS = 6


def box_text_patterns(t: str) -> list[str]:
    """OCR 行框的文字在题干里可能长什么样（正则，空白数量不计）。

    行框常把题号也读进来（"2.按要求填一填。"），而拼好的题干已经把题号剥掉；
    不归一化就永远匹配不上起手句。原样和去题号两版都试。
    """
    variants = [t]
    bare = re.sub(r"^\s*\d+\s*[、.．]\s*", "", t).strip()
    if bare and bare != t:
        variants.append(bare)
    return [r"\s*".join(re.escape(p) for p in v.split()) for v in variants if v.strip()]


def residue_covered(rect, box) -> bool:
    """这一行字是不是"基本印在配图框里"，该从题干里删掉。

    主判据仍是面积 ≥90%。但真实卷（综合实践课 p1 第 3 题）有一整行地图标注
    「教学楼 活动室 北 北」只被裁框上沿削掉 3.3pt，覆盖率 0.80 —— 字还印在图里，
    题干却留了同样一行。所以再放宽一档：任何一边超出 ≤6pt 且面积 ≥70% 也算在图内。
    这一档不会误伤图上方真正的题干行：那种行至少半个字高（>8pt）在框外。
    """
    ix0, iy0 = max(rect[0], box[0]), max(rect[1], box[1])
    ix1, iy1 = min(rect[2], box[2]), min(rect[3], box[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    bw = max(1e-6, box[2] - box[0])
    bh = max(1e-6, box[3] - box[1])
    area = (ix1 - ix0) * (iy1 - iy0) / (bw * bh)
    if area >= RESIDUE_COVER_MIN:
        return True
    if area < RESIDUE_EDGE_MIN:
        return False
    out = max(rect[0] - box[0], rect[1] - box[1],
              box[2] - rect[2], box[3] - rect[3], 0.0)
    return out <= RESIDUE_EDGE_SLACK_PT


def _union_cover(rects, box, nx: int = 24, ny: int = 6) -> float:
    """一行字被本题【几张图的并集】盖住多大比例（网格采样）。

    真实卷（周末作业(1) p1 第 3 题）：那行 "？个 ?根 ？元 ?根" 横跨四个选项小图，
    被裁成左右两张图，中间有 12pt 的真空白 —— 单张都到不了 90%，
    可这行字确实整行印在图里。只用并集判"盖住"，不用并集裁图。
    """
    if not rects:
        return 0.0
    x0, y0, x1, y1 = [float(v) for v in box]
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hit = total = 0
    for i in range(nx):
        x = x0 + (i + 0.5) * (x1 - x0) / nx
        for j in range(ny):
            y = y0 + (j + 0.5) * (y1 - y0) / ny
            total += 1
            if any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects):
                hit += 1
    return hit / float(total) if total else 0.0


def _trailing_label_start(text: str) -> int | None:
    """行尾的短图注从第几个字符开始；不是"正文 + 图注"的形状就返回 None。

    真实卷（周末作业(1) p4 第 4 题）：表头 "小笼包蛋糕    油条" 和题干
    "(1)吃小笼包的人数是吃蛋糕的2倍,有多少人" 被 OCR 并成一行。表头在截图里
    已经能读到，题干里再留一遍就是重复。只从行尾往回摘【≥2 段、每段 ≤6 字、
    不含句读/括号/下划线】的碎片；正文里正常的一句话永远拼不出两段这样的尾巴。
    """
    parts = re.split(r"([ \t]{2,})", str(text or ""))
    labels = 0
    first_idx = None
    i = len(parts) - 1
    while i >= 0:
        seg = parts[i]
        if not seg.strip():
            i -= 1
            continue
        s = seg.strip()
        if len(s) > 6 or re.search(r"[。？?！!，,；;：:（）()＿_]", s):
            break
        labels += 1
        first_idx = i
        i -= 2                                    # 跳过前面的空白段
    if labels < 2 or first_idx is None:
        return None
    return sum(len(p) for p in parts[:first_idx])


def _leading_label_tokens(text: str) -> list[str]:
    """混排行行首的短图注：≤4 个汉字、后随 ≥2 个空格。

    真实卷（综合实践单元(1) p2 第 1 题）OCR 行是
    「喷泉      游乐场            是（    )。(4分)」：左边两段是地图标签，
    右边才是题干。整行删掉会丢题干，整行留下又会和图里的标签重复 ——
    只摘行首这几段。
    """
    parts = re.split(r"([ \t]{2,})", str(text or ""))
    labels: list[str] = []
    i = 0
    while i + 2 < len(parts):
        tok = parts[i].strip()
        nxt = parts[i + 2].strip()
        if (not tok or len(tok) > SIDE_LABEL_MAX_CHARS
                or not all("\u4e00" <= ch <= "\u9fff" for ch in tok)
                or not nxt):
            break
        labels.append(tok)
        i += 2
    if not labels or i >= len(parts):
        return []
    rest = "".join(parts[i:])            # 标签之后的整段正文，不是第一个词
    body = re.sub(r"\s+", "", rest)
    if len(body) < SIDE_BODY_MIN_CHARS:
        return []
    # 正文里得有点题目该有的东西（数字/标点）；整行都是图注的不算
    if not re.search(r"[0-9０-９（）()。，,、；;？?！!]", rest):
        return []
    return labels


DIAGRAM_LABEL_MAX_CHARS = 24


def _diagram_label_like(text: str) -> bool:
    """短图注的形状：没有任何句子标点（末尾一个问号/句号除外），总长 ≤24 字。

    真实卷（综合实践单元(1) p1/p2）：地图标签被 OCR 拼进行首/行尾/选项里，
    "①十里堡站            呼家楼金台路?"、"教学楼 ( ↑ 综合楼 体育馆 ↑ 艺术楼"
    都是这个形状。反例是真正的题干：
    - "龙龙面向（ )。" 带作答空位（括号里 ≥2 个空格）→ 不算图注；
    - "体育课上，同学们一开始面向北站立" 有逗号 → 不算；
    - "3.下面是北京地铁部分线路示意图。" 以题号起手 → 不算。
    图注形状只负责"长得像"，是不是真在图里由调用方的几何判据决定。
    """
    raw = str(text or "")
    t = re.sub(r"\s+", "", raw)
    if not t or len(t) > DIAGRAM_LABEL_MAX_CHARS:
        return False
    if not re.search(r"[\u4e00-\u9fff]", t):
        return False
    if re.search(r"[（(]\s*[）)]", raw):
        return False                        # 空作答位 "(    )" 是题干，不是图注
    if re.match(r"^[0-9０-９]{1,2}\s*[.．、]", t):
        return False
    body = re.sub(r"[。？！?！]+$", "", t)
    if re.search(r"[。？！?！；;：:，,、]", body):
        return False
    segs = [x for x in re.split(r"\s+", raw.strip()) if x]
    if not segs:
        return False
    # 地图图注常把多个地名连写成一段（"★光明小学大门▲祥和小区出口"）：
    # 带这类标记符号时按整段 ≤24 字放行，没有符号仍按短段判。
    if re.search(r"[★☆▲△◆◇○●◎]", t):
        return True
    if len(segs) >= 2:
        return max(len(x) for x in segs) <= 8
    return len(segs[0]) <= 12


def _space_runs(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"[ \t]+", str(text or ""))]


def _collapse_space_runs(text: str) -> str:
    """收掉删行留下的长空格，但作答空位的宽度必须留住。

    真实卷（综合实践单元(1) p2 第 2 题）：摘掉续行行首的两个地名后，
    "（     )" 被一并缩成 "（ )"——题干看着没缺字，空位却窄了一半。
    """
    parts = re.split(r"([（(][ \t]{2,}[）)])", str(text or ""))
    return "".join(p if i % 2 else re.sub(r"[ \t]{2,}", " ", p)
                   for i, p in enumerate(parts))


def _cut_before_suffix(seg: str, suffix: str) -> int | None:
    """在题干匹配段里找到行框后缀（图注）之前的切点；找不到返回 None。

    按【后缀全文】对齐，不按字数：行框常带题干已剥掉的题号（"4.如右图…"），
    按字数对齐会多留两个字（实测题干变成"…背靠背夹 我面"）。
    """
    sfx = re.sub(r"\s+", "", str(suffix or ""))
    if not sfx:
        return None
    s = str(seg or "")
    for m in reversed(list(re.finditer(r"[ \t]+", s))):
        if re.sub(r"\s+", "", s[m.end():]) == sfx:
            return m.start()
    return None


def _side_label_cut(text: str, bb: tuple[float, float, float, float],
                    fig: tuple[float, float, float, float],
                    option: bool = False) -> int | None:
    """正文行伸进图框，切在图左沿的空白缝上，只摘缝右边的短图注。

    真实卷（综合实践单元(1) p1/p2）：
    - 选项 "①十里堡站            呼家楼金台路?"：地图在图右侧，后半行是图注；
    - 题干 "4.如右图所示…背靠背夹 我面向东。"：单空格缝正好压着图左沿。
    返回切点（保留 text[:cut]）；形状不像"正文 + 图注"就返回 None。
    """
    bx0, by0, bx1, by1 = bb
    fx0, fy0, fx1, fy1 = fig
    vshare = ((min(by1, fy1) - max(by0, fy0))
              / max(1e-6, by1 - by0))
    if vshare < 0.5:
        return None
    if bx1 <= fx0 + 6.0 or bx0 >= fx0 - 2.0:
        return None                         # 正文没伸进图里 / 整行本来就在图内
    w = max(1e-6, bx1 - bx0)
    best = None
    for a, b in _space_runs(text):
        gx0 = bx0 + w * a / max(1, len(text))
        gx1 = bx0 + w * b / max(1, len(text))
        if not (gx0 - 2.0 <= fx0 <= gx1 + 8.0):
            continue                        # 这条缝没压着图左沿
        prefix = text[:a].rstrip()
        suffix = text[b:].strip()
        if not prefix or not suffix or not _diagram_label_like(suffix):
            continue
        # 切在作答括号里：真实卷（第三单元练习题 p1 第 1 题）
        # "1.一共有(       )个" 的空白缝压着右图左沿，照切会把 ")个" 当图注摘走，
        # 题干成 "1.一共有(" —— 括号残缺。括号里的空白是作答位，不是行间缝。
        if prefix.endswith(("(", "（")) or suffix[:1] in (")", "）"):
            continue
        if len(re.sub(r"\s+", "", suffix)) < 2:
            continue                        # 单字多半是空位后的量词，不是地名
        pn = re.sub(r"\s+", "", prefix)
        if option:
            if not re.match(r"^[①-⑳A-Ha-h]", pn):
                continue
            if len(pn) < 2:
                continue
        else:
            if len(pn) < 4 or not re.search(r"[\u4e00-\u9fff]", prefix):
                continue
        best = b
    return best


def _diagram_row_hit(bb: tuple[float, float, float, float], text: str,
                     fig: tuple[float, float, float, float]) -> bool:
    """整行都在图框里、且长得像图注：这一行不是题干，是图里被 OCR 读出来的字。

    真实卷（综合实践单元(1) p1 第 3 题）：裁框上沿切进"教学楼 综合楼 体育馆
    艺术楼"这一行的 64%，整行仍被留在题干里 —— 图上已经印着同样的字。
    只认横向也整行落在图框内（左右各留 2pt）；框外的题干行不许按这条删。
    """
    bx0, by0, bx1, by1 = bb
    fx0, fy0, fx1, fy1 = fig
    if by1 - by0 > 14.0 or not _diagram_label_like(text):
        return False
    vshare = ((min(by1, fy1) - max(by0, fy0))
              / max(1e-6, by1 - by0))
    if vshare < 0.45:
        return False
    return bx0 >= fx0 - 2.0 and bx1 <= fx1 + 2.0


def _strip_side_labels_from_options(q: dict[str, Any],
                                    boxes: list[dict[str, Any]],
                                    rects: list[tuple[float, float, float, float]]) -> int:
    """选项行伸进图框：把图里那截短标签从选项里摘掉，返回改了几条。

    只处理"一个选项 = 一个 OCR 行框"的题（归一化后逐字相等）：选项被拆自同一行时
    没有各自的坐标，按几何切会把别的选项一起切掉，宁可不动。
    """
    opts = q.get("options") or []
    n = 0
    for oi, opt in enumerate(list(opts)):
        on = re.sub(r"\s+", "", str(opt or ""))
        if not on:
            continue
        hit = None
        for b in boxes:
            bt = str(b.get("text") or "")
            if re.sub(r"\s+", "", bt) == on:
                hit = b
                break
        if hit is None:
            continue
        bt = str(hit.get("text") or "")
        bb = (float(hit["x"]), float(hit["y"]),
              float(hit["x"]) + float(hit.get("w") or 0),
              float(hit["y"]) + float(hit.get("h") or 0))
        cut = None
        for r in rects:
            cut = _side_label_cut(bt, bb, r, option=True)
            if cut is not None:
                break
        if cut is None:
            continue
        new = re.sub(r"[ \t]{2,}", " ", bt[:cut].rstrip()).strip()
        if len(re.sub(r"\s+", "", new)) < 2:
            continue
        if new != str(opt):
            opts[oi] = new
            n += 1
    return n


DIAGRAM_GROW_MAX_PT = 60.0
DIAGRAM_GROW_GAP_PT = 3.5


CROSS_GRAZE_MAX_PT = 12.0
CROSS_GRAZE_MAX_FRAC = 0.25


def _trim_cross_question_graze(cands: list[dict[str, Any]],
                               report: list | None = None) -> list[dict[str, Any]]:
    """相邻两题的图只在边上蹭进几个点：把上面那题的底沿收回来。

    真实卷（综合实践单元(1) p1 第 3/4 题）：记录单的框底和下一题"两名同学"
    的图只隔 1.5pt，缝合把两个人的头顶并进了上一题的图里 —— 印出来表格底下
    多出两个半截黑头。横竖都重叠、但只蹭进 ≤12pt 且不超过较矮一图高度的 1/4，
    说明不是共享图（共享图会被整块罩住或大段重叠），收回上题底沿即可。
    """
    by_page: dict[int, list[dict[str, Any]]] = {}
    for c in cands:
        by_page.setdefault(int(c["page"]), []).append(c)
    for _page, g in by_page.items():
        g.sort(key=lambda c: float(c["rect"][1]))
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                if int(a["q_index"]) == int(b["q_index"]):
                    continue
                if a.get("border_strip"):
                    # 底沿是刚并进来的表格边框，不是邻题的人头；削了就把框线切断
                    continue
                ar, br = a["rect"], b["rect"]
                ah = ar[3] - ar[1]
                bh = br[3] - br[1]
                iw = min(ar[2], br[2]) - max(ar[0], br[0])
                ih = min(ar[3], br[3]) - max(ar[1], br[1])
                if iw <= 0 or ih <= 0:
                    continue
                if ih > CROSS_GRAZE_MAX_PT or ih > min(ah, bh) * CROSS_GRAZE_MAX_FRAC:
                    continue
                if iw < min(ar[2] - ar[0], br[2] - br[0]) * 0.5:
                    continue
                new_bottom = br[1] - 0.5
                if new_bottom - ar[1] < 12.0 or new_bottom >= ar[3]:
                    continue
                a["rect"] = (ar[0], ar[1], ar[2], new_bottom)
                a["w_pt"] = round(a["rect"][2] - a["rect"][0], 1)
                a["h_pt"] = round(a["rect"][3] - a["rect"][1], 1)
                if report is not None:
                    report.append({"q_index": a["q_index"], "page": a["page"],
                                   "kept": True,
                                   "rect": [round(v, 1) for v in a["rect"]],
                                   "why": "cross-graze"})
    return cands


def _grow_over_cut_label_rows(rect: tuple[float, float, float, float],
                              text_boxes: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """框上沿从一行图注中间切过去时，把这一行连同紧挨着的图注行并进图里。

    真实卷（综合实践单元(1) p1 第 3 题）：记录单的裁框上沿从"体育馆（东）
    综合楼"这一行的 64% 处切过，表头"小亮的记录单/小丽的记录单"也留在框外。
    结果题干里留着这串字、图里只印出下半截字 —— 同一行被劈成两半。
    这里只向上长到【整行短图注】的外沿，遇到正文（带逗号/句号/空位）就停；
    最多长 60pt，避免把上一题的正文吞进图里。
    """
    x0, y0, x1, y1 = [float(v) for v in rect]
    rows: list[tuple[float, float]] = []
    for tb in text_boxes or []:
        t = str(tb.get("text") or "")
        by0 = float(tb["y"])
        by1 = by0 + float(tb.get("h") or 0)
        if by1 - by0 <= 0.5 or by1 - by0 > 14.0:
            continue
        bx0 = float(tb["x"])
        bx1 = bx0 + float(tb.get("w") or 0)
        if bx0 < x0 - 2.0 or bx1 > x1 + 2.0:
            continue                       # 行伸出框外：不是图注，是正文
        if not _diagram_label_like(t):
            continue
        rows.append((by0, by1))
    if not rows:
        return rect
    cut = [a for a, b in rows if a + 0.5 < y0 < b - 0.5]
    if not cut:
        return rect
    top = min(cut)
    moved = True
    while moved:
        moved = False
        for a, b in rows:
            if a < top - 0.5 and 0.0 <= top - b <= DIAGRAM_GROW_GAP_PT:
                top = a
                moved = True
    if not (0.0 < y0 - top <= DIAGRAM_GROW_MAX_PT):
        return rect
    return (x0, top, x1, y1)


def _trim_sliver_text_rows(rect: tuple[float, float, float, float],
                           text_boxes: list[dict[str, Any]],
                           src, np, k: float) -> tuple[float, float, float, float]:
    """框的上/下沿只切到一行文字的 1–2pt 时，把沿收到行外。

    真实卷：综合实践单元(1) p2 第 1 题的裁框上沿切进大题题头 1.5pt、下沿切进
    下一题起手句 1.3pt —— 印出来图顶上一条半个字、底下一条半个字，既重复又难看。
    p1 第 5 题同一现象但更深：下一题起手句被切掉 2.7/5.5pt，而且这行从框左沿
    外伸进来。所以判"半个字"分两档：普通行 45% 行高，起于框左沿外的长正文行
    60%；两种情况都要行外先空出一线空白（SIDE_SPLIT_GAP_PT）才收 —— 图自己
    紧贴剪裁沿的标签行不会被切。
    """
    x0, y0, x1, y1 = [float(v) for v in rect]
    if not text_boxes:
        return rect
    px0 = max(0, int(round(x0 * k)))
    py0 = max(0, int(round(y0 * k)))
    px1 = min(src.gray.shape[1], int(round(x1 * k)))
    py1 = min(src.gray.shape[0], int(round(y1 * k)))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return rect
    ink = src.gray[py0:py1, px0:px1] < int(getattr(src, "ink_thr", 160) or 160)
    row_ink = ink.any(axis=1)
    top, bottom = y0, y1
    for tb in text_boxes or []:
        t = re.sub(r"\s+", "", str(tb.get("text") or ""))
        if len(t) < 8:
            continue
        bx0 = float(tb["x"])
        bx1 = bx0 + float(tb.get("w") or 0)
        if bx1 <= x0 + 2.0 or bx0 >= x1 - 4.0:
            continue                       # 整行都在图里的标注不归这条管
        by0 = float(tb["y"])
        by1 = by0 + float(tb.get("h") or 0)
        h = max(1e-6, by1 - by0)
        ov = min(y1, by1) - max(y0, by0)
        limit = (SLIVER_ROW_CROSS_LEFT_FRAC if bx0 < x0 + 2.0
                 else SLIVER_ROW_FRAC)
        if not (0.0 < ov < limit * h):
            continue
        if by1 <= y0 + limit * h:
            # 框上沿切到这一行的下半截：行下方先空出一线空白才收
            iy = max(0, min(len(row_ink), int(round((by1 - y0) * k))))
            nxt = next((i for i in range(iy, len(row_ink)) if row_ink[i]), None)
            if nxt is None or (nxt - iy) / k >= SIDE_SPLIT_GAP_PT:
                top = max(top, by1 + 0.5)
        elif by0 >= y1 - limit * h:
            # 框下沿切到这一行的上半截：行上方先空出一线空白才收
            iy = max(0, min(len(row_ink), int(round((by0 - y0) * k))))
            prev = next((i for i in range(iy - 1, -1, -1) if row_ink[i]), None)
            if prev is None or (iy - 1 - prev) / k >= SIDE_SPLIT_GAP_PT:
                bottom = min(bottom, by0 - 0.5)
    if bottom - top < 12.0:
        return rect
    return (x0, top, x1, bottom)


def _row_body_start(tb: dict[str, Any], src, np, k: float,
                    x0: float, x1: float) -> float | None:
    """一行里【图注】与【正文】之间那条最宽的空白，右缘就是正文起点。

    真实卷（综合实践单元(1) p2 第 1 题）：OCR 把地图标签和题干拼成一行
    「莲池      假山            2.莲池在凉亭的（     )面，在」；标签和正文
    之间空 24pt，正文括号里最宽也只空 11pt。按最宽空白取，才能停在
    「2.」之前而不是切进句子中间（之前取“最右的贯通缝”，一直切到 132.4，
    把「2.莲池在」也裁进了图里）。
    """
    by0 = float(tb["y"])
    by1 = by0 + float(tb.get("h") or 0)
    if by1 - by0 < 2.0:
        return None
    px0 = max(0, int(round(x0 * k)))
    px1 = min(src.gray.shape[1], int(round(x1 * k)))
    py0 = max(0, int(round((by0 + 0.5) * k)))
    py1 = min(src.gray.shape[0], int(round((by1 - 0.5) * k)))
    if px1 - px0 < 4 or py1 - py0 < 2:
        return None
    ink = src.gray[py0:py1, px0:px1] < int(getattr(src, "ink_thr", 160) or 160)
    col = ink.sum(axis=0)
    gaps: list[tuple[int, int]] = []
    st = None
    for i, v in enumerate(col):
        if v == 0 and st is None:
            st = i
        elif v != 0 and st is not None:
            gaps.append((st, i))
            st = None
    if st is not None:
        gaps.append((st, len(col)))
    edge = max(2, int(round(1.0 * k)))
    cand = []
    for a, b in gaps:
        if a <= edge or b >= len(col) - edge:
            continue                       # 贴着框沿的空隙不是图注/正文分界
        if (b - a) / k < 8.0:
            continue
        cand.append((b - a, a, b))
    if not cand:
        return None
    _, _a, b = max(cand)
    return x0 + b / k


def _is_whole_question_screenshot(rect: tuple[float, float, float, float]) -> bool:
    """这块候选够不够高，像不像"整道题被拍进一张图"。

    只回答高度：横向切半、气泡/说明框这类矮块另有 L/L2b 处理，
    不能因为 L0 的整题截图判据把并排的方格图一起丢掉（见常量注释）。
    """
    return rect[3] - rect[1] >= STEM_SCREENSHOT_MIN_H_PT


def _is_page_edge_band(rect: tuple[float, float, float, float], src) -> bool:
    """贴物理页边、又矮又宽的【几乎空白】灰带：扫描件的页边/压痕，不是题图。

    真实卷（第三单元达标练习题A，两页并排拍成一张图）：左页底边 26pt 高的
    灰色压痕被当成第 3 题的配图，裁出来是一条几乎空白的横带，审计另报
    "同一行框外还有墨 右+960px"。它离页底只有 28pt，宽度却占满整栏。

    只看几何会把页顶的真实地图一起砍掉（综合实践单元(1) p1 第 6 题、
    p2 第 19 题的平面图都贴页顶 30pt 内）。压痕的墨是灰雾：实测
    dark<170 占 0.02%，而真图/地图的实笔画占 4% 以上 —— 用墨量分开。
    """
    x0, y0, x1, y1 = rect
    if y1 - y0 > 40.0 or x1 - x0 < 80.0:
        return False
    if not (y1 >= src.height_pt - 30.0 or y0 <= 30.0):
        return False
    gray = getattr(src, "gray", None)
    if gray is None:
        return True                       # 没有像素可查时维持旧判据
    k = DPI_PROBE / 72.0
    px0 = max(0, int(round(x0 * k)))
    px1 = min(gray.shape[1], int(round(x1 * k)))
    py0 = max(0, int(round(y0 * k)))
    py1 = min(gray.shape[0], int(round(y1 * k)))
    if px1 <= px0 or py1 <= py0:
        return True
    sub = gray[py0:py1, px0:px1]
    return float((sub < 170).mean()) <= 0.005


def _seal_column(noise_rows: list[tuple[float, float, float, float]],
                 page_w: float, page_h: float | None = None
                 ) -> list[tuple[float, float, float, float]]:
    """页边竖排密封线的那一列字框（空列表＝没找到）。

    密封线在 OCR 里是【已被丢弃的 margin 单字框】。判三件事：
      · 一列至少 4 个字（综合实践单元(1) p1 第 5 题图右沿的「北/东/大门」
        只凑出 3 个框，按 3 个砍会把「大门」的「门」切掉）；
      · 这些框的 x 要真的挤成一列（±8pt），而不是散在右侧半页的零碎标注；
      · 【纵向要真像一列字】：地图标签也会在页右排成一列 x，但东一个西一个
        （综合实践单元(1) p1：y 37–232 里最大空档 76pt，占页高 26%）。
        真密封列的最大空档只占页高 10% 左右：达标B 62/634、综合实践单元(1)
        p2 27/288。没有 page_h 时这条不生效（只在直接调用的单测里）。
    达标B 是两页并排的照片：密封列在 850–864pt，离页边 36pt，
    旧的"只看页边 30pt 内"完全看不到它，写作格和作答横线就带着
    「勿/答/题」原字裁了出来。
    """
    # 单字框的实际大小随字号走（达标B 实测 6.5–13.7pt 宽、8.6–13.7pt 高），
    # 卡 10pt 会把整列滤到只剩 1 个框，等于没看见密封线。
    boxes = [b for b in (noise_rows or [])
             if b[2] - b[0] <= 16.0 and b[3] - b[1] <= 16.0
             and b[0] >= page_w - 80.0]
    if len(boxes) < 4:
        return []
    boxes.sort(key=lambda b: b[0])
    clusters: list[list[tuple[float, float, float, float]]] = []
    for b in boxes:
        if clusters and abs(b[0] - clusters[-1][-1][0]) <= 8.0:
            clusters[-1].append(b)
        else:
            clusters.append([b])

    def column_like(cl: list[tuple[float, float, float, float]]) -> bool:
        if len(cl) < 4:
            return False
        if page_h is None:
            return True
        ys = sorted(b[1] for b in cl)
        span = max(b[3] for b in cl) - ys[0]
        if span < 0.50 * page_h:
            return False
        gaps = [b - a for a, b in zip(ys, ys[1:])]
        return max(gaps) <= 0.16 * page_h

    good = [cl for cl in clusters if column_like(cl)]
    if not good:
        return []
    best = max(good, key=len)
    return best if len(best) >= 4 else []


def _seal_rule_x(rect: tuple[float, float, float, float], src,
                 seal_left: float, k: float) -> float | None:
    """密封字左边那条竖虚线的 x（没找到＝None）。

    很多卷的密封线是一条【从页顶通到页底】的虚线，密封字在它右边，
    个别字还压在线上（达标B 的「线/答」、综合实践单元的「答」）。
    只按字列左缘切，虚线仍留在图右沿，作答横线的判据会把这条竖线
    当成"图里还有别的东西"，整段作答区就被当配图裁走。

    判据（页边 20pt 内，逐像素列）：
      · 墨只覆盖整页高度的 15%–85% —— 虚线是一段一段的；表格竖线接近 100%；
      · 首末墨点跨整页高度的 ≥60% —— 图框竖边只有图那么高，不会通到页顶页底；
      · 【最大空隙 ≤6pt】—— 这一条是必须的：正文栏里任何一个 x 都会穿过
        好几十行字，覆盖率/跨度都能凑够（综合实践单元(1) p2 的 x=334.8：
        覆盖率 0.15、跨度 198pt，看着像线，其实行距的空隙有 90pt）。
        真虚线实测：达标B x=843 最大空隙 3.6pt、综合实践单元 x=794 也是 3.6pt。
    """
    g = getattr(src, "gray", None)
    if g is None:
        return None
    h, w = g.shape[:2]
    if h < 20 or w < 4:
        return None
    x0 = max(0, int((seal_left - 20.0) * k))
    x1 = min(w, int((seal_left - 0.5) * k))
    y0, y1 = int(h * 0.04), int(h * 0.96)
    if x1 <= x0 + 1 or y1 - y0 < 20:
        return None
    cols = g[y0:y1, x0:x1] < src.ink_thr
    nrows = y1 - y0
    cov = cols.mean(axis=0)
    hits: set[int] = set()
    for i in range(len(cov)):
        c = float(cov[i])
        if not (0.15 <= c <= 0.85):
            continue
        rows = cols[:, i].nonzero()[0]
        if len(rows) < 20:
            continue
        if (rows[-1] - rows[0] + 1) < 0.60 * nrows:
            continue
        if int((rows[1:] - rows[:-1]).max()) > 6.0 * k:
            continue                     # 行距级别的大空隙：这是正文栏，不是虚线
        hits.add(i)
    if not hits:
        return None
    right = max(hits)                    # 紧挨密封字的那一组
    left = right
    while left - 1 in hits:
        left -= 1
    return (x0 + left) / k


def _clip_seal_strip(rect: tuple[float, float, float, float],
                     noise_rows: list[tuple[float, float, float, float]],
                     page_w: float, src=None,
                     k: float = DPI_PROBE / 72.0
                     ) -> tuple[float, float, float, float]:
    """裁框右沿伸进页边竖排密封线 → 收到这一列文字左边。

    真实卷（综合实践单元(1) p2 第 22/23 题）：裁框为了保住方格图右沿收到
    页边 363.7，把「…请勿…答」那列竖排密封字也裁了进来。密封线在 OCR 里
    是【已被丢弃的 margin 单字框】，位置固定在同一列；用它反推左缘，
    比按“离页边多少 pt”硬切稳（不同扫描件留白宽度不一样）。
    只在裁框确实盖住这列字时才切。达标B 的写作格右框线在 843pt、
    密封列在 850pt，切在 849 既保住格线又不带密封字。

    src 给了就再往前找那条页顶到页底的竖虚线（见 _seal_rule_x），
    并把压在线上的密封字整字切掉 —— 否则图右沿会留半截「线/答」。
    """
    col = _seal_column(noise_rows, page_w,
                       getattr(src, "height_pt", None) if src is not None else None)
    if len(col) < 4:
        return rect
    left = min(b[0] for b in col)
    if rect[2] <= left + 0.5:
        return rect
    if not any(_covers(rect, b) >= 0.5 for b in col):
        return rect
    cut = left - 1.0
    if src is not None:
        rx = _seal_rule_x(rect, src, left, k)
        if rx is not None:
            cut = min(cut, rx - 1.0)
            # 压在虚线/字列左沿上的密封单字（达标B 的「线/答」左移 11pt）
            for b in noise_rows or []:
                if (b[2] - b[0] <= 16.0 and b[3] - b[1] <= 16.0
                        and b[1] < rect[3] and b[3] > rect[1]
                        and b[0] < cut <= b[2] + 1.0):
                    cut = min(cut, b[0] - 1.0)
    if cut - rect[0] < 12.0:
        return rect
    return (rect[0], rect[1], cut, rect[3])


def _split_side_text_figure(rect: tuple[float, float, float, float],
                            text_boxes: list[dict[str, Any]],
                            src, np, k: float
                            ) -> tuple[float, float, float, float] | None:
    """裁框把同一行的题干也框进来 → 沿框内的贯通空白竖缝把右沿收回去。

    只看【从框里起、伸到框外 ≥12pt】的正文行；框里只有图注的题不动。
    切点必须落在正文起点之前、又要横穿这一行 —— 纯正文行的“正文起点”就是
    行首，两个条件不可能同时成立，所以自然返回 None（实测 q22/q23 的方格图
    就是这样保住的，不需要额外的“有没有图注”开关）。
    切点取【正文起点之前】最靠右的贯通缝：这样既排掉题干，又能把指北针
    留在图里。之前的“最右缝”会一路切进句子（q12 切到 132.4）。
    """
    x0, y0, x1, y1 = [float(v) for v in rect]
    W, H = x1 - x0, y1 - y0
    if W < SIDE_SPLIT_MIN_W_PT or H < 20.0:
        return None
    rows: list[tuple[float, float, float]] = []
    for tb in text_boxes or []:
        raw = str(tb.get("text") or "")
        t = re.sub(r"\s+", "", raw)
        if len(t) < SIDE_SPLIT_ROW_CHARS:
            continue
        bx0 = float(tb["x"])
        bx1 = bx0 + float(tb.get("w") or 0)
        by0 = float(tb["y"])
        by1 = by0 + float(tb.get("h") or 0)
        if min(y1, by1) - max(y0, by0) < 0.5 * max(1e-6, by1 - by0):
            continue
        if bx0 >= x1 - 4.0 or bx1 <= x0 + 0.30 * W:
            continue
        labels = _leading_label_tokens(raw)
        if labels:
            bs = _row_body_start(tb, src, np, k, x0, x1)
            if bs is None:
                bs = bx0
        else:
            bs = bx0
        rows.append((bx0, bx1, bs))
    if not rows:
        return None
    body_min = min(bs for _bx0, _bx1, bs in rows)
    px0 = max(0, int(round(x0 * k)))
    py0 = max(0, int(round(y0 * k)))
    px1 = min(src.gray.shape[1], int(round(x1 * k)))
    py1 = min(src.gray.shape[0], int(round(y1 * k)))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return None
    ink = src.gray[py0:py1, px0:px1] < int(getattr(src, "ink_thr", 160) or 160)
    col = ink.sum(axis=0)
    total = float(col.sum())
    if total <= 0:
        return None
    min_gap = max(1, int(round(SIDE_SPLIT_GAP_PT * k)))
    gaps: list[tuple[int, int]] = []
    st = None
    for i, v in enumerate(col):
        if v == 0 and st is None:
            st = i
        elif v != 0 and st is not None:
            gaps.append((st, i))
            st = None
    if st is not None:
        gaps.append((st, len(col)))
    best = None
    for a, b in gaps:
        if b - a < min_gap:
            continue
        split = x0 + b / k                  # 缝的右缘＝正文起点：把整条空白留在图里
        if split > body_min + 0.5:
            continue                       # 不许切进正文（缝右缘正好压着首字像素时允许）
        if split - x0 < SIDE_SPLIT_MIN_LEFT * W:
            continue
        if x1 - split < SIDE_SPLIT_MIN_RIGHT * W:
            continue
        if float(col[:b].sum()) < SIDE_SPLIT_LEFT_INK * total:
            continue
        if not any(bx0 < split - 2.0 and bx1 > split + SIDE_TEXT_OVER_PT
                   for bx0, bx1, _bs in rows):
            continue
        best = split                       # 候选缝里取最靠右的那条
    if best is None:
        return None
    out = _trim_sliver_text_rows((x0, y0, best, y1), text_boxes, src, np, k)
    if out[2] - out[0] < 12.0 or out[3] - out[1] < 12.0:
        return None
    return out


def strip_text_inside_figures(qs: list[dict[str, Any]], spans: list[dict[str, Any]],
                              got: dict[int, list[dict[str, Any]]]) -> int:
    """把【已经完全落在本题配图框内】的 OCR 文字从题干里删掉，返回删掉的条数。

    为什么需要：图里的标注（"加法算式:""CL 长长"）会被 OCR 当成正文行，
    先拼进题干；裁图时这些字又被当作图的一部分裁进来 —— 同一句话印两遍。
    判据只有一条：整行文字框 ≥90% 落在【本题自己的】配图框里。部分压住的不动：
    那可能是图上方真正的题干，不能因为蹭到边就删。
    """
    by_q = {int(s.get("q_index", -1)): s for s in spans}
    # 同一页同栏、别的题名下的图。只用来回答"这一行的行首是不是压在图里"，
    # 绝不拿它整行删字：共享地图挂在第 1 题，第 2 题的续行行首照样在图里
    # （综合实践单元(1) p2 第三大题实测）。
    page_col = {int(s.get("q_index", -1)): (int(s.get("page", 1)), int(s.get("col", 0)))
                for s in spans}
    neigh: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    for oi, oimgs in got.items():
        pc = page_col.get(int(oi))
        if pc is None:
            continue
        for im in oimgs:
            if im.get("rect"):
                neigh.setdefault(pc, []).append(tuple(im["rect"]))
    n = 0
    # 共享图只挂第一题：后面那题自己没有图，但续行的行首仍压在同一张图上，
    # 也要按邻图摘掉行首地名。只把有邻图可借的题拉进来，不空跑全卷。
    scope = set(int(x) for x in got)
    for qi, pc in page_col.items():
        if neigh.get(pc):
            scope.add(int(qi))
    for qi in sorted(scope):
        imgs = got.get(qi) or []
        if not (0 <= qi < len(qs)):
            continue
        q = qs[qi]
        text = str(q.get("text") or "")
        if not text.strip():
            continue
        rects = [tuple(im["rect"]) for im in imgs if im.get("rect")]
        # 邻题的图也参与"行首压在图里"的几何判断；只有 side_split 元数据是本题的。
        side_rects = list(imgs)
        for r_ in neigh.get(page_col.get(qi, (-1, -1)), []):
            if all(tuple(x["rect"]) != r_ for x in imgs if x.get("rect")):
                side_rects.append({"rect": r_})
        removed = False
        content_seen = False
        # ⚠️ 必须按【行在题干里的先后】找对应的那一次出现，不能一律删第一处。
        # 真实卷（综合实践课 p1）：「辰辰从( )面走来…」后面还挂着一行图内标签「辰辰」，
        # 删第一处会把句子里的「辰辰」删掉、把标签留在末尾 —— 题干被改坏，残渣还在。
        # 也不能一律删最后一处：地图标签「散通道」在题干里出现过，但最后一句
        # 「紧急疏散通道」里的那三个字是正文，删了就把题改残。
        # 游标按 OCR 行序前进：没被框住的行只把游标推过去，不删。
        cursor = 0
        for b in by_q.get(qi, {}).get("text_boxes") or []:
            t = str(b.get("text") or "").strip()
            if not t:
                continue
            # OCR 两次读出来的空格数量可能不同（行框里是"CL        长长"），
            # 按空白切段再拼成 \s* 才匹配得上；其它字符必须逐字相同。
            # 行框可能带题号（"2.按要求填一填。"），题干已剥题号 —— 不先归一化
            # 就永远匹配不上起手句，content_seen 翻不过来，紧跟其后的单字图注
            # （"北""辰辰"）会被当正文删掉。见 box_text_patterns。
            pats = box_text_patterns(t)
            m = None
            for p in pats:
                m = re.compile(p).search(text, cursor)
                if m:
                    break
            if not m and cursor:
                # 多栏排版时 OCR 行的先后和拼出来的题干先后不一定一致；
                # 游标后面找不到，就退回全文找（否则这一行永远删不掉）。
                for p in pats:
                    m = re.compile(p).search(text)
                    if m:
                        break
            if not m:
                continue
            bb = (float(b["x"]), float(b["y"]),
                  float(b["x"]) + float(b.get("w") or 0),
                  float(b["y"]) + float(b.get("h") or 0))
            # 整行图注：横向也在图框内、上下被框住 ≥45%，且形状就是短标签。
            # 真实卷（综合实践单元(1) p1 第 3 题）：裁框上沿切进图注行 64%，
            # 整行仍留在题干里，图上又印着同样的字 —— 这一行不是题干。
            if any(_diagram_row_hit(bb, t, r) for r in rects):
                cand = text[:m.start()] + text[m.end():]
                if len(re.sub(r"\s+", "", cand)) >= 2:
                    text = cand
                    cursor = m.start()
                    removed = True
                    n += 1
                    continue
            # 单张图 ≥90% 就算在图里；跨几张图的一行用并集判（见 _union_cover）。
            covered = (any(residue_covered(r, bb) for r in rects)
                       or _union_cover(rects, bb) >= RESIDUE_COVER_MIN)
            # 图文同排收窄过的框：这一行是"地图标签 + 题干正文"拼出来的，
            # 从图里起、伸到图外。只摘行首那几段标签，正文必须留在题干里。
            # 真实卷：综合实践单元(1) p2 第 1 题，整行删掉会剩半句题干。
            side = False
            for im in side_rects:
                if not im.get("rect"):
                    continue
                r = im["rect"]
                vshare = ((min(bb[3], r[3]) - max(bb[1], r[1]))
                          / max(1e-6, bb[3] - bb[1]))
                if (im.get("side_split") and vshare >= 0.5
                        and bb[0] < r[2] - 2.0
                        and bb[2] > r[2] + SIDE_TEXT_OVER_PT):
                    side = True
                    break
                # 没标 side_split，但这一行【行首就落在图里、行尾伸到图外】，
                # 开头又是 1–3 段短标签：图里印着"凉亭            假山的（ )面"，
                # 标签和正文被 OCR 拼成一行。只摘行首标签，正文必须留。
                if (vshare >= 0.5 and bb[0] >= r[0] - 2.0
                        and bb[0] < r[2] - 10.0
                        and bb[2] > r[2] + SIDE_TEXT_OVER_PT
                        and _leading_label_tokens(t)):
                    side = True
                    break
            if side:
                labels = _leading_label_tokens(t)
                cut, seg = 0, m.group(0)
                for lab in labels:
                    mm = re.match(r"\s*" + re.escape(lab) + r"\s*", seg[cut:])
                    if not mm:
                        cut = 0
                        break
                    cut += mm.end()
                if cut and len(re.sub(r"\s+", "", seg[cut:] + text[m.end():])) >= 2:
                    text = text[:m.start()] + seg[cut:] + text[m.end():]
                    cursor = m.start() + len(seg) - cut
                    removed = True
                    n += 1
                    if len(re.sub(r"\s+", "", t)) >= RESIDUE_KEEP_FIRST_CHARS:
                        content_seen = True
                    continue
            if not covered:
                # 行伸进图框、图左沿正好压在空白缝上：缝右边那截是图注。
                # 真实卷（综合实践单元(1) p1 第 4 题）："…背靠背夹 我面向东。"
                # 图里已经印着"我面向东。"，题干再留一遍就是重复。
                cut = None
                for r in rects:
                    cut = _side_label_cut(t, bb, r, option=False)
                    if cut is not None:
                        break
                if cut:
                    seg = m.group(0)
                    keep = _cut_before_suffix(seg, t[cut:])
                    if keep is None:
                        continue
                    body = seg[:keep].rstrip()
                    if (keep > 0 and len(re.sub(r"\s+", "", body)) >= 4
                            and re.search(r"[\u4e00-\u9fff]", body)):
                        text = text[:m.start()] + body + text[m.end():]
                        cursor = m.start() + len(body)
                        content_seen = True
                        removed = True
                        n += 1
                        continue
                # 题干正文 + 图里的短标签被 OCR 并成一行（图在右）：
                # 只摘行尾那几段标签，正文留在题干（真实卷 p4 第 4 题的表头）。
                cut = _trailing_label_start(t)
                trimmed = False
                if cut:
                    seg = m.group(0)
                    keep = _cut_before_suffix(seg, t[cut:])
                    body = seg[:keep].rstrip() if keep is not None else ""
                    est_x = bb[0] + (bb[2] - bb[0]) * float(keep or 0) / max(1, len(seg))
                    if (keep is not None and keep > 0
                            and len(re.sub(r"\s+", "", body)) >= 8
                            and re.search(r"[\u4e00-\u9fff]", body)):
                        for r in rects:
                            vshare = ((min(bb[3], r[3]) - max(bb[1], r[1]))
                                      / max(1e-6, bb[3] - bb[1]))
                            if (vshare >= 0.5 and bb[0] < r[0] - 24
                                    and est_x >= r[0] - 12
                                    and bb[2] <= r[2] + 12):
                                text = text[:m.start()] + body + text[m.end():]
                                cursor = m.start() + len(body)
                                content_seen = True
                                removed = True
                                trimmed = True
                                n += 1
                                break
                if trimmed:
                    continue
                # 没被图整行盖住的行就是题干正文（可能只蹭到裁框边）。
                # 起手句保护只挡"整行删除"，不挡上面摘行尾图注。
                content_seen = True
                cursor = m.end()
                continue
            # 本题的起手句永远不删 —— 就算裁框把它整行盖住了，题干也得留一句
            # 能看出在问什么的话（真实卷 第三单元 p4 第 3 题：裁框同时盖住了
            # 起手句和"问题一/问题二"标签，全删就成空题）。
            if not content_seen and len(re.sub(r"\s+", "", t)) >= RESIDUE_KEEP_FIRST_CHARS:
                content_seen = True
                cursor = m.end()
                continue
            cand = text[:m.start()] + text[m.end():]
            if len(re.sub(r"\s+", "", cand)) < 2:
                cursor = m.end()
                continue                  # 删完就空了：宁可留残渣，不交白卷
            text = cand
            cursor = m.start()
            removed = True
            n += 1
        # 选项行同样会伸进图框：q3/q4/q5 的选项右边就是地图图注。
        # 题干走上面的逐行游标，选项按"一行一个选项"逐条摘。
        n += _strip_side_labels_from_options(
            q, by_q.get(qi, {}).get("text_boxes") or [], rects)
        if removed:
            text = _collapse_space_runs(text)
            # 删掉图内整行后常留下一个空行（"题干（\n \n选项标签"）：前端和打印
            # 都会把它当成段落间隔，卷面上出现一条没来由的空白。
            text = re.sub(r"\n[ \t]*\n+", "\n", text)
            q["text"] = text.strip()
    return n


def _preamble_is_figure_labels(text: str) -> bool:
    """无题号伪题的文本像不像"图里的标注/图例"，而不是一道真题。

    真实卷（综合实践单元(1) p2）：
      · 第四节开头是地图标注 `8501 8502 … 肉 东北`（数字占八成）→ 是图注；
      · 第五节开头是图例 `①春风小区 ②人民广场 ③长风商城 ④体育馆` → 是图例。
    真题通常有括号空位/分值/问句，这些由调用处的 BLANK/SCORE 判据先挡掉。
    """
    t = re.sub(r"\s+", "", str(text or ""))
    if len(t) < 2:
        return True                            # 空伪题只剩图：更该折
    if len(set(re.findall(r"[①-⑳]", t))) >= 2:
        return True
    digits = sum(ch.isdigit() for ch in t)
    return digits >= 0.4 * len(t)


def fold_figure_preamble_questions(qs: list[dict[str, Any]],
                                   got: dict[int, list[dict[str, Any]]] | None = None,
                                   spans: list[dict[str, Any]] | None = None) -> int:
    """把【图前面那道无题号伪题】折进紧跟其后的真题，返回折掉的条数。

    为什么：地图/图例的标注先被 OCR 拼成一行行"正文"，于是切成一道 q_no=None
    的伪题（"8501 8502…" / "①②③④…"），图挂在这道伪题上。前端会把它当成
    自动编号的"第 1 题"，真正的第 1 题又在下面出现一次 —— 同一大题两道 1，
    孩子分不清哪道要答。

    只在四条同时成立时折（宁可不折，不许把真题吞掉）：
      · 这道题没有题号（q_no is None），下一道有题号，且在同一大题；
      · 这道题确实挂着配图；
      · 题干没有空位/分值（真题的标志）；
      · 文本像图注/图例（数字占四成以上，或 ≥2 个圈号）。
    折法：图并给下一题；图例文字（≥2 圈号）放到下一题题干最前面；纯数字/标签
    残渣丢掉。got/spans 同步重映射，后续按下标取题的环节不会错位。
    """
    folded = 0
    i = 0
    while i < len(qs) - 1:
        q, nxt = qs[i], qs[i + 1]
        if (q.get("q_no") is not None or nxt.get("q_no") is None
                or q.get("section") != nxt.get("section")):
            i += 1
            continue
        imgs = list(q.get("images") or (got or {}).get(i) or [])
        if not imgs:
            i += 1
            continue
        t = str(q.get("text") or "")
        flat = re.sub(r"\s+", "", t)
        if re.search(r"[（(]\s*[）)]", flat) or re.search(r"[（(]\s*\d+\s*分", flat):
            i += 1
            continue                        # 有空的可能是真题，不折
        if not _preamble_is_figure_labels(t):
            i += 1
            continue
        nxt_imgs = list(nxt.get("images") or (got or {}).get(i + 1) or [])
        seen = {tuple(im.get("rect") or []) for im in nxt_imgs}
        nxt_imgs += [im for im in imgs if tuple(im.get("rect") or []) not in seen]
        nxt["images"] = nxt_imgs
        if re.search(r"[①-⑳]", flat):        # 图例是答题必需的信息，并进题干开头
            body = str(nxt.get("text") or "")
            nxt["text"] = (t.strip() + "\n" + body).strip() if body else t.strip()
        if q.get("source_lines"):
            nxt["source_lines"] = (list(q["source_lines"])
                                   + list(nxt.get("source_lines") or []))
        if q.get("symbols"):
            nxt["symbols"] = list(q["symbols"]) + list(nxt.get("symbols") or [])
        qs.pop(i)
        if got is not None:
            new_got: dict[int, list[dict[str, Any]]] = {}
            for k, v in got.items():
                if k == i:
                    continue
                new_got[k - 1 if k > i else k] = v
            got.clear()
            got.update(new_got)
            got[i] = nxt_imgs
        if spans is not None:
            spans[:] = [s for s in spans if int(s.get("q_index", -1)) != i]
            for s in spans:
                if int(s.get("q_index", -1)) > i:
                    s["q_index"] = int(s["q_index"]) - 1
        folded += 1
        # 不 i+=1：折掉一道后，当前位置可能是同一大题里的另一道伪题
    return folded


def apply_graphic_notes(qs: list[dict[str, Any]],
                        got: dict[int, list[dict[str, Any]]]) -> int:
    """图形算式的整行原图：收掉 OCR 留下的长空格、补一句"图形见下方原图"。

    为什么不能省：第 31 题的 OCR 题干是"如果            =16,            =16,那么"，
    两处 12 个空格就是番茄/黄瓜的位置。不补这句，家长会以为系统把题目弄丢了；
    补了也不冒充"读到了图标"——原图就在下面，孩子看图作答。
    返回补了提示的题数。产品路径（papers.py）和审计渲染共用这一份，别各写一套。
    """
    n = 0
    for qi, imgs in got.items():
        if not (0 <= qi < len(qs)) or not any(im.get("graphic") for im in imgs):
            continue
        t = re.sub(r"[ \t]{2,}", " ", str(qs[qi].get("text") or "")).strip()
        if t:
            kinds = {str(im.get("graphic_kind") or "") for im in imgs
                     if im.get("graphic")}
            if "match" in kinds:
                note = "（连一连的题目见下方原图，请照着原图连线）"
            elif "terms" in kinds:
                note = "（本题算式的各部分名称见下方原图）"
            else:
                note = "（本题算式中的图形见下方原图）"
            qs[qi]["text"] = t + note
            n += 1
    return n


def find_figures(sources: dict[int, PageSource], spans: list[dict[str, Any]],
                 out_dir: str, report: list[dict[str, Any]] | None = None,
                 noise: list[dict[str, Any]] | None = None,
                 questions: list[dict[str, Any]] | None = None
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
      J) 同一题里被另一个更大候选整个罩住的小框是**同一张图裁了两遍**，丢掉
        （见 `_drop_contained`；横向缝合按高度比不并的那类重复裁图）。
      另）候选框的墨绝大多数落在"家具行"里（栏目横幅的色块）→ 不是题图；
          由 ≥2 个空心方框＋运算符组成的矮块是【作答位置】→ 不是图。
    """
    import numpy as np
    try:
        import cv2
    except Exception:                                   # cv2 是硬依赖，缺了也不能拖垮整卷识别
        cv2 = None
    qr_det = None
    if cv2 is not None:
        try:
            qr_det = cv2.QRCodeDetector()
        except Exception:
            qr_det = None

    # 被"太小"砍掉的小块先记下来：同一行里它们多半是式子的一部分
    # （括号、运算符），图框长出来一点比"算式少半个括号"划算得多。见 _absorb_row_peers。
    small_peers: dict[tuple[int, int], list] = {}
    # 整题截图被丢掉的框：同一页同一题里落在它纵向范围内的其它候选都是这张
    # 截图里的碎片（达标A q1 的 "míng zi" 答题格就是截图被丢后剩下来的
    # 86×46 小块）——不一起丢，成品里会多出一张没头没尾的空格子图。
    shot_rects: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}

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

    # 向上吃小图标时的两个"墙"：整页文字框（别人的题干/题头不吃进图）、
    # 上一题的底边（绝不跨题）。原来只传本题文字框，实测共享地图会一路吃穿上一题。
    page_boxes: dict[int, list] = {}
    prev_bottom: dict[int, float] = {}
    _groups: dict[tuple[int, int], list] = {}
    for s in spans:
        pg_s = int(s.get("page", 1))
        page_boxes.setdefault(pg_s, []).extend(s.get("text_boxes") or [])
        _groups.setdefault((pg_s, int(s.get("col", 0))), []).append(s)
    for _grp in _groups.values():
        _grp.sort(key=lambda x: float(x["y0"]))
        for _i, _s in enumerate(_grp):
            prev_bottom[int(_s["q_index"])] = (
                float(_grp[_i - 1]["y1"]) if _i else 0.0)

    # 图可以往页边伸多远：隔壁栏【有题】就是硬墙；隔壁只是页边/密封线则放开。
    # （达标B q8 的写作格伸进密封线带 9pt；同一页左栏却绝不能捞过去。）
    walls: dict[tuple[int, int], tuple[float, float]] = {}
    _bounds: dict[tuple[int, int], list[float]] = {}
    for s in spans:
        key = (int(s.get("page", 1)), int(s.get("col", 0)))
        b = _bounds.setdefault(key, [float("inf"), 0.0])
        b[0] = min(b[0], float(s.get("x0") or 0.0))
        b[1] = max(b[1], float(s.get("x1") or 0.0))
    for (pg_w, col_w) in _bounds:
        src_w = sources[pg_w].width_pt if pg_w in sources else _bounds[(pg_w, col_w)][1]
        left = max([b1 for (p2, c2), (_b0, b1) in _bounds.items()
                    if p2 == pg_w and c2 < col_w] or [0.0])
        right = min([b0 for (p2, c2), (b0, _b1) in _bounds.items()
                     if p2 == pg_w and c2 > col_w] or [float(src_w)])
        walls[(pg_w, col_w)] = (left, right)

    # ── 第一遍：只测量，不裁图。家具判定要看【全部】候选，单题循环里看不到另一页 ──
    cands: list[dict[str, Any]] = []
    graphic_blocks: dict[int, dict[str, Any]] = {}
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
        # ── 图形算式整行：题干行里夹着字符级大图标 → 整行原样成图（见常量区说明）──
        gb = None
        if cv2 is not None:
            try:
                gb = _graphic_equation_block(src, s, np, cv2)
            except Exception:
                gb = None
        if gb is None:
            # 算式各部分名称的竖排图：OCR 只读到零散数字和"乘数"，只能整块成图
            try:
                gb = _term_diagram_block(src, s)
            except Exception:
                gb = None
        if gb is None:
            # 连一连：图、条目、连线空间是一整块，拆开就没法作答（周末作业(1) p1 第 1 题）
            try:
                gb = _match_layout_block(src, s)
            except Exception:
                gb = None
        if gb:
            gb.setdefault("kind", "equation")
            graphic_blocks[qi] = gb
        grect = gb["rect"] if gb else None
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
            # ── G2) 小窄块里的墨 ≥85% 落在文字行框里 → 多行文字的残影，不是图 ──
            if _is_text_covered_block([bx0, by0, bx1, by1], sgn.get("raw"),
                                      sgn.get("tb") or [], k, np):
                drop(qi, pg, to_pt((bx0, by0, bx1, by1)), "text-block")
                continue
            if _is_text_frame_block([bx0, by0, bx1, by1], sgn.get("raw"),
                                    sgn.get("tb") or [], k, np,
                                    sgn.get("tb_txt")):
                drop(qi, pg, to_pt((bx0, by0, bx1, by1)), "text-frame")
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
            # ── H) 贴物理页边、又矮又宽的灰带＝扫描件压痕，不是题图 ─────
            if _is_page_edge_band(raw, src):
                drop(qi, pg, raw, "page-edge")
                continue
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
            # ── I2) 下沿切在图的标签行中间 → 放到标签行底下（见函数说明）────
            grown_lbl = _extend_bottom_label_row(
                rect, s.get("text_boxes") or [],
                y_limit=float(s.get("y1") or src.height_pt))
            if grown_lbl != rect:
                rect = grown_lbl
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "label-row-extended"})
            # ── K) 紧贴图边的小标点框圈进来（算式不能少半个括号）──
            #     ⚠️ 圈完必须夹回这道题自己的栏区间：横版两张 A4 的卷子一旦越栏，
            #     就又是用户骂过的"把右边跟他没关系的截过来"。
            rect = _extend_to_short_marks(rect, s.get("text_boxes") or [])
            lbx0, lby0, lbx1, lby1 = span_box(src, s)
            rect = (max(rect[0], lbx0 - 3), max(rect[1], lby0 - 3),
                    min(rect[2], lbx1 + 3), min(rect[3], lby1 + 3))
            # ⚠️ 试过"四面把框外紧贴的图形墨吃进来"（_grow_to_ink）来治审计器的"切边"，
            #    实测两头不讨好：周末作业确实 切边 1→0、含题干 3→1，
            #    但第三单元练习题 配图 57→50、缺图 0→2、切边 2→5 ——
            #    因为长出去的框被这道题的区间边界夹住，反而把邻题的图挤没了。
            #    结论：四面长这条判据不接。只保留【上方小图标】这一种（见 K0）。
            # ── K0) 太阳/月亮紧贴本题上沿：只向上吃 ≤40×40pt 的小图标 ────
            if rect[1] <= lby0 + 1.0:
                grown = _grow_up_small_attached(rect, src, page_boxes.get(pg, []),
                                                lby0, np, cv2,
                                                floor_top=prev_bottom.get(qi, 0.0))
                if grown != rect:
                    rect = grown
                    if report is not None:
                        report.append({"q_index": qi, "page": pg, "kept": True,
                                       "rect": [round(v, 1) for v in rect],
                                       "why": "grew-up"})
            # ── L2) 裁框下沿把本题【最后一行题干】盖住 → 下沿收到这一行上面 ─────
            #     上沿管"图在题干下面"，下沿管"图在题干上面、题干紧跟着图"。
            #     真实卷：第三单元练习题 第 8 页第 30 题，青蛙跳数轴下面紧贴
            #     "青蛙1次跳4格,兔子1次跳( )个4格…"，裁框下沿 430.7 把整行框进图。
            #     ⚠️ 必须在 L0 之前做：这一行留着的话，L0 会把"下方还有一整句"
            #        误当成文字块的下半部，把数轴整张图当整题截图丢掉。
            cut = _clip_stem_row_bottom(rect, s.get("text_boxes") or [], ate_rows,
                                        src=src, k=k, np=np)
            if cut != rect:
                rect = cut
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "stem-bottom-clipped"})
            if rect[2] - rect[0] < 8 or rect[3] - rect[1] < 8:
                continue
            # ── L0) 整题截图判定必须在裁掉题干行【之前】做 ─────────────
            #   `_clip_stem_row` 会把本题起手行从上沿削掉；等到 L3 再看，
            #   `_stem_echo_edit` 选不到那句成句，整题截图就留了下来，
            #   成品图里重复一遍故事题干（达标A 第 1 题：框 [16.4,161.9,…]，
            #   起手行 164.9–181.4 被削到 182.4，L3 只剩拼音/答案格碎片）。
            q_text = ""
            if questions is not None and 0 <= qi < len(questions):
                q_text = str(questions[qi].get("text") or "")
            if q_text:
                edited0, ewhy0 = _stem_echo_edit(rect, s.get("text_boxes") or [], q_text,
                                                 src=src, k=k)
                if edited0 is None and _is_whole_question_screenshot(rect):
                    drop(qi, pg, rect, ewhy0 or "stem-screenshot")
                    shot_rects.setdefault((pg, qi), []).append(tuple(rect))
                    continue
            # ── L) 裁框不许把「本题的起手句」整行框进图里 ─────────────
            #   照片卷/扫描卷上最常见的那种脏：图就印在题干下面，裁框上沿顶到区间
            #   第一行（＝题干第一行），印出来图里又重复一遍「2. 请为2号无人配送车…」。
            #   ⚠️ 一个例外：这一行被规则⑤当【图注】吸回来的（气泡「我面向东。」和题干
            #     并成一行那种），它是图的一部分，裁掉就把图裁残。
            cut = _clip_stem_row(rect, s.get("text_boxes") or [], ate_rows,
                                 src=src, k=k)
            if cut != rect:
                rect = cut
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "stem-clipped"})
            # ── L2b) 图文同排：地图在左、题干在右被 OCR 拼成一行 → 沿空白竖缝收右沿 ──
            #    综合实践单元(1) p2 第 1 题：不收的话整行"图内重复文字"把题干删剩半句。
            side_split = False
            split = _split_side_text_figure(rect, page_boxes.get(pg, []) or
                                            (s.get("text_boxes") or []), src, np, k)
            if split is not None and split != rect:
                rect = split
                side_split = True
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "side-text-split"})
            if rect[2] - rect[0] < 8 or rect[3] - rect[1] < 8:
                continue
            # ── L3) 整题截图：文字归题干，图里只留作答格/真图 ─────────────
            #    达标A q1（5 行故事题干）→ 切完不剩东西，整框丢（L0 已拦下）；
            #    达标B q8（提示语+词语提示+写作格）→ 切掉顶部文字块，留格子。
            if q_text:
                edited, ewhy = _stem_echo_edit(rect, s.get("text_boxes") or [], q_text,
                                               src=src, k=k)
                if edited is None:
                    drop(qi, pg, rect, ewhy or "stem-screenshot")
                    continue
                if edited != rect:
                    rect = edited
                    if report is not None:
                        report.append({"q_index": qi, "page": pg, "kept": True,
                                       "rect": [round(v, 1) for v in rect],
                                       "why": ewhy})
            # ── L4) 栏界把框线切断：隔壁没有题时，把连续的墨接回来 ─────────
            #    只接右侧：左侧没有真实案例，而页边装饰被接宽会绕过装订栏判据。
            #    图文同排刚收窄过的框不许再接：右边 1–2pt 外就是题干首字，
            #    按"连续墨"接过去会把"1."也裁进图里（综合实践单元(1) p2 实测）。
            wl, wr = walls.get((pg, int(s.get("col", 0))), (0.0, src.width_pt))
            grown = rect if side_split else _extend_edge_ink(rect, src, k, np, "right", wr)
            if grown != rect:
                rect = grown
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "edge-extended"})
            # ── L4b) 裁框正好从字中间切过：把框外这一笔接完（≤6pt）─────────
            #    OCR 行擦墨会把图内标签（"乐乐 龙龙"）擦掉大半，候选框停在字中间；
            #    窄图又够不到 L4 的 60pt 门槛，标签就只剩半个字（综合实践单元 p1 q4）。
            if not side_split:
                glyph = _extend_cut_glyph(rect, src, k, np, "right", wr)
                if glyph != rect:
                    rect = glyph
                    if report is not None:
                        report.append({"q_index": qi, "page": pg, "kept": True,
                                       "rect": [round(v, 1) for v in rect],
                                       "why": "glyph-extended"})
            # ── L4c) 页边竖排密封线：先切掉再判"这是不是图" ─────────────
            #    密封字是 margin 单字框（已被丢弃），不算"图里的墨"；留着它会让
            #    作答横线/写作格看起来够高够宽，J4 判不出"这只是作答位置"，
            #    整段题干连横线一起被当成图裁走（达标B p1 第 5 题）。
            seal = _clip_seal_strip(rect, noise_by_page.get(pg, []), src.width_pt,
                                    src=src, k=k)
            if seal != rect:
                # 切完只剩贴着密封列的窄条＝这一列字自己连成的候选（达标B q3/q4
                # 的 13–16pt 竖条），不是图。留着会在成品里多出两条黑边。
                if seal[2] - seal[0] < SEAL_COLUMN_MAX_W:
                    drop(qi, pg, rect, "seal-column")
                    continue
                rect = seal
                if report is not None:
                    report.append({"q_index": qi, "page": pg, "kept": True,
                                   "rect": [round(v, 1) for v in rect],
                                   "why": "seal-trim"})
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
            # ── J2b) 两个空心圆圈＝比较大小的作答圈（`50-55 ○ 3×9`）───
            if _is_answer_circle_row(rect, sgn.get("raw"), k, cx0, y0, np):
                drop(qi, pg, rect, "answer-circles")
                continue
            # ── J3) 只有括号和虚线引导的空白作答行（`读作:( )`）─────────────
            if _is_blank_answer_row(rect, sgn.get("raw"), k, cx0, y0, np):
                drop(qi, pg, rect, "answer-blanks")
                continue
            # ── J4) 文字挖掉后只剩两三条作答横线（`你会对爷爷说：“ ____ ”`）──
            if _is_blank_rule_row(rect, sgn.get("band"), k, cx0, y0, np):
                drop(qi, pg, rect, "answer-rules")
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
            # ── 图形算式整行已由 gb 接管：落在它里面的碎片不再单独裁 ──────
            #    第 31 题按普通图形裁出来的就是图标被行框挖断后的两截碎片。
            if grect is not None and _covers(grect, rect) >= 0.5:
                drop(qi, pg, rect, "graphic-fragment")
                continue
            cands.append({
                "q_index": qi, "page": pg,
                "strict": strict, "side_split": side_split,
                "src": src, "col": int(s.get("col", 0)), "rect": rect,
                "tbs": s.get("text_boxes") or [],
                # 规则⑤吸回来的图注行号：合并/缝合后复检上沿时不能把它当题干切掉。
                "ate_rows": list(ate_rows),
                "w_pt": round(rect[2] - rect[0], 1), "h_pt": round(rect[3] - rect[1], 1),
                # rect 是给测试和"这图到底从哪儿裁的"留的凭据：
                # 没有它，"有没有跨栏"这种断言就只能靠人眼看图猜。
                "band": [round(float(s.get("x0") or 0), 1), round(y0 / k, 1),
                         round(float(s.get("x1") or src.width_pt), 1),
                         round(float(s.get("y1") or src.height_pt), 1)],
            })

    # ── 图形算式的整行原图：不参与"这张墨是不是图"的判据 ────────────────
    #    它本来就同时含文字和图标，text-block / text-cut / 空心框这些尺对它无效。
    for qi, gb in graphic_blocks.items():
        s = gb["span"]
        pg = int(s.get("page", 1))
        src = sources.get(pg)
        rect = gb["rect"]
        if src is None or rect[2] - rect[0] < 8 or rect[3] - rect[1] < 8:
            continue
        cands.append({
            "q_index": qi, "page": pg, "strict": True, "graphic": True,
            "graphic_kind": gb.get("kind") or "equation",
            "src": src, "col": int(s.get("col", 0)), "rect": rect,
            "tbs": s.get("text_boxes") or [],
            "w_pt": round(rect[2] - rect[0], 1),
            "h_pt": round(rect[3] - rect[1], 1),
            "band": [round(float(s.get("x0") or 0), 1),
                     round(float(s.get("y0") or 0), 1),
                     round(float(s.get("x1") or src.width_pt), 1),
                     round(float(s.get("y1") or src.height_pt), 1)],
        })
        if report is not None:
            report.append({"q_index": qi, "page": pg, "kept": True,
                           "rect": [round(v, 1) for v in rect],
                           "why": "graphic-equation"})

    # ── 第二遍：跨题缝合 → 过滤页上垃圾 → 每题按【面积大到小】限量 → 按阅读顺序编号裁图 ──
    #    整题截图已经整框丢掉：同一题里纵向落在那张截图范围内的候选都是它切出来的
    #    碎片（答题格/拼音框），一起丢，不许单独印出去。
    cands = _drop_shot_fragments(cands, shot_rects, report)
    cands = _stitch_across_questions(cands, report)
    ok: list[dict[str, Any]] = []
    for c in sorted(cands, key=lambda x: (x["page"], x["q_index"], x["rect"][1], x["rect"][0])):
        src = c["src"]
        if c.get("graphic"):
            ok.append(c)              # 整行原图：内容型裁图，不过"像不像图"的筛子
            continue
        # ── 候选框把一整行【页面家具】罩住了 → 贴边的切掉、留下的才是图 ──────
        #    必须在 margin/furniture 之前：周末作业的页脚卡伸到页边、每页位置又不一样，
        #    跨页同位置判据（_is_furniture）抓不到它。
        #    但"图 + 图下面一行栏目横幅"很常见（周末作业第 1 页第 4 题、第 2 页第 3 题），
        #    整框丢会把真题图一起扔掉 —— 见 _trim_furniture_rows。
        trimmed, twhy = _trim_furniture_rows(c["rect"], page_boxes.get(c["page"], []))
        if trimmed is not None:
            c["rect"] = trimmed
            c["w_pt"] = round(trimmed[2] - trimmed[0], 1)
            c["h_pt"] = round(trimmed[3] - trimmed[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"], "kept": True,
                               "rect": [round(v, 1) for v in trimmed], "why": twhy})
        else:
            cover, ftext = _furniture_row_cover(c["rect"], page_boxes.get(c["page"], []))
            if cover >= FURNITURE_ROW_COVER_MIN:
                drop(c["q_index"], c["page"], c["rect"], "furniture-text")
                continue
        # ── 小框把两整行文字从右边切断 → 文字残片 ──────────────────────
        if _is_text_cut_strip(c["rect"], page_boxes.get(c["page"], [])):
            drop(c["q_index"], c["page"], c["rect"], "text-cut")
            continue
        if _is_text_edge_fragment(c["rect"], page_boxes.get(c["page"], [])):
            drop(c["q_index"], c["page"], c["rect"], "text-edge")
            continue
        # ── 页脚二维码：扫码看讲解的入口，不是题图 ────────────────────────
        if _is_qr_block(c["rect"], src, DPI_PROBE / 72.0, qr_det):
            drop(c["q_index"], c["page"], c["rect"], "qr")
            continue
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
        bs_flags: list[str] = []
        grown = _absorb_row_peers(c["rect"], peers, box, bs_flags)
        if "bottom" in bs_flags:
            # 下沿刚并进来的是一条边框线：下面那题紧挨着，_trim_cross_question_graze
            # 会把它当成"蹭进邻题"再削回去（综合实践单元 p1 第 3 题实测），
            # 所以给这条框标个记号，让那刀跳过。
            c["border_strip"] = True
        if grown != c["rect"]:
            c["rect"] = grown
            c["w_pt"] = round(grown[2] - grown[0], 1)
            c["h_pt"] = round(grown[3] - grown[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"], "kept": True,
                               "rect": [round(v, 1) for v in grown], "why": "row-peer"})

    # 同一行被文字行挖断的几块并回一张（见 _stitch_side_by_side 的真卷说明）
    ok = _stitch_side_by_side(ok, report)

    # 大框已经把小框整个罩住＝同一张图裁了两遍，只留大框（见 _drop_contained）
    ok = _drop_contained(ok, report)

    # 缝合可能把上沿重新长回题干首行（周末作业 p1 第 3 题实测）→ 再收一次
    ok = _reclip_stem_after_merge(ok, report)

    # 框子被吸收/缝合改过形状之后，文字残影与空白横线要按最终形状复检一次
    # （见 _recheck_merged；候选阶段看到的是碎片，两个真实缺陷都在这一步之前长歪了）
    ok = _recheck_merged(ok, report, np, cv2)

    # 上一题的图底只蹭进下一题的图几个点（缝合把邻题的人头并进来了）→ 收回底沿
    ok = _trim_cross_question_graze(ok, report)

    # ── 最终形状再收两刀：上下沿的半个字/邻题起手句，以及页边竖排密封线 ──
    #    这两刀必须放在所有"长框/缝合"之后：前面刚收完又被 _extend_edge_ink
    #    或 _absorb_row_peers 长回去，等于没做（q22 实测）。
    for c in ok:
        if c.get("graphic"):
            continue                       # 图形算式整行原图故意含文字，不能被修边
        rect = c["rect"]
        grown = _grow_over_cut_label_rows(rect, page_boxes.get(c["page"], []))
        if grown != rect:
            rect = grown
            c["rect"] = rect
            c["w_pt"] = round(rect[2] - rect[0], 1)
            c["h_pt"] = round(rect[3] - rect[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"], "kept": True,
                               "rect": [round(v, 1) for v in rect],
                               "why": "label-grow"})
        trimmed = _trim_sliver_text_rows(rect, page_boxes.get(c["page"], []),
                                         c["src"], np, DPI_PROBE / 72.0)
        clipped = _clip_seal_strip(
            trimmed, noise_by_page.get(c["page"], []), c["src"].width_pt,
            src=c["src"], k=DPI_PROBE / 72.0)
        if clipped != rect and clipped[2] - clipped[0] >= 8:
            c["rect"] = clipped
            c["w_pt"] = round(clipped[2] - clipped[0], 1)
            c["h_pt"] = round(clipped[3] - clipped[1], 1)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"], "kept": True,
                               "rect": [round(v, 1) for v in clipped],
                               "why": "edge-trim"})

    # 最终形状再查一次"窄条字尾"：候选阶段框还宽 31.9pt（含页边空白），
    # 上面那刀修完才露出 14pt 的真形状；只在前一阶段查会漏（附加题实测）。
    kept_ok: list[dict[str, Any]] = []
    for c in ok:
        if not c.get("graphic") and _is_text_edge_fragment(
                c["rect"], page_boxes.get(c["page"], [])):
            drop(c["q_index"], c["page"], c["rect"], "text-edge")
            continue
        kept_ok.append(c)
    ok = kept_ok

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
            # 图形算式的整行原图：审计看到它含题干是【应该的】——图标只有原图能表达，
            # 判断题不能拿普通配图的"含题干"尺去量它（见 tests/audit_papers.stem_in_figures）。
            "graphic": bool(c.get("graphic")),
            "graphic_kind": c.get("graphic_kind"),
            # 图文同排收窄过的框：清理题干时要按"只摘行首图注"处理，
            # 不能再拿整行覆盖去删（否则题干正文会跟着没）。
            "side_split": bool(c.get("side_split")),
        })
    return out
