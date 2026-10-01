"""GUI 的前端资源（单页，内嵌 CSS/JS，无需任何外部文件）。

配色只用两个颜色，靠透明度分层：
    深色 #333319   —— 背景
    浅色 #E5FFFF   —— 前景 / 描边 / 强调（hover 时反转）

尺寸系统
--------
全页**没有任何写死的 px 尺寸**。只有一个来源：

    --u = clamp(9px, 0.58vw + 0.9vh, 22px) * var(--k)

  * 由窗口「宽 + 高」共同决定，所以横竖比例变化时整体跟着变
  * clamp 上下限防止极端窗口下失控
  * --k 是用户缩放系数（页头 A- / A+，存 localStorage）

其余所有尺寸（字号、内外边距、间距、描边粗细、卡片最小宽、内容最大宽……）
一律写成 calc(var(--u) * n)，改一处即可整体缩放。
"""

PALETTE = {"dark": "#333319", "light": "#E5FFFF"}

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBRA DINN · 存档工具</title>
<style>
/* ---------------- 字体 ----------------
   gui/fonts/ 下两款：英文字母优先 IMFe（IM FELL English Roman），
   中文/日文及其他 IMFe 没有的字形自动回落到 Source Han Serif SC。
   子集化等工作等项目成熟后再做。 */
@font-face{
  font-family:"IMFe";
  src:url("/fonts/IMFeENrm28P.ttf") format("truetype");
  font-weight:400;font-style:normal;font-display:swap;
}
@font-face{
  font-family:"SourceHanSerif";
  src:url("/fonts/SourceHanSerifSC-SemiBold-subset.otf") format("opentype");
  font-weight:400;font-style:normal;font-display:swap;
}

:root{
  /* 字体栈：英文 IMFe → 中文 SourceHanSerif → 系统衬线兼容回退 */
  --font:"IMFe","SourceHanSerif","Songti SC","SimSun","Noto Serif CJK SC",Georgia,serif;
  /* ================= 尺寸来源：只有这一处 =================
     正文字号 fs 由窗口「宽 + 高」共同决定，再夹在 12~16.5px；
     尺寸单位 u = 1.25 * fs；--k 是用户缩放系数（页头 A- / A+）。
     其余所有尺寸一律 calc 派生，改这里即整体缩放。 */
  --fs-base: clamp(12px, 0.55vw + 0.72vh, 16.5px);
  --k: 1;
  --fs: calc(var(--fs-base) * var(--k));
  --u:  calc(var(--fs) * 1.25);

  /* ---------- 颜色 ---------- */
  --d:#333319;
  --l:#E5FFFF;
  --l-72:rgba(229,255,255,.72);
  --l-50:rgba(229,255,255,.50);
  --l-30:rgba(229,255,255,.30);
  --l-18:rgba(229,255,255,.18);
  --l-08:rgba(229,255,255,.08);
  --l-04:rgba(229,255,255,.04);

  /* ---------- 字号（相对于正文） ---------- */
  --fs-sm:  calc(var(--fs) * 0.85);
  --fs-xs:  calc(var(--fs) * 0.74);
  --fs-h1:  calc(var(--fs) * 1.45);
  --fs-h2:  calc(var(--fs) * 0.95);
  --fs-tag: calc(var(--fs) * 1.30);
  --fs-big: calc(var(--fs) * 1.80);
  --fs-btn: calc(var(--fs) * 0.85);

  /* ---------- 间距（相对于单位 u） ---------- */
  --gap:      calc(var(--u) * 0.75);
  --gap-sm:   calc(var(--u) * 0.38);
  --pad-page: calc(var(--u) * 1.30);
  --pad-card: calc(var(--u) * 0.90);
  --pad-btn:  calc(var(--u) * 0.30) calc(var(--u) * 0.64);
  --pad-tag:  calc(var(--u) * 0.04) calc(var(--u) * 0.46);

  /* ---------- 线宽 / 尺寸 ---------- */
  --bw:      max(1px, calc(var(--u) * 0.05));
  --bw-2:    max(1px, calc(var(--u) * 0.09));
  --bar:     max(2px, calc(var(--u) * 0.16));
  --w-page:  calc(var(--u) * 68);
  --w-card:  calc(var(--u) * 17);
  --w-toast: calc(var(--u) * 30);
  --w-meta:  calc(var(--u) * 5.2);
}

*{box-sizing:border-box}
/* 不显示滚动条（滚轮照常滚）：
   scrollbar-width 管 Firefox 与新版 Chromium，::-webkit-scrollbar 管旧版 Chromium */
*{scrollbar-width:none}
*::-webkit-scrollbar{width:0;height:0}
html,body{margin:0;padding:0}
body{
  background:var(--d);color:var(--l);
  font-family:var(--font);
  font-size:var(--fs);line-height:1.55;
}
.wrap{
  max-width:var(--w-page);
  margin:0 auto;
  padding:var(--pad-page) calc(var(--pad-page) * 0.85) calc(var(--u) * 2.6);
}

h1,h2{
  font-family:var(--font);
  font-weight:400;margin:0;letter-spacing:.16em;text-transform:uppercase;
}
h1{font-size:var(--fs-h1)}
h2{
  font-size:var(--fs-h2);color:var(--l-72);
  border-bottom:var(--bw) solid var(--l-30);
  padding-bottom:calc(var(--u) * 0.42);
  margin:calc(var(--u) * 2.4) 0 var(--gap);
}
h2 small{
  font-family:inherit;text-transform:none;letter-spacing:0;
  color:var(--l-50);font-size:var(--fs-sm);
  margin-left:calc(var(--u) * 0.85);
}

header{display:flex;align-items:flex-end;justify-content:space-between;
       gap:calc(var(--u) * 1.2);flex-wrap:wrap;
       border-bottom:var(--bw-2) solid var(--l);
       padding-bottom:calc(var(--u) * 0.75)}
.sub{color:var(--l-50);font-size:var(--fs-sm);margin-top:calc(var(--u) * 0.24)}
.sub b{color:var(--l-72);font-weight:400}

.tools{display:flex;gap:var(--gap-sm);flex-wrap:wrap;align-items:center}

.scale{display:flex;align-items:center;gap:calc(var(--u) * 0.28);
       border:var(--bw) solid var(--l-30);padding:calc(var(--u) * 0.16)}
.scale b{font-weight:400;font-size:var(--fs-xs);color:var(--l-50);
         min-width:calc(var(--u) * 2.4);text-align:center}
.scale button{padding:calc(var(--u) * 0.12) calc(var(--u) * 0.42);border:none}

button{
  font:inherit;font-size:var(--fs-btn);letter-spacing:.09em;text-transform:uppercase;
  background:transparent;color:var(--l);border:var(--bw) solid var(--l-50);
  padding:var(--pad-btn);cursor:pointer;white-space:nowrap;
  transition:background .12s ease,color .12s ease,border-color .12s ease;
}
button:hover:not(:disabled){background:var(--l);color:var(--d);border-color:var(--l)}
button:disabled{opacity:.3;cursor:not-allowed}

.grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(var(--w-card),1fr));
  gap:var(--gap);
}

.card{
  border:var(--bw) solid var(--l-30);background:var(--l-04);
  padding:var(--pad-card);
  display:flex;flex-direction:column;gap:calc(var(--u) * 0.72);
}
.card.is-slot{border-color:var(--l-50)}
.card.is-preset{border-color:var(--l-50);background:var(--l-08)}
.card.empty{border-style:dashed;opacity:.55}
.card.bad{background:transparent}

.chead{display:flex;align-items:baseline;justify-content:space-between;
       gap:var(--gap-sm)}
.tag{
  font-size:var(--fs-tag);letter-spacing:.1em;white-space:nowrap;
  border:var(--bw) solid var(--l);padding:var(--pad-tag);line-height:1.3;
}
.fname{font-size:var(--fs-sm);color:var(--l-50);word-break:break-all;
       text-align:right;line-height:1.35}

/* 卡片正面：解对数与说明同行基线对齐（不换行），字号/字重/颜色不变 */
.stats{display:flex;gap:calc(var(--u) * 1.0);align-items:flex-end}
.stat{display:flex;align-items:baseline;gap:calc(var(--u) * 0.3)}
.stat>b{
  display:block;font-size:var(--fs-big);font-weight:400;line-height:1.0;
}
.stat>span{
  display:block;font-size:var(--fs-xs);letter-spacing:.1em;
  text-transform:uppercase;color:var(--l-50);white-space:nowrap;
}
.bar{height:var(--bar);background:var(--l-18);margin-top:calc(var(--u) * -0.15)}
.bar>i{display:block;height:100%;background:var(--l)}

/* 卡片正面：只放四项 */
.facts{
  display:grid;grid-template-columns:var(--w-meta) 1fr;
  gap:calc(var(--u) * 0.2) calc(var(--u) * 0.55);
  margin:0;font-size:var(--fs);
}
.facts dt{color:var(--l-50);white-space:nowrap}
.facts dd{margin:0;color:var(--l);word-break:break-all}
.mono{letter-spacing:.01em}

/* ---------------- 详细信息浮层 ---------------- */
body.locked{overflow:hidden}
.modal{
  position:fixed;inset:0;z-index:60;display:none;
  background:rgba(51,51,25,.88);
  padding:calc(var(--u) * 1.4);overflow:auto;
}
.modal.on{display:flex}
.panel{
  margin:auto;                      /* 双向居中；用 margin:auto 而不是 align-items，
                                       内容超高时才不会被裁掉顶部 */
  border:var(--bw-2) solid var(--l);background:var(--d);
  width:100%;max-width:calc(var(--u) * 60);
  max-height:calc(100vh - var(--u) * 3.2);
  padding:var(--pad-card);
  display:flex;flex-direction:column;gap:calc(var(--u) * 0.6);
}
.panel .head{
  display:flex;align-items:center;justify-content:space-between;
  gap:var(--gap);border-bottom:var(--bw) solid var(--l-30);
  padding-bottom:calc(var(--u) * 0.4);
}
.panel .head h3{
  font-family:var(--font);font-weight:400;
  font-size:calc(var(--fs) * 1.25);letter-spacing:.12em;margin:0;
  word-break:break-all;min-width:0;
}
.panel .head .x{padding:calc(var(--u) * 0.04) calc(var(--u) * 0.5)}
/* 正文网格 4 列：普通项 = 一行两项；加 .wide 的项跨两列 = 一行一项 */
.panel .body{
  overflow:auto;flex:1;min-height:0;
  display:grid;
  grid-template-columns:calc(var(--u) * 7.4) 1fr calc(var(--u) * 7.4) 1fr;
  gap:calc(var(--u) * 0.16) calc(var(--u) * 0.4);
  margin:0;font-size:var(--fs);
  align-content:start;
}
.panel .body dt{color:var(--l-50);white-space:nowrap}
.panel .body dd{margin:0;color:var(--l-72);word-break:break-all;
                padding-right:calc(var(--u) * 0.9)}
/* 整行项：标签占第 1 列，值跨后 3 列 */
.panel .body .full{grid-column:span 3}
.panel .sect{
  grid-column:1/-1;color:var(--l);
  letter-spacing:.14em;text-transform:uppercase;font-size:var(--fs-xs);
  margin-top:calc(var(--u) * 0.55);
  border-bottom:var(--bw) solid var(--l-18);
  padding-bottom:calc(var(--u) * 0.15);
}
.panel .sect:first-child{margin-top:0}

.acts{display:flex;gap:calc(var(--u) * 0.36);flex-wrap:wrap;
      margin-top:auto;padding-top:calc(var(--u) * 0.2)}

table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}
th,td{
  text-align:left;vertical-align:middle;
  padding:calc(var(--u) * 0.36) calc(var(--u) * 0.7) calc(var(--u) * 0.36) 0;
  border-bottom:var(--bw) solid var(--l-08);
}
th{
  color:var(--l-50);font-weight:400;letter-spacing:.1em;text-transform:uppercase;
  font-size:var(--fs-xs);border-bottom-color:var(--l-30);
}
td.num{font-size:var(--fs)}
td.act{text-align:right;white-space:nowrap}

.tabs{display:flex;gap:calc(var(--u) * 0.32);margin-bottom:var(--gap)}
.tabs button[aria-selected="true"]{background:var(--l);color:var(--d);border-color:var(--l)}

.note{color:var(--l-50);font-size:var(--fs-sm)}
.pill{border:var(--bw) solid var(--l-30);padding:0 calc(var(--u) * 0.36);
      font-size:var(--fs-xs);letter-spacing:.08em;color:var(--l-72)}

#toast{
  position:fixed;left:50%;transform:translateX(-50%);
  bottom:calc(var(--u) * 1.6);
  display:flex;flex-direction:column;gap:calc(var(--u) * 0.5);
  align-items:center;pointer-events:none;z-index:50;
}
#toast div{
  border:var(--bw) solid var(--l);background:var(--d);color:var(--l);
  padding:calc(var(--u) * 0.5) calc(var(--u) * 0.95);
  font-size:var(--fs-sm);max-width:var(--w-toast);
}
#toast div.err{border-style:dashed}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div>
      <h1>Obra Dinn · 存档工具</h1>
      <div class="sub" id="sub">正在读取…</div>
    </div>
    <div class="tools">
      <div class="scale">
        <button onclick="zoom(-1)" title="缩小">A-</button>
        <b id="zk">100%</b>
        <button onclick="zoom(1)" title="放大">A+</button>
      </div>
      <input type="file" id="up" accept=".txt" hidden>
      <button onclick="document.getElementById('up').click()">导入文件到存档库</button>
      <button onclick="refresh(true)">重新读取</button>
      <button onclick="doQuit()">退出程序</button>
    </div>
  </header>

  <h2>游戏槽位 <small>写入前会自动备份</small></h2>
  <div class="grid" id="slots"></div>

  <h2>预制存档 <small>随程序分发 · 只读；装到槽位后随便改</small></h2>
  <div class="grid" id="presets"></div>

  <h2>存档库 <small id="libpath"></small></h2>
  <div class="grid" id="lib"></div>

  <h2>备份 <small>含游戏自带的 -Recent 快照</small></h2>
  <div class="tabs" id="tabs"></div>
  <div id="bk"></div>
</div>

<div id="toast"></div>

<div class="modal" id="modal" onclick="if(event.target===this)closeDetail()">
  <div class="panel">
    <div class="head">
      <h3 id="panelTitle">详细信息</h3>
      <button class="x" onclick="closeDetail()">关闭</button>
    </div>
    <dl class="body" id="panelBody"></dl>
  </div>
</div>

<script>
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

/* ---------------- 尺寸：唯一单位 u + 用户缩放 k ---------------- */
const ZOOM_KEY = 'obradinn.zoom';
let zoomK = parseFloat(localStorage.getItem(ZOOM_KEY) || '1');
if (!isFinite(zoomK) || zoomK <= 0) zoomK = 1;

function applyZoom(){
  document.documentElement.style.setProperty('--k', zoomK.toFixed(3));
  $('#zk').textContent = Math.round(zoomK * 100) + '%';
  localStorage.setItem(ZOOM_KEY, String(zoomK));
}
function zoom(dir){ zoomK = Math.min(2.4, Math.max(0.55, zoomK + dir * 0.08)); applyZoom(); }

function toast(msg, isErr){
  const d = document.createElement('div');
  if (isErr) d.className = 'err';
  d.textContent = msg;
  $('#toast').appendChild(d);
  setTimeout(() => d.remove(), isErr ? 6500 : 3200);
}

async function api(path, body){
  const opt = body
    ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}
    : undefined;
  let r, j;
  try { r = await fetch(path, opt); j = await r.json(); }
  catch(e){ throw new Error('无法连接本地服务：' + e.message); }
  if (!j.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

/* era 0/1/2/3 —— 内部键仍是 save_tool.describe() 的 phase 值，只是显示名换了 */
const PHASE_NAME = {'on-ship':'调查','ready-to-leave':'推理','tally':'保险评估','office':'办公室'};
const ENDING_NAME = {win:'好结局', mid:'中等结局', fail:'坏结局'};
const DELIVERY_NAME = {package:'包裹', envelope:'信封'};
const sex = g => (g === 'female' ? '女' : '男');

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const jsq = s => String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");

function statsHtml(i){
  const pct = Math.round(i.fates_correct / i.crew_total * 100);
  return `<div class="stats">
      <div class="stat"><b>${i.fates_correct}</b><span>/ ${i.crew_total} 解对</span></div>
    </div>
    <div class="bar"><i style="width:${pct}%"></i></div>`;
}

/* 卡片正面：只有这四项 */
function factsHtml(i){
  return `<dl class="facts">
    <dt>阶段</dt><dd>${PHASE_NAME[i.phase] || i.phase}</dd>
    <dt>结局走向</dt><dd>${ENDING_NAME[i.ending] || i.ending}</dd>
    <dt>主人公性别</dt><dd>${sex(i.gender)}</dd>
    <dt>已解锁章节数</dt><dd>${i.charts_revealed} / 10</dd>
  </dl>`;
}

function fmtTime(sec){
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return (h ? h + ' 时 ' : '') + (h || m ? m + ' 分 ' : '') + s + ' 秒';
}

const yn = b => (b ? '是' : '否');

function card(row, kind, tag){
  const preset = kind === 'preset';
  const name = row.name || (row.slot + ' · ObraDinnSave-' + row.slot + '.txt');
  if (!row.exists){
    return `<article class="card empty">
      <div class="chead"><span class="tag">${tag}</span><span class="fname">空槽位</span></div>
      <div class="note">这个槽位里还没有存档。</div>
    </article>`;
  }
  if (!row.ok){
    return `<article class="card bad">
      <div class="chead"><span class="tag">${tag}</span><span class="fname">${esc(name)}</span></div>
      <div class="note">无法解析：${esc(row.error)}</div>
    </article>`;
  }
  const i = row.info;
  const p = jsq(row.path);
  const install = `<button onclick="doImport('P1','${p}')">装到 P1</button>
       <button onclick="doImport('P2','${p}')">装到 P2</button>
       <button onclick="doImport('P3','${p}')">装到 P3</button>`;
  const acts = kind === 'slot'
    ? `<button onclick="doExport('${p}')">导出到存档库</button>
       <button onclick="dl('${p}')">下载</button>
       <button onclick="doGender('${p}')">切换性别</button>
       <button onclick="openDetail('${p}')">详细信息</button>`
    : preset
    ? `${install}
       <button onclick="dl('${p}')">下载</button>
       <button onclick="openDetail('${p}')">详细信息</button>`
    : `${install}
       <button onclick="doGender('${p}')">切换性别</button>
       <button onclick="dl('${p}')">下载</button>
       <button onclick="doDelete('${p}')">删除</button>
       <button onclick="openDetail('${p}')">详细信息</button>`;
  // 预制存档用注释名当标签（文件名保持规范，放在第二行）
  const label = preset ? (row.comment || name) : tag;
  const sub = preset ? row.bytes + ' B' : row.bytes + ' B · ' + (row.mtime || '');
  return `<article class="card ${kind === 'slot' ? 'is-slot' : (preset ? 'is-preset' : '')}">
    <div class="chead">
      <span class="tag">${esc(label)}</span>
      <span class="fname">${esc(name)}<br>${sub}</span>
    </div>
    ${statsHtml(i)}
    ${factsHtml(i)}
    <div class="acts">${acts}</div>
  </article>`;
}

function rowByPath(path){
  return [...(STATE.slots || []), ...(STATE.presets || []), ...(STATE.library || [])]
    .find(r => r.path === path && r.exists && r.ok);
}

function openDetail(path){
  const row = rowByPath(path);
  if (!row){ toast('无法读取该存档的详细信息', true); return; }
  const i = row.info;
  // full=true → 标签占 1 列、值跨后 3 列（整行一项）；否则一行两项
  const D = (k, v, full) => `<dt>${k}</dt>`
                          + `<dd${full ? ' class="full"' : ''}>${v}</dd>`;
  $('#panelTitle').textContent = row.comment || row.name || row.slot;
  $('#panelBody').innerHTML =
      '<div class="sect">存档</div>'
    + (row.comment ? D('注释', esc(row.comment), true) : '')
    + D('路径', esc(row.path), true)
    + D('大小', row.bytes + ' B', true)
    + D('修改时间', row.mtime || '—', true)
    + D('sha256', '<span class="mono">' + i.sha256 + '</span>', true)
    + '<div class="sect">进度</div>'
    + D('阶段', (PHASE_NAME[i.phase] || i.phase) + '（era ' + i.era + '）')
    + D('结局走向', (ENDING_NAME[i.ending] || i.ending) + ' · '
        + (DELIVERY_NAME[i.delivery] || i.delivery))
    + D('解对数', i.fates_correct + ' / ' + i.crew_total)
    + D('船上区', i.ship_correct + ' / ' + i.ship_total)
    + D('办公室区', i.office_correct + ' / ' + i.office_total)
    + D('空白脸', i.blank_faces + ' / ' + i.faces_total)
    + D('已访问书页', i.moments_visited + ' / ' + i.moments_total)
    + D('已解锁章节数', i.charts_revealed + ' / 10')
    + '<div class="sect">其他</div>'
    + D('主人公性别', sex(i.gender))
    + D('已看过末页', yn(i.bookVisitedLastPage))
    + D('包裹已送达', yn(i.officePackageReady))
    + D('已拿到猴爪', yn(i.officePawReady))
    + D('已用猴爪看破书页', yn(i.officeHaveRevealedBook))
    + D('已通关过', yn(i.officeEndedOnce))
    + D('游玩时长', fmtTime(i.playTime));
  $('#modal').classList.add('on');
  document.body.classList.add('locked');
}

function closeDetail(){
  $('#modal').classList.remove('on');
  document.body.classList.remove('locked');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

let STATE = null;

function render(st){
  STATE = st;
  $('#sub').innerHTML = '存档目录 <b>' + esc(st.saveDir) + '</b>'
    + (st.saveDirExists ? '' : ' <span class="pill">不存在</span>');
  $('#libpath').textContent = st.libraryDir;

  $('#slots').innerHTML = st.slots.map(s => card(s, 'slot', s.slot)).join('');

  const pre = st.presets || [];
  $('#presets').innerHTML = pre.length
    ? pre.map(r => card(r, 'preset', '')).join('')
    : '<div class="note">这个副本里没有预制存档。</div>';

  $('#lib').innerHTML = st.library.length
    ? st.library.map(r => card(r, 'lib', '存档')).join('')
    : '<div class="note">存档库是空的。用右上角「导入文件到存档库」，或从某个槽位「导出到存档库」。</div>';

  $('#tabs').innerHTML = ['P1','P2','P3'].map((s, n) =>
    `<button aria-selected="${n === 0}" onclick="loadBackups('${s}', this)">${s}</button>`).join('');
  loadBackups('P1');
}

async function renderBackups(slot, rows){
  const el = $('#bk');
  if (!rows.length){ el.innerHTML = '<div class="note">没有找到备份。</div>'; return; }
  el.innerHTML = `<table><thead><tr>
      <th>时间</th><th>来源</th><th>文件</th><th>内容</th><th></th>
    </tr></thead><tbody>` + rows.map(r => {
    const info = r.ok
      ? `${r.info.fates_correct}/${r.info.crew_total} 解对 · ${PHASE_NAME[r.info.phase] || r.info.phase} · ${sex(r.info.gender)}`
      : '无法解析';
    return `<tr>
      <td class="num">${r.mtime}</td>
      <td><span class="pill">${r.source}</span></td>
      <td class="mono" style="color:var(--l-50)">${esc(r.name)}</td>
      <td>${esc(info)}</td>
      <td class="act"><button onclick="doRestore('${slot}','${jsq(r.path)}')">恢复到 ${slot}</button></td>
    </tr>`;
  }).join('') + '</tbody></table>';
}

async function loadBackups(slot, btn){
  if (btn) $$('#tabs button').forEach(b => b.setAttribute('aria-selected', b === btn));
  try {
    const j = await api('/api/backups?slot=' + slot);
    await renderBackups(slot, j.backups);
  } catch(e){ toast(e.message, true); }
}

async function refresh(loud){
  try {
    const st = await api('/api/state');
    render(st);
    if (loud) toast('已重新读取');
  } catch(e){ toast(e.message, true); }
}

function busy(fn){
  return async (...a) => {
    const btns = $$('button');
    btns.forEach(b => b.disabled = true);
    try { await fn(...a); }
    catch(e){ toast(e.message, true); }
    finally { btns.forEach(b => b.disabled = false); }
  };
}

const doImport = busy(async (slot, path) => {
  if (!confirm('把这份存档写入游戏槽位 ' + slot + '？\n原内容会先自动备份。')) return;
  const r = await api('/api/import', {slot, path});
  toast('已装入 ' + slot + '（' + r.bytes + ' B）· 备份 ' + r.backups.length + ' 份');
  await refresh();
});

const doExport = busy(async (path) => {
  const r = await api('/api/export', {path});
  toast('已导出到存档库');
  await refresh();
});

const doGender = busy(async (path) => {
  const r = await api('/api/gender', {path, gender:'toggle'});
  if (!r.changed) toast('性别未变化');
  else toast('主人公已切换为 ' + (r.gender === 'female' ? '女' : '男') + '（原文件已备份）');
  await refresh();
});

const doDelete = busy(async (path) => {
  if (!confirm('把这份存档移到存档库的 _trash？')) return;
  await api('/api/delete', {path});
  toast('已移入 _trash');
  await refresh();
});

const doRestore = busy(async (slot, path) => {
  if (!confirm('用这份备份覆盖槽位 ' + slot + '？\n当前内容会先自动备份。')) return;
  const r = await api('/api/import', {slot, path});
  toast('已从备份恢复 ' + slot);
  await refresh();
});

function dl(path){ location.href = '/api/download?path=' + encodeURIComponent(path); }

/* 打包成 --windowed 后没有控制台，Ctrl+C 用不了 —— 这是唯一的正规退出方式 */
const doQuit = busy(async () => {
  if (!confirm('退出程序？\n浏览器页面不会自己关，关掉即可。')) return;
  await api('/api/quit', {});
  toast('已退出，可以关闭这个页面了');
});

$('#up').addEventListener('change', async ev => {
  const f = ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  const buf = await f.arrayBuffer();
  let bin = '';
  const u8 = new Uint8Array(buf);
  for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
  try {
    const r = await api('/api/upload', {name:f.name, data:btoa(bin)});
    toast('已加入存档库（' + r.bytes + ' B）');
    await refresh();
  } catch(e){ toast(e.message, true); }
});

applyZoom();
refresh();
</script>
</body>
</html>
"""
