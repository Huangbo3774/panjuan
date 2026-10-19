/* 作答页小问视图的断言：给 node 直接跑（node tests/subqs_assert.js）。
 *
 * 为什么用 node 而不是只在浏览器里看一眼：这套逻辑决定孩子看到几个输入框、
 * 每个框标的是哪一问。框数错了 = data-b 下标错位 = 批改把答案记到别的空上，
 * 属于判分事故，不能靠肉眼看渲染。
 */
'use strict';

const path = require('path');
const PJ = require(path.join(__dirname, '..', 'web', 'js', 'subqs.js'));

let ok = 0, bad = 0;
function t(name, fn) {
  try { fn(); ok++; console.log('  PASS ' + name); }
  catch (e) { bad++; console.log('  FAIL ' + name + ' → ' + e.message); }
}
function eq(a, b, why) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error((why ? why + '：' : '') + x + ' ≠ 期望 ' + y);
}

const three = {
  blanks: 6, text: '看图填一填。 (1)2只2只地数,数了(    )次,一共有(    )只蝴蝶。 (2)3只3只地数,数了(    )次,一共有(    )只蝴蝶。 (3)4只4只地数,数了(    )次,一共有(    )只蝴蝶。',
  subqs: [
    { no: 1, lead: '看图填一填。', text: '2只2只地数,数了(    )次,一共有(    )只蝴蝶。', blanks: 2 },
    { no: 2, text: '3只3只地数,数了(    )次,一共有(    )只蝴蝶。', blanks: 2 },
    { no: 3, text: '4只4只地数,数了(    )次,一共有(    )只蝴蝶。', blanks: 2 },
  ],
};

t('三问各两空 → 标签按问分组，孩子知道哪空归哪问', () => {
  eq(PJ.blankLabels(three),
     ['(1)第1空', '(1)第2空', '(2)第1空', '(2)第2空', '(3)第1空', '(3)第2空']);
});

t('题干分行：引导语一行 + 三问各一行', () => {
  eq(PJ.stemLines(three),
     ['看图填一填。',
      '（1）2只2只地数,数了( )次,一共有( )只蝴蝶。',
      '（2）3只3只地数,数了( )次,一共有( )只蝴蝶。',
      '（3）4只4只地数,数了( )次,一共有( )只蝴蝶。']);
});

t('没有小问的题不加编号（反例：普通填空照排一行）', () => {
  const plain = { blanks: 2, text: '一年有（    ）个月，其中大月有（    ）个。', subqs: [] };
  eq(PJ.blankLabels(plain), ['第1空', '第2空']);
  eq(PJ.stemLines(plain), ['一年有（ ）个月，其中大月有（ ）个。']);
});

t('只切出一问不算小问（反例：不许硬加 (1) 前缀）', () => {
  const one = { blanks: 2, text: '（1）只有一问。', subqs: [{ no: 1, text: '只有一问。', blanks: 2 }] };
  eq(PJ.subCount(one), 0);
  eq(PJ.blankLabels(one), ['第1空', '第2空']);
});

/* ⚠️ 这条不变量是「批改不错位」的前提：渲染时按 labels.length 生成输入框，
 * 下标 data-b=i|k 要和小问/空位一一对上，所以标签数必须【恒等于】q.blanks（至少 1）。 */
t('不变量：标签数恒等于该题空位数（六种形状，含 OCR 漏括号 / 多括号）', () => {
  const shapes = [
    three,
    { blanks: 6, subqs: [{ no: 1, text: 'a', blanks: 2 }, { no: 2, text: 'b', blanks: 2 }] },
    { blanks: 1, subqs: [{ no: 1, text: 'a', blanks: 4 }, { no: 2, text: 'b', blanks: 4 }] },
    { blanks: 0, subqs: [] },
    { blanks: 3, subqs: [] },
    { blanks: 2, subqs: [{ no: 1, text: 'a', blanks: 1 }, { no: 2, text: 'b', blanks: 1 }] },
  ];
  shapes.forEach((q, i) => {
    const want = Math.max(parseInt(q.blanks, 10) || 0, 1);
    const got = PJ.blankLabels(q).length;
    if (got !== want) throw new Error('第 ' + (i + 1) + ' 种形状：标签 ' + got + ' 个 ≠ 空位 ' + want + ' 个');
  });
});

t('小问空位少于总空位 → 多出来的退回第N空（不许少给框）', () => {
  const q = { blanks: 4, subqs: [{ no: 1, text: 'a', blanks: 2 }, { no: 2, text: 'b', blanks: 1 }] };
  eq(PJ.blankLabels(q), ['(1)第1空', '(1)第2空', '(2)第1空', '第4空']);
});

t('小问空位多于总空位 → 截断到总空位（判分下标仍以 q.blanks 为准）', () => {
  const q = { blanks: 2, subqs: [{ no: 1, text: 'a', blanks: 2 }, { no: 2, text: 'b', blanks: 2 }] };
  eq(PJ.blankLabels(q), ['(1)第1空', '(1)第2空']);
});

t('题干为空的配图题不报错（反例：只有图、没有文字）', () => {
  eq(PJ.stemLines({ blanks: 1, text: '', subqs: [] }), []);
  eq(PJ.blankLabels({ blanks: 1, text: '', subqs: [] }), ['第1空']);
});

/* 前后端同口径的交叉核对在 tests/cross_blanks.js（字符串清单由
 * tests/test_subqs_js.py 那份 Python 侧持有，两边各数一遍再比 ——
 * 清单如果抄两份，漂了都不知道比的是同一批字符串）。 */

t('空位数：括号里几个空格都算一个空（真卷的 6 个空格曾被漏数）', () => {
  eq(PJ.countBlanks('数了(      )次,一共有(      )只蝴蝶。'), 2);
  eq(PJ.countBlanks('一年有（        ）个月，大月有（  ）个。'), 2);
  // OCR 常把一对括号读成全角开 + 半角闭的混配，只认成对写法就漏（真卷有 5 个）
  eq(PJ.countBlanks('数了（      )次,一共有(      ）只蝴蝶。'), 2);
  eq(PJ.countBlanks('算式：____________ ＝ ____________'), 2);
});

t('空位数反例：填了数 / 夹了字 / 单个下划线都不算', () => {
  eq(PJ.countBlanks('3×4=（12），5×6=（30）'), 0);
  eq(PJ.countBlanks('（ 见上图 ）不对，应该是（   ）'), 1);
  eq(PJ.countBlanks('a_b'), 0);
});

t('符号插入：光标处插入 / 选区替换 / 越界夹回', () => {
  eq(PJ.pasteSymbol('3和4', 1, 1, '＋'), { value: '3＋和4', caret: 2 });
  // 选中"×"点"÷"必须【替换】，不是变成"×÷"——否则家长改不动，只能整行重打
  eq(PJ.pasteSymbol('3×4', 1, 2, '÷'), { value: '3÷4', caret: 2 });
  eq(PJ.pasteSymbol('', 0, 0, '★'), { value: '★', caret: 1 });
  eq(PJ.pasteSymbol('abc', 99, 99, '×'), { value: 'abc×', caret: 4 });
  eq(PJ.pasteSymbol('abc', 2, 1, '×'), { value: 'ab×c', caret: 3 });
});

t('空 token 不许改动文本（反例：按钮没带符号时不能吞字）', () => {
  eq(PJ.pasteSymbol('3×4', 1, 2, ''), { value: '3×4', caret: 1 });
});

t('符号面板非空，且一个 emoji 都不许放', () => {
  const flat = [].concat.apply([], PJ.SYMBOL_GROUPS.map(function (g) { return g.items; }));
  if (flat.length < 20) throw new Error('面板只有 ' + flat.length + ' 个符号（尺坏了或被人删了）');
  ['×', '÷', '＝', '★', '□'].forEach(function (s) {
    if (flat.indexOf(s) < 0) throw new Error('面板缺了最常用的 ' + s);
  });
  // 码点 > 0xFFFF 的就是 emoji 那一类：simhei/msyh 里没有字形，
  // 印到卷子上是空白方块 —— 这条挡住"顺手粘个 ⭐"的下一次改动。
  const bad = flat.filter(function (s) { return s.codePointAt(0) > 0xFFFF; });
  if (bad.length) throw new Error('面板里放了打印字体没有的字形：' + bad.join(''));
});

console.log('\n' + ok + ' passed, ' + bad + ' failed');
process.exit(bad ? 1 : 0);
