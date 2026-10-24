/* 磐卷 PaperForge · 桌面窗口版（pywebview / WebView2）文案微调
 *
 * 背景：V1.3 起打包 exe 双击直接开原生窗口。窗口里有两处和浏览器不一样：
 *   1) 从资源管理器往页面里【拖拽】文件，WebView2 不给 dataTransfer.files —— 拖拽区文案要改成点选；
 *   2) 打印页「在浏览器里打开并打印」—— 桌面版没有"浏览器"，点了其实是系统另存为。
 * 只改文案，不改任何行为：下载/打印本来就走 pywebview 放行的 SaveFileDialog。
 *
 * ⚠️ 与 app.js / gate.js 同一口径：不用 innerHTML，全部 textContent。
 * 浏览器版（window.pywebview 不存在）这里一个字符都不会动。
 */
(function () {
  'use strict';

  function patch() {
    if (!window.pywebview) return;
    var h = document.querySelector('#drop h2');
    if (h) h.textContent = '点这里，选择老师发的文件';
    var t = document.getElementById('toprint');
    if (t) t.textContent = '另存一份 PDF 去打印';
  }

  // pywebview 注入 window.pywebview 的时机不保证在 DOMContentLoaded 之前，
  // 所以监听事件 + 就绪后再补扫一次，谁先到算谁。
  window.addEventListener('pywebviewready', patch);
  document.addEventListener('DOMContentLoaded', function () {
    patch();
    setTimeout(patch, 300);
  });
})();
