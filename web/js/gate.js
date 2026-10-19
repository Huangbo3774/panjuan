/* 磐卷 PaperForge · 服务门闸（四个页面共用）
 *
 * 背景：网页在浏览器沙箱里【不能】自己启动本地进程 —— 这是所有浏览器的硬规则，
 * 不是本项目的限制。所以"点一下就起服务"必须借 Windows 自定义协议 panjuan://
 * （由 scripts\install_startup.ps1 注册到 HKCU，双击 start.bat 时会自动注册一次）。
 *
 * 三种状态：
 *   1) 服务在跑 + 页面是 http:// 打开的  → 什么都不显示，正常用。
 *   2) 服务在跑 + 页面是 file:// 双击打开的 → 顶部绿条，自动切到正式地址
 *      （file:// 下相对路径、下载、接口都不如 http:// 稳，没必要留在这儿）。
 *   3) 服务没在跑 → 顶部橙条 + 「▶ 启动服务」按钮；点它 → panjuan://start，
 *      每秒重试健康检查，一起来就自动进页面；12 秒还没起来就提示手动方式。
 *
 * 探测方式实测过（Chrome，本机）：
 *   file:// 页面 fetch http://127.0.0.1:8000/api/health → status 200
 *   端口没人监听                                          → TypeError: Failed to fetch
 * 即 fetch 成/败能干净地区分"起没起"，不需要图片探针。
 *
 * ⚠️ 路径一律相对：绝对路径 /css/app.css 在 file:// 下会去磁盘根找，样式全丢。
 * ⚠️ 本文件不用 innerHTML，全部 createElement + textContent（文案全是写死的，
 *    但把"没有页面数据进 HTML"这件事变成结构保证而不是我的承诺）。
 */
(function () {
  'use strict';

  var PORT = location.port || '8000';                 // file:// 下 location.port 为空
  var SERVED = /^https?:$/.test(location.protocol);   // 由本机服务提供的页面
  var ROOT = SERVED ? '' : ('http://127.0.0.1:' + PORT + '/');
  var HEALTH = ROOT + 'api/health?_=';

  var el = null, timer = null, tries = 0;

  function mk(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function btn(id, label, ghost) {
    var b = mk('button', 'pj-gate__btn' + (ghost ? ' pj-gate__btn--ghost' : ''), label);
    b.type = 'button'; b.id = id; return b;
  }

  /* ── 探测：done(true) 表示服务健康 ─────────────────────── */
  function health(done) {
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    // 2.5s：机器忙的时候健康检查偶尔要一秒以上，卡太紧会把"在跑"误判成"没起"，
    // 用户就看到一个橙条和一个其实不必点的按钮。
    var to = ctl ? setTimeout(function () { try { ctl.abort(); } catch (e) { } }, 2500) : null;
    function settle(ok) { if (to) clearTimeout(to); done(ok ? true : false); }
    try {
      fetch(HEALTH + Date.now(), { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
        .then(function (r) { settle(r && r.ok); })     // 只认 2xx：500 的"活着"不算健康
        .catch(function () { settle(false); });        // 连接被拒 / 超时 / 被 abort
    } catch (e) { settle(false); }
  }

  /* file:// 时把当前页面映射到正式地址：file:///…/web/paper.html?a=1 → …/paper.html?a=1 */
  function officialUrl() {
    var p = decodeURIComponent(location.pathname || '');
    var i = p.lastIndexOf('/web/');
    var page = i >= 0 ? p.slice(i + 5) : 'index.html';
    return ROOT + page + (location.search || '');
  }
  function goOfficial() {
    if (el) el.className = 'pj-gate pj-gate--ok';
    if (SERVED) location.reload(); else location.replace(officialUrl());
  }

  /* 从页面自己的地址反推项目根：file:///C:/…/paper-forge/web/index.html → C:\…\paper-forge
     为什么要费劲算这个：横幅里光写"双击 start.bat"，用户根本不知道那个文件在哪台机器的哪个位置。 */
  function rootDir() {
    if (!/^file:$/.test(location.protocol)) return '';
    var p = '';
    try { p = decodeURIComponent(location.pathname || ''); } catch (e) { p = location.pathname || ''; }
    var i = p.lastIndexOf('/web/');
    if (i < 0) return '';
    return p.slice(1, i).replace(/\//g, '\\');      // 去掉 file:// 后开头的斜杠
  }
  function copyBtn(label, text) {
    var b = btn('', label, true);
    b.onclick = function () {
      // file:// 是安全上下文，clipboard API 一般可用；不行就退回选中文本让人手动 Ctrl+C
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { b.textContent = '✓ 已复制'; },
                                                function () { fallback(); });
      } else { fallback(); }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); b.textContent = '✓ 已复制'; } catch (e) { b.textContent = '按 Ctrl+C 复制'; }
        document.body.removeChild(ta);
      }
      setTimeout(function () { b.textContent = label; }, 2000);
    };
    return b;
  }

  /* ── 三种卡片 ──────────────────────────────────────────── */
  function card(kind) {
    if (!el) {
      el = mk('div', 'pj-gate');
      document.body.insertBefore(el, document.body.firstChild);
    }
    el.className = 'pj-gate' + (kind === 'ok' ? ' pj-gate--ok' : '');
    while (el.firstChild) el.removeChild(el.firstChild);
    el.appendChild(mk('span', 'pj-gate__ico', kind === 'ok' ? '✓' : '!'));

    var txt = mk('div', 'pj-gate__txt');
    el.appendChild(txt);
    var strong = mk('strong', null);
    var span = mk('span', 'pj-gate__sub');
    txt.appendChild(strong); txt.appendChild(span);

    if (kind === 'ok') {
      strong.textContent = '本机服务已经在跑了';
      span.textContent = '正在切到正式页面（http://127.0.0.1:' + PORT + '/）—— ' +
        '双击 HTML 打开的那种窗口功能不全，别留在这儿。';
      var go = btn('pj-go', '立即进入', true);
      go.onclick = goOfficial;
      el.appendChild(go);
      setTimeout(goOfficial, 1200);
      return;
    }
    if (kind === 'how') {
      /* 这一屏的存在理由：那个按钮走的是浏览器"外部协议"授权，天生不稳（确认框被忽略过一次，
         Chrome 之后就会静默拦截，页面这边什么都看不见）。所以这里不解释原理，只给一定能成的路，
         并且把绝对路径写出来 + 给复制按钮——光说"双击 start.bat"，用户不知道它在哪个文件夹。 */
      strong.textContent = '一定能启动的三条路（按省事程度排）';
      span.textContent = '那个按钮走的是浏览器的"外部协议"授权：确认框只要被忽略过一次，' +
        'Chrome 之后会静默拦截，页面这边收不到任何报错——所以点了没反应不一定是程序坏了。';
      var root = rootDir();
      var rows = root ? [
        ['① 双击启动（最省事）', root + '\\start.bat', root + '\\start.bat'],
        ['② 用开机自启，以后连按钮都不用点', 'powershell -ExecutionPolicy Bypass -File "' +
          root + '\\scripts\\install_startup.ps1" -AutoStart', null],
        ['③ 在 PowerShell 里直接跑', 'powershell -ExecutionPolicy Bypass -File "' +
          root + '\\scripts\\start.ps1"', null]
      ] : [
        ['① 双击项目文件夹里的 start.bat', '', null],
        ['② 或执行 scripts\\start.ps1', '', null]
      ];
      rows.forEach(function (r) {
        var box = mk('div', 'pj-gate__row');
        box.appendChild(mk('b', null, r[0]));
        if (r[1]) box.appendChild(mk('code', null, r[1]));
        if (r[2]) box.appendChild(copyBtn('复制路径', r[2]));
        else if (r[1]) box.appendChild(copyBtn('复制命令', r[1]));
        el.appendChild(box);
      });
      var tip = mk('div', 'pj-gate__row');
      tip.appendChild(mk('b', null, '想让那个按钮重新有效'));
      tip.appendChild(mk('span', 'pj-gate__sub',
        '看浏览器地址栏右侧有没有一个带红叉的小图标，点它选「允许」；' +
        '或者在地址栏打开 chrome://settings/content/handlers，把里面关于 磐卷/PaperForge 的记录删掉，' +
        '再回这个页面点一次（这次要在弹窗里勾「总是允许」）。'));
      el.appendChild(tip);
      var back = btn('pj-back', '返回', true);
      back.onclick = function () { card('down'); };
      el.appendChild(back);
      return;
    }
    strong.textContent = '本机服务没在运行';
    span.textContent = '网页自己启动不了本地程序（浏览器安全规则），点右边按钮让 Windows 去启动它。';
    var start = btn('pj-start', '▶ 启动服务');
    start.onclick = startServer;
    var how = btn('pj-how', '手动方式', true);
    how.onclick = function () { card('how'); };
    var m = mk('span', 'pj-gate__msg');
    m.id = 'pj-msg';
    m.textContent = '第一次会弹一次系统确认框，点「打开」并勾上「总是允许」。没弹或点了没反应？看「手动方式」。';
    el.appendChild(start); el.appendChild(how); el.appendChild(m);
  }

  function say(t) {
    var m = document.getElementById('pj-msg');
    if (m) m.textContent = t;
  }

  function startServer() {
    // 让 Windows 执行注册好的命令（wscript 隐藏窗口拉起 start.ps1 -NoBrowser）
    try { window.location.href = 'panjuan://start'; } catch (e) { }
    say('正在启动…（首次装依赖可能要 1–3 分钟）');
    poll();
  }

  function poll() {
    if (timer) clearInterval(timer);
    tries = 0;
    timer = setInterval(function () {
      tries += 1;
      health(function (up) {
        if (up) { stop(); card('ok'); return; }
        if (tries === 8) say('还没起来。八成是浏览器没把这个请求交给 Windows：' +
                             '看地址栏右侧有没有弹确认框/带红叉的小图标，点「允许」；' +
                             '或者直接用下面的「一定能启动的三条路」。');
        if (tries === 15) { var h2 = btn('pj-how2', '看那三条路', true); h2.onclick = function () { card('how'); }; el.appendChild(h2); }
        // 重试按钮只在 24 秒这一次挂上去（挂早了会盖在"正在启动"上面碍事）
        if (tries === 24) {
          var r = btn('pj-retry', '重新检查', true);
          r.onclick = function () { location.reload(); };
          el.appendChild(r);
        }
        if (tries > 90) { stop(); say('探测停了。请改用「手动方式」启动，或点「重新检查」再来一轮。'); }
      });
    }, 1000);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function boot() {
    health(function (up) {
      if (up) {
        // http:// 提供的页面本来就在正式地址上，不用管；file:// 则切过去
        if (!SERVED) card('ok');
        return;
      }
      card('down');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
