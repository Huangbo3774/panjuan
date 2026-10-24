/* 磐远试卷打印助手 · 桌面壳文案适配 + 提示条
 *
 * 两种桌面壳，口径不同，别混：
 *   · V1.4 Qt 壳（__PANJUAN_QT__，自带 Chromium）：拖文件进窗口【真的能用】
 *     —— dropEvent 由壳截获、经 pjfile:// 白名单协议喂回 add()。所以拖拽区文案
 *     保持"或拖到这里"不动；只把「在浏览器里打开并打印」改成「打开 PDF 并打印」
 *     （壳里点了开的是应用内 PDF 窗口）。
 *   · V1.3 pywebview 壳（window.pywebview，系统 WebView2）：拖拽拿不到文件对象，
 *     拖拽区文案改成点选；打印按钮点了其实是系统另存为。
 *   · 浏览器版：两个标记都不存在，一个字符都不改。
 *
 * __pjToast：给 Qt 壳回传提示用的页面内浮条（下载完成/拖拽被跳过等）。
 *
 * ⚠️ 与 app.js / gate.js 同一口径：不用 innerHTML，全部 textContent。
 */
(function () {
  'use strict';

  var QT = false;

  function patch() {
    QT = !!window.__PANJUAN_QT__;
    var webviewShell = !QT && !!window.pywebview;
    if (!QT && !webviewShell) return;
    var t = document.getElementById('toprint');
    if (t) t.textContent = QT ? '打开 PDF 并打印' : '另存一份 PDF 去打印';
    if (webviewShell) {
      var h = document.querySelector('#drop h2');
      if (h) h.textContent = '点这里，选择老师发的文件';
    }
  }

  // 页面内浮条：Qt 壳通过 runJavaScript 调它；3 秒自动消失，多条会堆叠
  window.__pjToast = function (msg) {
    var box = document.createElement('div');
    box.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:9999;' +
      'max-width:420px;padding:10px 14px;border-radius:8px;' +
      'background:#1c2530;color:#f2f5f8;font-size:14px;' +
      'box-shadow:0 4px 16px rgba(0,0,0,.35);line-height:1.5';
    box.textContent = String(msg);
    document.body.appendChild(box);
    var top = 18 + (document.body.querySelectorAll('div[data-pjtoast]').length - 1) * 56;
    box.setAttribute('data-pjtoast', '1');
    box.style.bottom = top + 'px';
    setTimeout(function () { box.remove(); }, 3200);
    return true;
  };

  // 注入时机不保证在 DOMContentLoaded 之前：监听事件 + 就绪后补扫一次，谁先到算谁
  window.addEventListener('pywebviewready', patch);
  document.addEventListener('DOMContentLoaded', function () {
    patch();
    setTimeout(patch, 300);
  });
})();
