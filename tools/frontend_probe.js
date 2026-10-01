// 前端行为探针：用 jsdom 真跑一遍 index.html 的模板 + app.js，把"页面长什么样"
// 与"点一下之后状态怎么变"变成可比较的对象。
//
// 它做什么
// ========
// jsdom 能真跑 Vue：组件挂载、插值求值、事件绑定、$emit 全都按真实语义走。
// 本探针把"渲染结果"与"事件接线"变成两条可自动比对的证据：
//
//   1. 多状态 DOM 快照 —— 覆盖 5 个页块 + 学生/教师两种角色 + 4 个弹窗。
//      修改前后逐字节相同，即"渲染出来的结构没变"。
//   2. 点击序列断言   —— 快照看不见 @click 绑到了谁身上（属性渲染成 DOM 后
//      只剩一个监听器，没有痕迹）。这一条必须真的点一下、再读状态。
//
// 根实例没有 created / mounted / beforeCreate / beforeMount，`new Vue(` 之前
// 只有 axios 配置与两个拦截器。所以挂载是确定性的，**不发任何请求**。
//
// 本探针全程离线：不发 HTTP、不连数据库、不 import app 包。它只读
// index.html / static/ 下的文件，在内存里的 jsdom 中执行。
//
// 用法
// ====
//   node tools/frontend_probe.js                  # 人类可读报告
//   node tools/frontend_probe.js --json           # 结果 JSON 到 stdout（给测试用）
//   node tools/frontend_probe.js --write-baseline # 写出 tests_safe/baselines/frontend_render.json
//
// 退出码：0 正常；2 找不到 index.html；3 没构造出 Vue 实例；4 页面里没有 #app；
//         5 环境缺 jsdom（测试据此 skip，不是失败）。

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const JSON_ONLY = process.argv.includes('--json');
const WRITE = process.argv.includes('--write-baseline');
const BASELINE = path.join(ROOT, 'tests_safe', 'baselines', 'frontend_render.json');

// ---------------------------------------------------------------------------
// jsdom 的解析
// ---------------------------------------------------------------------------
// 本机 jsdom 装在 `C:\Users\HLJ\node_modules`（npm 全局，用户级）。它**不是**
// 仓库目录的祖先，所以 `require('jsdom')` 从仓库根调用必然失败。按"本机可跑、
// 换机器给出可读提示"来兜。
function loadJsdom() {
  try {
    return require('jsdom');
  } catch { /* 继续找 */ }

  const dirs = [
    ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean),
    path.join(os.homedir(), 'node_modules'),                       // npm 全局（用户级）
    path.join(process.env.APPDATA || '', 'npm', 'node_modules'),    // Windows 老式全局目录
    '/usr/lib/node_modules',
    '/usr/local/lib/node_modules',
  ];
  for (const dir of dirs) {
    try {
      return require(path.join(dir, 'jsdom'));
    } catch { /* 下一个 */ }
  }
  return null;
}

const jsdom = loadJsdom();
if (!jsdom) {
  process.stderr.write(
    '找不到 jsdom。装一个即可（本机是全局安装）：\n' +
    '  npm i -g jsdom\n' +
    '或用 NODE_PATH 指向已有的 node_modules。\n'
  );
  process.exit(5);
}

// ---------------------------------------------------------------------------
// 起页面
// ---------------------------------------------------------------------------

const html = read('index.html');
const body = html.match(/<body[^>]*>([\s\S]*)<\/body>/);
if (!body) { process.stderr.write('index.html 里取不到 <body>\n'); process.exit(2); }

const dom = new jsdom.JSDOM(
  `<!DOCTYPE html><html><head></head><body>${body[1]}</body></html>`,
  { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/' }
);
const { window } = dom;

// 页面自己的 console 全吞掉，只留 warn/error —— 否则几万行日志。
const notes = [];
window.console = {
  log() {}, info() {}, debug() {},
  warn: (...a) => notes.push(`warn: ${a[0]}`),
  error: (...a) => notes.push(`error: ${a[0]}`),
};

// 把 `new Vue` 的返回值捞出来。Proxy 的 construct 陷阱不影响静态成员与原型，
// 所以 app.js 里用到的 Vue 静态方法照常可用。
let vm = null;
window.eval(read('static/vendor/vue-2.6.14.js'));
window.Vue = new Proxy(window.Vue, {
  construct(target, args) {
    vm = Reflect.construct(target, args);
    return vm;
  },
});
window.eval(read('static/vendor/axios-1.20.0.min.js'));
window.eval(read('static/js/app.js'));

if (!vm) { process.stderr.write('app.js 没有构造出 Vue 实例\n'); process.exit(3); }

const doc = window.document;
if (!doc.getElementById('app')) { process.stderr.write('页面里没有 #app\n'); process.exit(4); }

const tick = () => new Promise(resolve => vm.$nextTick(resolve));
const snapshot = () => doc.getElementById('app').outerHTML;
const hash = text => crypto.createHash('sha256').update(text).digest('hex').slice(0, 16);

// 本探针会动到的根实例字段，挂载后立刻留一份初值。
// 用途是让 `goto` 能把上一个状态**连点击产生的副作用一起**清掉。
const TOUCHED = [
  'currentUser', 'pageState', 'showAITutor', 'showClassModal',
  'viewingGroupReports', 'activeTab', 'globalModal',
];
const INITIAL = Object.fromEntries(TOUCHED.map(key => [key, vm[key]]));

// ---------------------------------------------------------------------------
// 1. 多状态快照
// ---------------------------------------------------------------------------
//
// `currentUser` 是**必须显式给的前置条件**，不是可选项。
// app.js 里它是 `null`，而大厅模板第一句就是 `currentUser.role`。
// 直接切 `pageState = 'lobby'` 会抛 `Cannot read properties of null (reading 'role')`，
// 而**抛错的后果是 DOM 静默冻住**：Vue 的渲染是一个 `_update(vm._render())`，
// `_render()` 一抛，`_update` 就不执行，页面保留上一次成功的快照。
// 症状是"好几个不同状态算出同一个哈希"，而不是一条报错。
const asUser = role => ({
  id: 1, name: '探针', student_id: 'probe001',
  username: 'probe', email: 'p@example.com', role,
});

const STATES = [
  ['默认（落地页）', () => { vm.currentUser = null; vm.pageState = 'landing'; }],
  ['登录页', () => { vm.currentUser = null; vm.pageState = 'login'; }],
  ['注册页', () => { vm.currentUser = null; vm.pageState = 'register'; }],
  ['大厅（学生）', () => { vm.currentUser = asUser('student'); vm.pageState = 'lobby'; }],
  ['大厅（教师）', () => { vm.currentUser = asUser('teacher'); vm.pageState = 'lobby'; }],
  // 侧栏「个人中心」的真实接线是 `loadVoiceprintStatus()`（触网），所以这一页
  // 用注入进入；但它**自己**的交互（下面的「开始对话」）照样是点出来的。
  // 探针里每个状态都要标清"哪一段是注入的、哪一段是点的"，否则覆盖面会自我膨胀。
  ['个人中心（学生）', () => { vm.currentUser = asUser('student'); vm.pageState = 'lobby'; vm.activeTab = 'profile'; }],
  ['课堂（学生）', () => { vm.currentUser = asUser('student'); vm.pageState = 'classroom'; }],
  ['课堂（教师）', () => { vm.currentUser = asUser('teacher'); vm.pageState = 'classroom'; }],
  ['AI 辅导弹窗', () => { vm.currentUser = asUser('student'); vm.pageState = 'lobby'; vm.showAITutor = true; }],
  ['进入课堂弹窗', () => { vm.currentUser = asUser('teacher'); vm.pageState = 'lobby'; vm.showClassModal = true; }],
  ['小组报告弹窗', () => { vm.currentUser = asUser('teacher'); vm.pageState = 'lobby'; vm.viewingGroupReports = true; }],
  ['通用弹窗', () => {
    vm.currentUser = asUser('student'); vm.pageState = 'lobby';
    vm.globalModal = { ...vm.globalModal, show: true, type: 'alert', title: 'T', message: 'M' };
  }],
  // 确认型弹窗与提示型的分支不同：多一个「取消」按钮，且点遮罩**不**关闭。
  ['通用弹窗（确认）', () => {
    vm.currentUser = asUser('student'); vm.pageState = 'lobby';
    vm.globalModal = { ...vm.globalModal, show: true, type: 'confirm', title: 'T', message: 'M' };
  }],
];

// ---------------------------------------------------------------------------
// 2. 点击序列
// ---------------------------------------------------------------------------
//
// 只放**不触网**的接线。点了会发请求的按钮（提交登录/注册、拉课堂列表）不在这里：
// 那要么得造一份 mock，要么就会真发请求——两条都超出本探针的职责。
//
// 覆盖面因此是"页面间导航"这一类，不是"全部交互"。这是**已知的、有意的边界**：
// 模板块最容易被拆坏的地方就是"点了没反应"或"点错了跳转"——恰好是这一组能覆盖的。
// 真正带网络的流程改动，本探针不管。
//
// 每一条**各自建立前置状态**，不依赖上一条的残留：否则一条失败就会把后面几条
// 带到别的页面上，报出来的症状离原因很远。

const buttonWith = re =>
  [...doc.querySelectorAll('button')].find(el => re.test(el.textContent.trim()));

const STATE_SETUP = new Map(STATES.map(([name, apply]) => [name, apply]));

// 前置状态一律**按上面 STATES 里的名字**取，不另写一套：
// 两处各写一份，就会出现"测试用的登录态"和"快照用的登录态"悄悄分叉。
const goto = async name => {
  const apply = STATE_SETUP.get(name);
  if (!apply) throw new Error(`没有名为「${name}」的状态`);
  // 先归位、再摆前置状态。少了这一步，上一条点击留下的 showClassModal=true
  // 会让下一条的"遮罩恰好一个"断言报出"实为 2 个"——症状离原因很远。
  // 注意这不改变 STATES 的语义：每个状态本来就是**从初始实例**摆出来的一个快照。
  for (const key of TOUCHED) vm[key] = INITIAL[key];
  apply();
  await tick();
};

const overlay = () => doc.querySelector('.global-modal-overlay');

// 全屏弹窗的遮罩。10 个 `.fixed.inset-0` 里绝大多数挂在 v-if 上、默认不在 DOM 里，
// 所以"渲染出来的恰好一个"本身就是断言：多于一个说明状态没建干净，宁可报错也不要瞎选第一个。
const screenOverlay = () => {
  const all = [...doc.querySelectorAll('#app .fixed.inset-0')];
  if (all.length !== 1) return { el: null, why: `.fixed.inset-0 应恰好渲染 1 个，实为 ${all.length} 个` };
  return { el: all[0], why: null };
};

// 关闭按钮＝遮罩内**文档序第一个**带 .fa-times 的按钮（即弹窗头部的 ×）。
// 不按文字选：这些按钮里只有一个图标，没有文字。取文档序第一个而不是"唯一一个"——
// 「进入课堂弹窗」里选中文件后还会多出一个删除按钮，同样带 .fa-times。
const closeButtonIn = el => [...el.querySelectorAll('button')].find(b => b.querySelector('.fa-times'));

// ⚠️ 下面这些说明里**不写行号**，只写"在哪一块"。
// 行号会因为别处增删行而失效，而且没有任何东西会因此报红；所以用
// `#landing-page-tpl` 这类 id、或"侧栏那一颗"这类结构描述作**稳定锚点**。
const CLICKS = [
  ['落地页点“登录” → 进登录页', '默认（落地页）', async () => {
    const btn = buttonWith(/^登录$/);
    if (!btn) return ['落地页上找不到文字为“登录”的按钮（#landing-page-tpl 里的 lp-login-btn）'];
    btn.click(); await tick();
    return vm.pageState === 'login' ? null : [`pageState 应为 login，实为 ${vm.pageState}`];
  }],
  ['落地页点“注册” → 进注册页', '默认（落地页）', async () => {
    const btn = buttonWith(/注册/);
    if (!btn) return ['落地页上找不到去注册的按钮（#landing-page-tpl 里的 lp-register-btn）'];
    btn.click(); await tick();
    return vm.pageState === 'register' ? null : [`pageState 应为 register，实为 ${vm.pageState}`];
  }],
  ['登录页点“返回首页” → 回落地页', '登录页', async () => {
    const btn = buttonWith(/返回首页/);
    if (!btn) return ['登录页上找不到“返回首页”（pageState 为 login 那一块里那颗）'];
    btn.click(); await tick();
    return vm.pageState === 'landing' ? null : [`pageState 应为 landing，实为 ${vm.pageState}`];
  }],
  ['注册页点“返回首页” → 回落地页', '注册页', async () => {
    const btn = buttonWith(/返回首页/);
    if (!btn) return ['注册页上找不到“返回首页”（pageState 为 register 那一块里那颗）'];
    btn.click(); await tick();
    return vm.pageState === 'landing' ? null : [`pageState 应为 landing，实为 ${vm.pageState}`];
  }],

  // 通用弹窗：全应用约 40 处调用 showAlert/showConfirm，靠的是"弹窗把 Promise
  // 兑现掉"这个契约。契约断了，那些调用点不会报错——它们只是永远 await 下去。
  ['通用弹窗点“确定” → 关闭', '通用弹窗', async () => {
    const btn = buttonWith(/确定/);
    if (!btn) return ['提示型弹窗上找不到“确定”按钮'];
    btn.click(); await tick();
    return vm.globalModal.show === false ? null : ['点了“确定”但 globalModal.show 仍为 true'];
  }],
  ['通用弹窗（确认）点“取消” → 关闭', '通用弹窗（确认）', async () => {
    const btn = buttonWith(/取消/);
    if (!btn) return ['确认型弹窗上找不到“取消”按钮'];
    btn.click(); await tick();
    return vm.globalModal.show === false ? null : ['点了“取消”但 globalModal.show 仍为 true'];
  }],
  ['提示型弹窗点遮罩 → 关闭', '通用弹窗', async () => {
    const el = overlay();
    if (!el) return ['找不到 .global-modal-overlay'];
    el.click(); await tick();   // 事件目标是遮罩本身，@click.self 才会触发
    return vm.globalModal.show === false ? null : ['点了遮罩但提示型弹窗没关'];
  }],
  ['确认型弹窗点遮罩 → 不关闭', '通用弹窗（确认）', async () => {
    const el = overlay();
    if (!el) return ['找不到 .global-modal-overlay'];
    el.click(); await tick();
    return vm.globalModal.show === true ? null : ['确认型弹窗被遮罩点掉了（模板里应当排除 confirm）'];
  }],
  ['showConfirm 的 Promise 被“确定”兑现为 true', '通用弹窗（确认）', async () => {
    let settled;
    // 走真实入口，而不是直接改 globalModal —— 要验的正是这个契约本身。
    Promise.resolve(vm.showConfirm('探针')).then(value => { settled = value; });
    await tick();
    const btn = buttonWith(/确定/);
    if (!btn) return ['确认型弹窗上找不到“确定”按钮'];
    btn.click(); await tick();
    return settled === true ? null : [`Promise 应兑现为 true，实为 ${JSON.stringify(settled)}`];
  }],
  ['showConfirm 的 Promise 被“取消”兑现为 false', '通用弹窗（确认）', async () => {
    let settled;
    Promise.resolve(vm.showConfirm('探针')).then(value => { settled = value; });
    await tick();
    const btn = buttonWith(/取消/);
    if (!btn) return ['确认型弹窗上找不到“取消”按钮'];
    btn.click(); await tick();
    return settled === false ? null : [`Promise 应兑现为 false，实为 ${JSON.stringify(settled)}`];
  }],

  // 这一组一律走真实按钮：注入能证明"弹窗渲染得对"，证明不了"点得开"，
  // 而拆分模板块要拆坏的恰恰是后者。注入只用来摆前置状态。
  //
  // 已知边界：从大厅切到「个人中心」用的是注入（真实接线会调
  // loadVoiceprintStatus()，触网），从「个人中心」再点开 AI 弹窗则是真点击。
  ['大厅（学生）点“加入课堂” → 开进入课堂弹窗', '大厅（学生）', async () => {
    // 匹配到的是文档序第一个，即**侧栏那颗**；大厅首页里还有一颗文案相同。
    // 两颗都写 `showClassModal = true`，选哪颗都成立。
    const btn = buttonWith(/加入课堂/);
    if (!btn) return ['大厅（学生）上找不到“加入课堂”按钮（侧栏或大厅首页那颗）'];
    btn.click(); await tick();
    return vm.showClassModal === true ? null : [`点了“加入课堂”但 showClassModal 为 ${vm.showClassModal}`];
  }],
  ['大厅（教师）点“创建课堂” → 开进入课堂弹窗', '大厅（教师）', async () => {
    const btn = buttonWith(/创建课堂/);
    if (!btn) return ['大厅（教师）上找不到“创建课堂”按钮（侧栏或大厅首页那颗）'];
    btn.click(); await tick();
    return vm.showClassModal === true ? null : [`点了“创建课堂”但 showClassModal 为 ${vm.showClassModal}`];
  }],
  ['进入课堂弹窗点“×” → 关', '进入课堂弹窗', async () => {
    const { el, why } = screenOverlay();
    if (!el) return [why];
    const btn = closeButtonIn(el);
    if (!btn) return ['进入课堂弹窗里找不到带 .fa-times 的按钮（弹窗头部那颗）'];
    btn.click(); await tick();
    return vm.showClassModal === false ? null : ['点了弹窗的“×”但 showClassModal 仍为 true'];
  }],
  ['进入课堂弹窗点遮罩 → 关', '进入课堂弹窗', async () => {
    const { el, why } = screenOverlay();
    if (!el) return [why];
    el.click(); await tick();   // 目标是遮罩自身，@click.self 才会触发（showClassModal 那个 .fixed.inset-0）
    return vm.showClassModal === false ? null : ['点了遮罩但进入课堂弹窗没关'];
  }],
  ['个人中心点“开始对话” → 开 AI 辅导弹窗', '个人中心（学生）', async () => {
    const btn = buttonWith(/开始对话/);
    if (!btn) return ['个人中心上找不到“开始对话”按钮（个人中心那一页里那颗）'];
    btn.click(); await tick();
    return vm.showAITutor === true ? null : [`点了“开始对话”但 showAITutor 为 ${vm.showAITutor}`];
  }],
  ['AI 辅导弹窗点“×” → 关', 'AI 辅导弹窗', async () => {
    const { el, why } = screenOverlay();
    if (!el) return [why];
    const btn = closeButtonIn(el);
    if (!btn) return ['AI 辅导弹窗里找不到带 .fa-times 的按钮（弹窗头部那颗）'];
    btn.click(); await tick();
    return vm.showAITutor === false ? null : ['点了弹窗的“×”但 showAITutor 仍为 true'];
  }],
  ['AI 辅导弹窗点遮罩 → 关', 'AI 辅导弹窗', async () => {
    const { el, why } = screenOverlay();
    if (!el) return [why];
    el.click(); await tick();   // 同上（showAITutor 那个 .fixed.inset-0）
    return vm.showAITutor === false ? null : ['点了遮罩但 AI 辅导弹窗没关'];
  }],
  // 侧栏里 8 个切页按钮只有 4 个是纯赋值，另外 4 个顺带调了触网方法
  // （studentReports / history / report / profile 那四个）——只取纯的那类。
  ['大厅（教师）点“设置” → 切到设置页', '大厅（教师）', async () => {
    const btn = buttonWith(/^设置$/);
    if (!btn) return ['侧栏上找不到文字恰为“设置”的按钮（切页那一列里那颗）'];
    btn.click(); await tick();
    return vm.activeTab === 'settings' ? null : [`activeTab 应为 settings，实为 ${vm.activeTab}`];
  }],
];

// ---------------------------------------------------------------------------

(async () => {
  const out = { states: {}, clicks: {}, notes: [] };

  for (const [name] of STATES) {
    try {
      // 同样走 goto：快照这一轮也必须是"从初始实例摆出来的状态"，否则弹窗
      // 状态会叠加，且叠加会削弱冻结检测（真冻住了也可能算出旧哈希）。
      await goto(name);
      const text = snapshot();
      out.states[name] = { hash: hash(text), length: text.length };
      // 冻结检测：渲染抛错时 DOM 会保留上一次的成功快照。同一个哈希出现在两个
      // 语义不同的状态里，几乎一定是这个原因，必须浮到报告面上。
    } catch (error) {
      out.states[name] = { error: error.message };
    }
  }

  const seenHash = new Map();
  out.collisions = [];
  for (const [name, result] of Object.entries(out.states)) {
    if (!result.hash) continue;
    if (seenHash.has(result.hash)) {
      out.collisions.push(`${seenHash.get(result.hash)} ≡ ${name}`);
    } else {
      seenHash.set(result.hash, name);
    }
  }

  for (const [name, from, run] of CLICKS) {
    try {
      await goto(from);            // 前置状态自己建，不依赖上一条的残留
      const problems = await run();
      out.clicks[name] = problems ? { problems } : { ok: true };
    } catch (error) {
      out.clicks[name] = { problems: [error.message] };
    }
  }

  // 从运行时取根实例**真正注册**了哪些 watch：JS 对象字面量对重复键是
  // "后者整体胜出"，静态扫源码不可靠。
  out.watch_keys = Object.keys(vm.$options.watch || {}).sort();

  const counted = new Map();
  for (const note of notes) counted.set(note, (counted.get(note) || 0) + 1);
  out.notes = [...counted].map(([note, times]) => (times > 1 ? `${note}  ×${times}` : note));

  if (JSON_ONLY) {
    process.stdout.write(JSON.stringify(out, null, 2) + '\n');
  } else {
    const lines = ['=== 多状态 DOM 快照 ==='];
    for (const [name, result] of Object.entries(out.states)) {
      lines.push(result.error
        ? `  ${name.padEnd(18)} ✗ ${result.error}`
        : `  ${name.padEnd(18)} ${result.hash}  ${result.length.toLocaleString()} 字符`);
    }
    if (out.collisions.length) {
      lines.push('', '!! 有状态算出相同哈希（渲染多半抛错了，DOM 冻在上一次快照）:');
      for (const c of out.collisions) lines.push(`   ${c}`);
    }
    lines.push('', '=== 点击序列（事件接线；只覆盖不触网的路由类接线）===');
    for (const [name, result] of Object.entries(out.clicks)) {
      lines.push(result.ok ? `  ✓ ${name}` : `  ✗ ${name}\n      ${result.problems.join('\n      ')}`);
    }
    if (out.notes.length) {
      lines.push('', '=== 页内告警/错误（去重）===');
      for (const note of out.notes.slice(0, 10)) lines.push(`  ${note.slice(0, 160)}`);
    }
    lines.push('', `状态数 ${Object.keys(out.states).length}，接线 ${Object.keys(out.clicks).length}`);
    process.stdout.write(lines.join('\n') + '\n');
  }

  if (WRITE) {
    fs.mkdirSync(path.dirname(BASELINE), { recursive: true });
    fs.writeFileSync(BASELINE, JSON.stringify(out, null, 2) + '\n', 'utf8');
    if (!JSON_ONLY) process.stdout.write(`\n基线已写出：${path.relative(ROOT, BASELINE)}\n`);
  }
})();
