/* 磐远试卷打印助手 · 流程步骤条（四个页面共用【一份】定义）
 *
 * 顺序是产品口径，由用户明确指定：
 *   1 上传 → 2 校对题目 → 3 在线做题（可以跳过）→ 4 打印成 PDF
 * 第 4 步导出的东西跟着状态走：没做题就是空白卷，做了题就带上他的答案，
 * 再往下就是「答案 + 自动批改结果」。
 *
 * 为什么这个文件必须存在：上一版每个页面各自抄了一份 items 数组，
 * preview.html 那份把「打印版」排在第 2 步，另外两页又把「校对」排在第 3 步 ——
 * 四页互相打架，用户一眼就看出来了（"你这个顺序是错误的"）。
 * 抄一遍就会漂一次，所以顺序只留这一处，页面只负责说"我是第几步"。
 *
 * ⚠️ 与 gate.js 同样：不用 innerHTML，全部 createElement + textContent。
 */
(function () {
  'use strict';

  var STEPS = [
    { key: 'upload',    label: '上传',        href: 'index.html' },
    { key: 'proofread', label: '校对题目',    href: 'proofread.html' },
    { key: 'answer',    label: '在线做题',    href: 'paper.html' },
    { key: 'print',     label: '打印成 PDF',  href: 'print.html' }
  ];

  function render(current, id) {
    var el = document.getElementById('steps');
    if (!el) return 0;
    while (el.firstChild) el.removeChild(el.firstChild);
    STEPS.forEach(function (s, i) {
      var a = document.createElement('a');
      a.href = s.href + (id ? ('?paper=' + encodeURIComponent(id)) : '');
      if (s.key === current) a.className = 'on';
      var n = document.createElement('i');
      n.textContent = String(i + 1);
      a.appendChild(n);
      a.appendChild(document.createTextNode(s.label));
      el.appendChild(a);
    });
    return STEPS.length;
  }

  // 给页面一个"当前在第几步"的声明方式：<body data-step="print">
  function boot() {
    var b = document.body;
    if (!b) return;
    var cur = b.getAttribute('data-step') || '';
    var m = /[?&]paper=([^&]+)/.exec(location.search);
    render(cur, m ? decodeURIComponent(m[1]) : '');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }

  // 页面拿到试卷号之后可以再渲染一次（用任务号进来时，URL 里没有 paper=）
  window.PJSteps = { render: render, STEPS: STEPS };
})();
