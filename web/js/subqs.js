/* 小问（1）（2）（3）的作答页视图：题干按问分行 + 空位标签按问分组。
 *
 * 为什么单独一个文件、还不碰 DOM：
 *   1) 判据只留一份实现 —— 题干怎么分行、空位怎么标号，浏览器里和打印版必须同口径，
 *      写两遍就一定漂（本项目吃过「四页 steps 顺序各写一份」的苦头）；
 *   2) 纯函数才能被 node 直接跑（tests/test_subqs_js.py），
 *      内联在 paper.html 里的逻辑只有「打开浏览器才知道对不对」，那不算有尺。
 *
 * 口径（和 app/extractor/rules.split_subqs、app/papers/answer_writer 对齐）：
 *   · 题号 / 分值 / 批改仍按【一道题】走，小问只是显示层；
 *   · 少于两个小问就当普通题排，绝不硬加编号；
 *   · 空位标签对不上时退回「第N空」——宁可标签朴素，也不能少给孩子一个能作答的框
 *     （少一个框 = 少一个 data-b 下标 = 批改错位，那是判分事故，不是显示事故）。
 */
(function (root) {
  'use strict';

  /* 有几个小问（不足 2 个一律当 0，普通题不许被"分行"） */
  function subCount(q) {
    var s = (q && q.subqs) || [];
    return s.length >= 2 ? s.length : 0;
  }

  /* 这道题该有几个输入框：以 q.blanks 为准，最少 1 个 */
  function nblanks(q) {
    return Math.max(parseInt((q && q.blanks) || 0, 10) || 0, 1);
  }

  /* 空位口径：括号里的一整串空白 / 一段下划线。
   * countBlanks 和 isItemRow 共用这一份 —— 两处各写一个，漂了会出现
   * "空位里那 4 个空格被当条目间隔、整行被判成连线卡片行"（见 isItemRow）。 */
  var BLANK_RE = /_{2,}|＿{2,}|[（(]\s*[）)]/g;

  /* 条目行：三个以上、用两格以上空白隔开的短条目（连线/数数的卡片行）。
   * 和 app/extractor/rules.py 的 _is_item_row 同口径：这些空白是版面语义，
   * 折叠成一个空格后"6+6 6个2 6×2 …"看起来就是一句莫名其妙的话。 */
  function isItemRow(line) {
    // 先把【空位】挖成一个字符再切：`数了(    )次,一共有(    )只蝴蝶。`
    // 按两格空白切会切出三个"短条目"，整行题干被误判成卡片行，
    // 空位里那 4 个空格就原样留在题干里（subqs_assert 的"题干分行"当场红）。
    // 括号里的空白是空位，不是条目之间的版面间隔 —— 这一条和 Python 侧同一判据。
    var masked = String(line || '').replace(BLANK_RE, '□');
    var parts = masked.split(/[ \t]{2,}/).filter(function (p) {
      return p.trim();
    });
    if (parts.length < 3) return false;
    var max = 0;
    for (var i = 0; i < parts.length; i++) {
      max = Math.max(max, parts[i].trim().length);
    }
    return max <= 12;
  }

  /* 单行清洗：条目行保留间隔，普通行折叠空白。 */
  function tidyLine(line) {
    var s = String(line == null ? '' : line).trim();
    if (!s) return '';
    return isItemRow(s) ? s : s.replace(/\s+/g, ' ');
  }

  /* 题干分行：显式换行（条目行）各占一行；引导语一行，（1）（2）（3）各一行。 */
  function stemLines(q) {
    var raw = String((q && q.text) || '');
    if (!subCount(q)) {
      var parts = raw.split(/\r?\n/), out = [];
      for (var i = 0; i < parts.length; i++) {
        var line = tidyLine(parts[i]);
        if (line) out.push(line);
      }
      return out;
    }
    var subs = q.subqs;
    var head = tidyLine(subs[0].lead);
    var lines = [];
    if (head) lines.push(head);
    for (var j = 0; j < subs.length; j++) {
      var s = subs[j];
      lines.push('（' + s.no + '）' + tidyLine(s.text));
    }
    return lines;
  }

  /* 空位标签：按小问分组标 (1)第1空 / (1)第2空 / (2)第1空…，多出来的退回第N空。
   * 返回长度【恒等于】nblanks(q) —— 这条不变量是判不错位的前提，测试里有专门一条量它。 */
  function blankLabels(q) {
    var n = nblanks(q);
    if (!subCount(q)) {
      var plain = [];
      for (var k = 0; k < n; k++) plain.push('第' + (k + 1) + '空');
      return plain;
    }
    var subs = q.subqs, out = [];
    for (var i = 0; i < subs.length; i++) {
      var s = subs[i], m = parseInt(s.blanks, 10) || 0;
      for (var k = 0; k < m; k++) out.push('(' + s.no + ')第' + (k + 1) + '空');
    }
    while (out.length < n) out.push('第' + (out.length + 1) + '空');
    return out.slice(0, n);
  }

  /* 空位数：括号里一整串空白 = 一个空位，或一段下划线 = 一个空位。
   * ⚠️ 这条口径和 app/extractor/rules.py 的 BLANK_RE 必须一模一样 ——
   * 校对页保存时会用它重算空位数，两处不一致的话，家长点一次保存，
   * 做题页的输入框数量就会跳（本项目最恨"同一判据两处实现"）。
   * 一致性由 tests/test_subqs_js.py 拿同一批字符串两边跑一遍来钉。 */
  function countBlanks(text) {
    var m = String(text == null ? '' : text).match(BLANK_RE);
    return m ? m.length : 0;
  }

  /* 校对页「插入数学符号」的纯逻辑：给定文本 + 选区 + 要插的符号，
   * 返回新文本和新光标位置。
   * ⚠️ 有选区时必须【替换选区】，不是插在后面 —— 家长选中"×"点"÷"，
   *   若变成"×÷"就等于改不动，只能整行重打（这条逻辑放这里就是为了能被 node 测）。
   * ⚠️ start/end 越界或没给（IE/异常状态）一律夹到合法区间，不许抛错：
   *   抛错会让整个校对页的按钮失灵，而按钮失灵家长是看不懂原因的。 */
  function pasteSymbol(value, start, end, token) {
    var v = String(value == null ? '' : value);
    var a = Math.max(0, Math.min(v.length, start == null ? v.length : start));
    var b = Math.max(a, Math.min(v.length, end == null ? a : end));
    if (!token) return { value: v, caret: a };
    return { value: v.slice(0, a) + token + v.slice(b), caret: a + token.length };
  }

  /* 符号面板的内容。只放【打印字体里真有字形】的字符
   * （simhei/msyh 有 ★●○□△×÷＝≤≥√∠℃，没有 ⭐🌙 这类 emoji，
   *  写了 emoji 在家长打印出来的卷子上就是空白方块）。 */
  var SYMBOL_GROUPS = [
    { name: '运算', items: ['＋', '－', '×', '÷', '＝', '≠', '≈', '≥', '≤', '±', '√', '∶', '…'] },
    { name: '图形', items: ['★', '☆', '●', '○', '□', '△', '▲', '◆', '◇', '⊙', '■'] },
    { name: '单位/几何', items: ['°', '℃', '∠', '⊥', '∥', '⌒', '（', '）'] }
  ];

  var api = { subCount: subCount, nblanks: nblanks, stemLines: stemLines,
              blankLabels: blankLabels, countBlanks: countBlanks,
              pasteSymbol: pasteSymbol, SYMBOL_GROUPS: SYMBOL_GROUPS };
  root.PJSubs = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
