/* 把一批字符串按 countBlanks 数一遍，结果用 JSON 打回给 Python 比对。
 * 清单不在这里写：两处各存一份清单，漂了都不知道比的是不是同一批字符串。 */
'use strict';
const path = require('path');
const fs = require('fs');
const PJ = require(path.join(__dirname, '..', 'web', 'js', 'subqs.js'));

const list = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(list.map(function (s) { return PJ.countBlanks(s); })));
