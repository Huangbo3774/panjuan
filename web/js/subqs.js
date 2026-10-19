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

  /* 题干分行：引导语一行，（1）（2）（3）各一行。没有小问就原样一行。 */
  function stemLines(q) {
    var t = ((q && q.text) || '').replace(/\s+/g, ' ').trim();
    if (!subCount(q)) return t ? [t] : [];
    var subs = q.subqs;
    var head = String(subs[0].lead || '').replace(/\s+/g, ' ').trim();
    var out = [];
    if (head) out.push(head);
    for (var i = 0; i < subs.length; i++) {
      var s = subs[i];
      out.push('（' + s.no + '）' + String(s.text || '').replace(/\s+/g, ' ').trim());
    }
    return out;
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
    var m = String(text == null ? '' : text).match(/_{2,}|＿{2,}|[（(]\s*[）)]/g);
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
