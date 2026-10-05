#!/usr/bin/env python3
"""难度补丁器前端（单文件 HTML，内联 CSS/JS，无外部依赖）。"""
from __future__ import annotations

#: 与《奥伯拉丁的回归》排版风格一致的配色（和存档工具同款）
PALETTE = {"dark": "#333319", "light": "#E5FFFF", "paper": "#e8e2cf",
           "ink": "#2b2b20", "accent": "#8c2f1f", "ok": "#3f6b3a",
           "warn": "#8a6a1f"}

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>《奥伯拉丁的回归》难度补丁</title>
<style>
  /* 字体用的是存档工具同款那两款（已按本项目字符集子集化到 assets/fonts/）：
     英文优先 IMFe（IM FELL English Roman），中文回落到思源宋体 SemiBold。 */
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
    --dark:#333319; --light:#E5FFFF; --paper:#e8e2cf; --ink:#2b2b20;
    --accent:#8c2f1f; --ok:#3f6b3a; --warn:#8a6a1f; --line:#c9c2a8;
    --font:"IMFe","SourceHanSerif","Songti SC","SimSun",
           "Noto Serif CJK SC",Georgia,serif;
  }
  *{box-sizing:border-box}
  /* 一律不要圆角：上面各处已逐个清掉，这条再拦住以后新加的 */
  *,*::before,*::after{border-radius:0 !important}
  /* 去掉所有滑动条：页面仍可用滚轮/键盘滚动，只是不显示条。 */
  html{scrollbar-width:none; -ms-overflow-style:none}
  html::-webkit-scrollbar,body::-webkit-scrollbar,
  #log::-webkit-scrollbar,table::-webkit-scrollbar{width:0;height:0}
  body{
    margin:0; padding:0 0 3rem;
    background:#1b1b13;
    color:#e5e0cd;
    overflow-x:hidden;
    font:15px/1.6 var(--font);
  }
  header{
    background:var(--dark); border-bottom:2px solid #000;
    padding:1.1rem 1.5rem; display:flex; align-items:baseline; gap:1rem;
    flex-wrap:wrap;
  }
  header h1{margin:0; font-size:1.25rem; letter-spacing:.04em; color:var(--light)}
  header .sub{color:#b9b39a; font-size:.85rem}
  main{max-width:980px; margin:0 auto; padding:1.4rem 1.2rem}
  section{
    background:#26261c; border:1px solid #43432f;
    padding:1.1rem 1.2rem; margin-bottom:1.1rem;
  }
  section > h2{
    margin:0 0 .9rem; font-size:1rem; font-weight:600; color:var(--light);
    letter-spacing:.05em; border-bottom:1px solid #43432f; padding-bottom:.5rem;
  }
  .row{display:flex; gap:.6rem; align-items:baseline; padding:.28rem 0;
       flex-wrap:wrap}
  .row .k{min-width:8.5rem; color:#a9a48c; font-size:.9rem}
  /* 游戏位置、槽位号、登记计数这些也要用规定字体 ——
     原来写的 Consolas/monospace 会让它们走另一套字形。 */
  .row .v{font-family:var(--font); font-size:.9rem; word-break:break-all}
  .badge{display:inline-block; padding:.08rem .5rem;
         font-size:.82rem; font-family:var(--font)}
  .badge.ok{background:#2c4429; color:#a8d8a0; border:1px solid #3f6b3a}
  .badge.bad{background:#4a1f18; color:#f0b3a6; border:1px solid #8c2f1f}
  .badge.dim{background:#33331f; color:#a9a48c; border:1px solid #55552f}
  .levels{display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
          gap:.6rem}
  .lv{
    border:1px solid #4d4d33; background:#2b2b1d;
    padding:.7rem .75rem; cursor:pointer; transition:.12s; position:relative;
    text-align:left; color:inherit; font:inherit;
  }
  .lv:hover{border-color:#8c8c55; background:#33331f}
  .lv[aria-pressed="true"]{border-color:var(--light); background:#3a3a26;
                           box-shadow:0 0 0 1px var(--light) inset}
  .lv .n{font-size:1.05rem; color:var(--light)}
  .lv .m{font-size:.8rem; color:#a9a48c; display:block; margin-top:.15rem}
  .lv .tag{
    position:absolute; top:.5rem; right:.55rem; font-size:.7rem;
    color:#cdc7a8; background:#1b1b13; padding:0 .3rem;
  }
  .lv[data-vanilla="1"] .n{color:#e8d9a0}
  .btns{display:flex; gap:.6rem; flex-wrap:wrap; margin-top:1rem;
        align-items:center}
  button{
    font:inherit; padding:.5rem 1.1rem; cursor:pointer;
    border:1px solid #6b6b45; background:#3d3d28; color:#e5e0cd;
    transition:.12s;
  }
  button:hover:not(:disabled){background:#4d4d33; border-color:#9a9a63}
  button.primary{background:var(--accent); border-color:#b8472f; color:#fff}
  button.primary:hover:not(:disabled){background:#a1381f}
  button:disabled{opacity:.45; cursor:not-allowed}
  label.chk{display:inline-flex; align-items:center; gap:.4rem;
            font-size:.88rem; color:#c5c0a6; cursor:pointer}
  table{width:100%; border-collapse:collapse; font-size:.9rem}
  th,td{text-align:left; padding:.45rem .5rem; border-bottom:1px solid #3b3b28}
  th{color:#a9a48c; font-weight:500; font-size:.85rem}
  td .num{font-family:var(--font)}
  td.empty{color:#6f6b58; font-style:italic}
  #log{
    font-family:var(--font); font-size:.84rem; white-space:pre-wrap;
    background:#16160f; border:1px solid #43432f;
    padding:.7rem .8rem; overflow:hidden; margin-top:.9rem;
    display:none;
  }
  /* 正在换档时的防呆：
     1) main 上关掉 pointer-events —— 鼠标点什么都不响应（含难度卡片、
        浏览按钮、输入框、复选框，不需要逐个改）
     2) 按钮另置灰，防键盘 Tab 过去按回车
     3) 顶部提示条说明在干什么 */
  #busybar{
    display:none; position:sticky; top:0; z-index:9; margin:0;
    padding:.55rem 1.2rem; background:#8c2f1f; color:#fff;
    font-size:.9rem; letter-spacing:.04em;
  }
  body.busy #busybar{display:block}
  body.busy main{opacity:.45; pointer-events:none}
  body.busy header{opacity:.75}
  /* 手动指定游戏位置 */
  .pick{display:flex; flex-wrap:wrap; gap:.45rem; align-items:center}
  .pick input{
    flex:1 1 18rem; min-width:12rem; font:inherit; font-size:.88rem;
    padding:.35rem .5rem;
    border:1px solid #4d4d33; background:#1b1b13; color:#e5e0cd;
  }
  .pick input:focus{outline:none; border-color:#9a9a63}
  .pick .hint{flex-basis:100%}
  #game-msg{flex-basis:100%; font-size:.85rem}
  #game-msg.ok{color:#a8d8a0}
  #game-msg.bad{color:#f0b3a6}
  #log.on{display:block}
  .hint{color:#a9a48c; font-size:.85rem; margin-top:.7rem}
  .warnbox{
    background:#3a2f14; border:1px solid #8a6a1f; color:#f0dfa8;
    padding:.6rem .8rem; font-size:.88rem; margin-top:.8rem;
  }
  .busy{opacity:.6; pointer-events:none}
  code{background:#1b1b13; padding:.05rem .3rem;
       font-size:.85em}
</style>
</head>
<body>
<header>
  <h1>《奥伯拉丁的回归》难度补丁</h1>
  <span class="sub" id="ver">正在读取状态…</span>
</header>
<main>

  <div id="busybar">正在处理，请稍候…</div>

  <section id="sec-state">
    <h2>当前状态</h2>
    <div class="row"><span class="k">游戏位置</span><span class="v" id="s-game">—</span></div>
    <div class="row"><span class="k">手动指定</span><span class="v pick">
      <input id="game-path" type="text" spellcheck="false" autocomplete="off"
             placeholder="例如 F:\Games\ObraDinn">
      <button id="btn-browse" type="button">浏览…</button>
      <button id="btn-usegame" type="button">用这个目录</button>
      <div class="hint">选 <b>ObraDinn.exe 所在的目录</b>——里面应当有一个
        ObraDinn_Data 文件夹（直接填 ObraDinn.exe 的完整路径也可以）。</div>
      <div id="game-msg"></div>
    </span></div>
    <div class="row"><span class="k">能否改动</span><span class="v" id="s-run">—</span></div>
    <div class="row"><span class="k">当前难度</span><span class="v" id="s-dll">—</span></div>
    <div class="row"><span class="k">书页文字</span><span class="v" id="s-lang">—</span></div>
    <div class="row"><span class="k">两者是否匹配</span><span class="v" id="s-cons">—</span></div>
    <div class="row"><span class="k">可否撤销</span><span class="v" id="s-backup">—</span></div>
    <div id="s-warn"></div>
  </section>

  <section id="sec-level">
    <h2>选择难度</h2>
    <div class="levels" id="levels"></div>
    <div class="btns">
      <button class="primary" id="btn-apply" disabled>应用所选难度</button>
      <label class="chk"><input type="checkbox" id="opt-align" checked>
        应用时自动对齐三个存档（推荐）</label>
    </div>
    <div class="hint" id="apply-hint">
      随时可以换，也能换回原来的难度。选好档位后按下面的按钮即可。
    </div>
  </section>

  <section id="sec-saves">
    <h2>存档</h2>
    <table>
      <thead><tr><th>槽位</th><th>位置</th><th>已登记 / 总数</th><th></th></tr></thead>
      <tbody id="slots"><tr><td colspan="5" class="empty">读取中…</td></tr></tbody>
    </table>
    <div class="hint">
      换难度后，旧存档里已登记的人数可能接不上新难度的节奏，会卡住无法继续。
      对齐只改「已登记」标记，<b>不动你填好的下落</b>，推理成果不会丢。
    </div>
  </section>

  <section id="sec-restore">
    <h2>撤销</h2>
    <div class="hint">
      把游戏还原到<b>你第一次使用本工具之前</b>的样子，包括你原来装过的其他汉化或补丁。
      想回到官方原版，请选上面的「简单（原版）」。
    </div>
    <div class="btns">
      <button id="btn-restore">撤销：还原到使用前</button>
    </div>
  </section>

  <div id="log"></div>
</main>

<script>
const S = {state:null, picked:null, busy:false};
const $ = id => document.getElementById(id);

function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

// 每个档位「一批几人」，以及船上/办公室各凑几批
const BATCH = {
  3 :{per:3,  ship:"18 批 + 2 人",  office:"1 批", note:"原版"},
  4 :{per:4,  ship:"14 批 + 2 人",  office:"1 批"},
  6 :{per:6,  ship:"9 批 + 2 人",   office:"1 批"},
  9 :{per:9,  ship:"6 批 + 2 人",   office:"1 批"},
  14:{per:14, ship:"4 批 + 2 人",   office:"1 批"},
  29:{per:29, ship:"2 批",          office:"1 批"},
  58:{per:58, ship:"1 批",          office:"1 批"},
};
const LVNAME = {3:"简单（原版）",4:"容易",6:"中等",9:"偏高",14:"较难",29:"困难",58:"硬核"};

function badge(text, cls){return `<span class="badge ${cls}">${esc(text)}</span>`;}

const LOG_MAX_LINES = 14;
function logLine(s){
  const el = $("log");
  el.classList.add("on");
  // 不显示滑动条，所以只留最近几行，让最新的内容一定看得见
  const lines = (el.textContent + s + "\n").split("\n");
  el.textContent = lines.slice(Math.max(0, lines.length - LOG_MAX_LINES)).join("\n");
}
function clearLog(){$("log").textContent="";}

async function api(path, opts){
  const r = await fetch(path, Object.assign({headers:{"Content-Type":"application/json"}}, opts||{}));
  let j = null;
  try{ j = await r.json(); }catch(e){ throw new Error("服务没有返回 JSON（HTTP "+r.status+"）"); }
  if(!r.ok || j.error) throw new Error(j.error || ("HTTP "+r.status));
  return j;
}

function renderLevels(){
  const box = $("levels");
  box.innerHTML = "";
  for(const lv of (S.state?.levels || [])){
    const b = BATCH[lv.level] || {per:"?", ship:"?", office:"?"};
    const el = document.createElement("button");
    el.className = "lv";
    el.type = "button";
    el.dataset.level = lv.level;
    el.dataset.vanilla = lv.vanilla ? "1" : "0";
    el.setAttribute("aria-pressed", String(S.picked === lv.level));
    el.disabled = S.busy;      // 换档中卡片也要置灰（轮询会重建卡片，所以在这里跟着 S.busy 走）
    el.innerHTML =
      `<span class="n">${esc(lv.name)}</span>` +
      (lv.vanilla ? `<span class="tag">原版</span>` : "") +
      `<span class="m">每批 ${esc(b.per)} 人</span>`;
    el.onclick = () => {
      if(S.busy) return;
      S.picked = lv.level;
      renderLevels();
      $("btn-apply").disabled = S.busy || S.state?.game_running;
    };
    box.appendChild(el);
  }
}

function renderSlots(){
  const tb = $("slots");
  tb.innerHTML = "";
  const slots = S.state?.slots || [];
  const any = slots.some(s => s.exists);
  if(!any){ tb.innerHTML = '<tr><td colspan="4" class="empty">三个槽位都是空的</td></tr>'; return; }
  for(const s of slots){
    const tr = document.createElement("tr");
    if(!s.exists){
      tr.innerHTML = `<td><span class="num">${esc(s.slot)}</span></td>` +
                     `<td colspan="3" class="empty">空</td>`;
      tb.appendChild(tr); continue;
    }
    const cnt = (s.error
      ? `<span class="badge bad">读不出</span>`
      : `<span class="num">${s.marked} / ${s.faces}</span>`);
    const btn = document.createElement("button");
    btn.textContent = "对齐到此档";
    btn.disabled = true;
    btn.title = "先在上面选好难度";
    btn.dataset.slot = s.slot;
    tr.innerHTML =
      `<td><span class="num">${esc(s.slot)}</span></td>` +
      `<td>${esc(s.zone || "?")}${s.error ? `<br><span class="badge bad">${esc(s.error)}</span>` : ""}</td>` +
      `<td>${cnt}</td><td></td>`;
    tr.lastElementChild.appendChild(btn);
    btn.onclick = () => doAlign(s.slot);
    tb.appendChild(tr);
  }
  refreshAlignButtons();
}

function refreshAlignButtons(){
  document.querySelectorAll('#slots button[data-slot]').forEach(b => {
    const cur = S.state?.dll_level;
    b.disabled = S.busy || S.picked == null;
    b.title = S.picked == null ? "先在上面选好难度"
            : `把 ${b.dataset.slot} 的已登记人数对齐到「${LVNAME[S.picked] || S.picked}」的可达值`;
  });
}

function render(){
  const st = S.state;
  if(!st) return;
  $("ver").textContent = st.game_found ? "已找到游戏" : "没找到游戏";

  $("s-game").innerHTML = st.game ? esc(st.game) : badge("没找到", "bad");
  $("s-run").innerHTML = st.game_running
    ? badge("游戏开着，请先退出再改", "bad") : badge("可以改动", "ok");

  const dd = st.dll || {};
  const kindMap = {vanilla:["未打补丁","dim"], patched:["已打补丁","ok"],
                   unknown:["状态不明","bad"], missing:["文件缺失","bad"]};
  const k = kindMap[dd.kind] || ["未知","bad"];
  $("s-dll").innerHTML = (dd.level != null
      ? badge(LVNAME[dd.level] || dd.level, "ok") : "") + " " + badge(k[0], k[1]);

  const ll = st.langs || {};
  if(!ll.exists){ $("s-lang").innerHTML = badge("找不到","bad"); }
  else if(ll.level != null){
    $("s-lang").innerHTML = badge(LVNAME[ll.level] || ll.level, "ok");
  } else {
    $("s-lang").innerHTML = badge("认不出","bad");
  }

  const c = st.consistent;
  $("s-cons").innerHTML = c === true ? badge("匹配","ok")
    : c === false ? badge("不匹配 —— 建议再应用一次该难度","bad")
    : badge("无法判定","dim");

  const bp = st.backup || {};
  $("s-backup").innerHTML = bp.dll
    ? badge("可以撤销","ok")
    : badge("还没备份（第一次换难度时会自动建立）","dim");

  const w = [];
  const lt = (st.assets || {}).langtool || {};
  if(!lt.ok) w.push("缺少改写书籍文字所需的组件，暂时无法换难度。");
  if(!st.game_found) w.push("没有自动找到游戏目录。可以设环境变量 OBRADINN_GAME 指向游戏根目录后重启本程序。");
  $("s-warn").innerHTML = w.length
    ? `<div class="warnbox">${w.map(esc).join("<br>")}</div>` : "";

  renderLevels();
  renderSlots();
  $("btn-apply").disabled = S.busy || !st.game_found || st.game_running || S.picked == null;
  $("btn-restore").disabled = S.busy || !st.game_found || st.game_running;
}

async function refresh(){
  try{
    const r = await api("/api/state");
    S.state = r.state;          // 服务器返回的是 {state, busy} 包装
    render();
    const inp = $("game-path");
    if(document.activeElement !== inp && !inp.value) inp.value = S.state.game || "";
  }catch(e){ logLine("[!] 读取状态失败：" + e.message); }
}

$("btn-browse").onclick = async () => {
  const msg = $("game-msg");
  msg.className = "";
  msg.textContent = "请在刚弹出的窗口里选择游戏目录…";
  try{
    const r = await api("/api/pick-folder", {method:"POST", body:"{}"});
    if(r.ok && r.path){
      $("game-path").value = r.path;
      msg.textContent = "已选中，点「用这个目录」生效。";
    } else if(r.cancelled){
      msg.textContent = "没有选择。";
    } else {
      msg.className = "bad";
      msg.textContent = r.error || "选择失败";
    }
  }catch(e){ msg.className = "bad"; msg.textContent = e.message; }
};

$("btn-usegame").onclick = async () => {
  const msg = $("game-msg");
  msg.className = "";
  msg.textContent = "正在检查…";
  try{
    const r = await api("/api/set-game", {
      method:"POST", body: JSON.stringify({path: $("game-path").value})});
    S.state = r.state; render();
    msg.className = "ok";
    msg.textContent = "已记住这个位置。";
  }catch(e){ msg.className = "bad"; msg.textContent = e.message; }
};

function setBusy(on, label){
  S.busy = !!on;
  document.body.classList.toggle("busy", S.busy);
  if(label) $("busybar").textContent = label;
  // pointer-events 已经挡住了鼠标，这里再把控件本身置灰：
  // 一是防键盘 Tab 过去按回车，二是让用户一眼看出现在不能操作。
  document.querySelectorAll("button,input,select,textarea").forEach(el => {
    if(S.busy){
      el.dataset.wasDisabled = el.disabled ? "1" : "0";
      el.disabled = true;
    } else if(el.dataset.wasDisabled !== undefined){
      el.disabled = el.dataset.wasDisabled === "1";
      delete el.dataset.wasDisabled;
    }
  });
  render();          // 让各处控件状态跟着 S.busy 走
}

async function guard(fn, label){
  if(S.busy) return;
  setBusy(true, label || "正在处理，请稍候…");
  try{ await fn(); }
  catch(e){ logLine("[!] " + e.message); }
  finally{ setBusy(false); await refresh(); }
}

async function doApply(){
  const lv = S.picked;
  if(lv == null) return;
  const b = BATCH[lv] || {};
  if(!confirm(`确认把难度换成「${LVNAME[lv] || lv}」（每批 ${b.per} 人）？\n\n` +
              `会覆盖 DLL 与 14 个语言包${$("opt-align").checked ? "，并自动对齐三个存档" : ""}。`))
    return;
  clearLog();
  await guard(async () => {
    logLine(`=> 应用到「${LVNAME[lv] || lv}」…`);
    const r = await api("/api/apply", {method:"POST",
      body: JSON.stringify({level: lv, align: $("opt-align").checked})});
    (r.log || []).forEach(l => logLine("   " + l));
    (r.align || []).forEach(a => logLine(
      `   存档 ${a.slot}：${a.ok ? "[OK]" : "[X]"} ${a.detail}${a.backup ? "（已备份）" : ""}`));
    logLine("=> 完成");
  }, `正在切换到「${LVNAME[lv] || lv}」，请稍候…`);
}

async function doAlign(slot){
  const lv = S.picked;
  if(lv == null) return;
  if(!confirm(`把存档 ${slot} 的「已登记人数」对齐到「${LVNAME[lv] || lv}」的可达值？\n\n` +
              `只改已登记标记，不动你填好的下落。会先备份该存档。`))
    return;
  await guard(async () => {
    logLine(`=> 对齐存档 ${slot} 到「${LVNAME[lv] || lv}」…`);
    const r = await api("/api/align", {method:"POST",
      body: JSON.stringify({slot: slot, level: lv})});
    logLine(`   ${r.ok ? "[OK]" : "[X]"} ${r.detail}`);
  }, `正在对齐存档 ${slot}，请稍候…`);
}

async function doRestore(){
  if(!confirm("确认撤销？\n\nDLL 与 14 个语言包都会还原到你第一次使用本工具之前的状态" +
              "（存档不动）。\n如果当时已经打过补丁，撤销后会回到那个补丁状态。"))
    return;
  clearLog();
  await guard(async () => {
    logLine("=> 还原到使用前…");
    const r = await api("/api/restore", {method:"POST", body:"{}"});
    (r.log || []).forEach(l => logLine("   " + l));
    logLine("=> 完成");
  }, "正在撤销，请稍候…");
}

$("btn-apply").onclick = doApply;
$("btn-restore").onclick = doRestore;
$("opt-align").onchange = () => {};

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
