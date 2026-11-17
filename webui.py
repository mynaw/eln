# -*- coding: utf-8 -*-
"""ELN 网页界面（单页 HTML）。由 webapp.py 引入。"""

PAGE = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ELN 实验记录</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e7ee;--text:#1b2430;--muted:#6b7787;
      --accent:#2f6fed;--ok:#1a7f37;--danger:#c0392b}
*{box-sizing:border-box}
body{margin:0;font:14px/1.55 "Microsoft YaHei","Segoe UI",system-ui,sans-serif;
     color:var(--text);background:var(--bg)}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);
       padding:10px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.3px}
.tabs{display:flex;gap:4px;background:#eef1f6;border-radius:8px;padding:3px}
.tab{padding:4px 12px;border-radius:6px;cursor:pointer;color:var(--muted);font-size:13px}
.tab.on{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
input[type=search],input[type=text],input[type=number],textarea,select{
     padding:6px 9px;border:1px solid var(--line);border-radius:8px;font-size:13px;
     outline:none;font-family:inherit;background:#fff;color:var(--text);width:100%}
input:focus,textarea:focus,select:focus{border-color:var(--accent)}
header input[type=search]{flex:1;min-width:140px;max-width:380px}
/* 顶栏 Ketcher 入口 + 绘制对象选择菜单 */
#kwrap{position:relative}
#kwrap button{border-color:#c9d6ee;color:var(--accent)}
#btnSave{border-color:#c9d6ee;color:var(--accent)}
#btnAcct{border-color:#c9d6ee;color:#374151;font-weight:600}
#ewrap{position:relative}
#emenu{display:none;position:absolute;top:calc(100% + 4px);left:0;background:#fff;
       border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.14);
       padding:5px;z-index:15;min-width:230px}
#emenu.on{display:block}
#emenu button{display:block;width:100%;text-align:left;border:0;background:none;
              padding:6px 10px;border-radius:6px;cursor:pointer;white-space:nowrap}
#emenu button:hover{background:#f2f6ff}
#toast{position:fixed;left:50%;bottom:34px;transform:translateX(-50%) translateY(8px);
       background:#1f2937;color:#fff;font-size:13px;padding:8px 18px;border-radius:20px;
       opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:99}
#toast.on{opacity:.95;transform:translateX(-50%) translateY(0)}
#kmenu{display:none;position:absolute;top:calc(100% + 4px);left:0;background:#fff;
       border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.14);
       padding:5px;z-index:15;min-width:112px}
#kmenu.on{display:block}
#kmenu button{display:block;width:100%;text-align:left;border:0;background:none;
       padding:7px 12px;border-radius:6px}
#kmenu button:hover{background:#f2f6ff}
main{display:flex;gap:12px;padding:12px;align-items:flex-start}
#list{width:320px;flex:none;background:var(--card);border:1px solid var(--line);
      border-radius:10px;overflow:hidden;max-height:calc(100vh - 90px);overflow-y:auto}
.item{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.item:hover{background:#f2f6ff}
.item.on{background:#e9f0ff;border-left:3px solid var(--accent)}
.item .t{font-weight:600;font-size:13px}
.item .m{color:var(--muted);font-size:12px;margin-top:2px}
#detail{flex:1;background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:16px;min-height:200px}
#detail h2{margin:0 0 4px;font-size:17px}
.badge{display:inline-block;font-size:12px;color:var(--muted);margin-bottom:10px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:center}
th{background:#eef3fb;font-weight:600}
.kv{display:grid;grid-template-columns:96px 1fr;gap:4px 10px;margin:8px 0}
.kv .k{color:var(--muted)}
.svgbox{height:210px;display:flex;align-items:center;justify-content:center;
        margin:12px 0;overflow:hidden}
.svgbox svg{max-width:100%;max-height:210px;width:auto;height:auto}
.sec{margin:16px 0 6px;font-weight:600;font-size:14px;border-left:3px solid var(--accent);
     padding-left:8px}
pre{white-space:pre-wrap;word-break:break-word;background:#fafbfd;border:1px solid var(--line);
    border-radius:8px;padding:10px;margin:6px 0;font-family:inherit;font-size:13px}
.sum{color:var(--ok);font-weight:600;margin:8px 0}
button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 12px;
       font-size:13px;cursor:pointer;font-family:inherit;color:var(--text)}
button:hover{background:#f2f6ff}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{background:#2560d8}
button.danger{color:var(--danger);border-color:#f0c8c3}
button.mini{padding:2px 8px;font-size:12px}
.empty{color:var(--muted);padding:24px;text-align:center}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
/* 编辑弹层 */
#mask{display:none;position:fixed;inset:0;background:rgba(16,22,32,.42);z-index:20;
      padding:24px;overflow:auto}
#mask.on{display:block}
#editor{max-width:880px;margin:0 auto;background:var(--card);border-radius:12px;
        padding:18px;box-shadow:0 12px 40px rgba(0,0,0,.18)}
#editor h3{margin:0 0 12px;font-size:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}
.grid .full{grid-column:1/-1}
label{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}
textarea{min-height:70px;resize:vertical}
.comp-table input,.comp-table select{padding:4px 6px;font-size:12px}
.comp-table td{padding:3px}
.foot{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.hint{font-size:12px;color:var(--muted);margin-top:6px}
.who{font-size:12px;color:var(--muted);margin-left:auto}
.who a{color:var(--accent);text-decoration:none;margin-left:8px}
/* 实验笔记块（操作步骤） */
.blk{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:6px 0;
     background:#fafbfd;white-space:pre-wrap;word-break:break-word;font-size:13px;
     position:relative;padding-right:56px}
.blk .bkind{display:inline-block;font-size:11px;color:#fff;background:#8a94a6;
     border-radius:4px;padding:1px 6px;margin-right:8px;vertical-align:1px;white-space:nowrap}
.blk.step .bkind{background:#2f6fed}
.blk.chem .bkind{background:#1a7f37}
.blk.calc .bkind{background:#a06a1b}
.blk table{margin:6px 0 0;font-size:12px}
.bops{position:absolute;top:7px;right:8px}
.bops button{margin-left:4px}
.dim{color:var(--muted)}
.blk textarea{width:100%;min-height:96px;white-space:pre-wrap}
/* Ketcher 画板弹层 */
#kmask{display:none;position:fixed;inset:0;background:rgba(16,22,32,.5);z-index:22;
       padding:16px}
#kmask.on{display:flex;flex-direction:column}
#kbar{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#kbar b{color:#fff;font-size:14px}
#kbar span{color:#c9d2e0;font-size:12px;margin-left:auto}
#kframe{flex:1;width:100%;border:0;border-radius:10px;background:#fff}
/* 网页笔记本（与桌面版对齐） */
#nmask{display:none;position:fixed;inset:0;background:rgba(16,22,32,.5);z-index:23;padding:18px}
#nmask.on{display:flex}
#nbook{flex:1;max-width:1020px;margin:0 auto;background:var(--card);border-radius:12px;
       display:flex;flex-direction:column;padding:14px;min-height:0;max-height:100%;
       box-shadow:0 12px 40px rgba(0,0,0,.2)}
#nbar{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#nbar b{font-size:15px}
#nbar .hint{margin-left:auto}
#nadd{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
#nbody{display:flex;gap:10px;flex:1;min-height:0}
#ncat{width:230px;flex:none;border:1px solid var(--line);border-radius:8px;overflow-y:auto;
      background:#fafbfd;padding:6px;font-size:12px}
.ncat-it{padding:5px 6px;border-radius:5px;cursor:pointer;overflow:hidden;
         text-overflow:ellipsis;white-space:nowrap}
.ncat-it:hover{background:#eef3fb}
#nblocks{flex:1;overflow-y:auto;min-width:0}
.nbcard{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:6px 0;
        background:#fff}
.nbhead{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.nbnum{color:var(--muted);font-size:12px}
.nops{margin-left:auto;display:flex;gap:4px}
.nbbody{white-space:pre-wrap;word-break:break-word;font-size:13px}
.nbbody table{margin:4px 0 0}
.nbcard .bkind{display:inline-block;font-size:11px;color:#fff;background:#8a94a6;
       border-radius:4px;padding:1px 6px;white-space:nowrap}
.nbcard .bkind.step{background:#2f6fed}
.nbcard .bkind.chem{background:#1a7f37}
.nbcard .bkind.calc{background:#a06a1b}
.nbform{background:#fafbfd;border-radius:8px;padding:10px}
.nbform label{margin:8px 0 2px}
.nbform textarea{width:100%;min-height:72px}
.nbform input[type=text]{width:100%}
.nbform .chk{font-size:13px;color:var(--text)}
.nbform .chk input{width:auto;margin-right:6px}
#umask{display:none;position:fixed;inset:0;background:rgba(16,22,32,.42);z-index:21;
      padding:24px;overflow:auto}
#umask.on{display:block}
#ued{max-width:560px;margin:0 auto;background:var(--card);border-radius:12px;padding:18px;
     box-shadow:0 12px 40px rgba(0,0,0,.18)}
#ued h3{margin:0 0 12px;font-size:16px}
.ulist{font-size:13px;margin-bottom:12px}
.ulist div{padding:5px 0;border-bottom:1px solid var(--line);display:flex;
           justify-content:space-between}
.urow button{border:1px solid var(--line);border-radius:6px;padding:1px 7px;
             margin-left:4px;cursor:pointer;font-size:12px;background:#fff}
.urow button:hover{background:#f2f6ff}
.uBadge{font-style:normal;font-size:11px;color:#6b7280;margin-left:6px}
@media (max-width:760px){
  main{flex-direction:column}
  #list{width:100%;max-height:34vh}
  .grid{grid-template-columns:1fr}
}
</style></head>
<body>
<header>
  <h1>ELN 实验记录</h1>
  <div class="tabs">
    <div class="tab on" data-kind="reaction">反应</div>
    <div class="tab" data-kind="sample">药剂</div>
  </div>
  <div id="kwrap">
    <button id="btnKetcher">Ketcher ▾</button>
    <div id="kmenu">
      <button onclick="startKetcher('reaction')">绘制反应</button>
      <button onclick="startKetcher('sample')">绘制药剂</button>
    </div>
  </div>
  <button id="btnRefresh" title="从库里重读列表和详情（F5 同效）">⟳ 刷新</button>
  <button id="btnSave" title="确认落库并给当前记录存一份保存快照">保存</button>
  <input id="q" type="search" placeholder="搜索标题 / 编号 / 结构 / 备注…">
  <button id="btnImport" title="导入 SDF / MOL，结构自动建成药剂">导入</button>
  <input type="file" id="impfile" accept=".sdf,.mol" style="display:none">
  <div id="ewrap">
    <button id="btnExport">导出 ▾</button>
    <div id="emenu">
      <button onclick="doExport('pdf')">当前记录 → PDF</button>
      <button onclick="doExport('docx')">当前记录 → DOCX</button>
      <button onclick="doExport('md')">当前记录 → Markdown 包（zip）</button>
      <button onclick="doExport('eln')">当前记录 → .eln 标准包</button>
      <button onclick="doExport('md','all')">整库 → Markdown 包（zip）</button>
      <button onclick="doExport('eln','all')">整库 → .eln 标准包</button>
      <button onclick="doExport('csv')">药剂表 → CSV</button>
      <button onclick="doExport('sdf')">药剂结构 → SDF</button>
    </div>
  </div>
  <button id="btnAcct" title="当前登录的账户">账号</button>
  <button onclick="window.open('/help','_blank')"
          title="打开用户手册（与桌面端 F1 帮助同一份内容）">帮助</button>
  <button id="btnLogout" title="确认后：退出登录 → 停止服务进程 → 关闭本页">退出</button>
  <button id="btnNew" class="primary">+ 新建</button>
  <span id="who" class="who" style="display:none">{{USER}}</span>
</header>
<main>
  <div id="list"><div class="empty">加载中…</div></div>
  <div id="detail"><div class="empty">从左侧选择一条记录</div></div>
</main>

<div id="mask"><div id="editor">
  <h3 id="edTitle">编辑</h3>
  <div id="edBody"></div>
  <div id="edComps"></div>
  <div class="foot">
    <button onclick="closeEditor()">取消</button>
    <button class="primary" onclick="saveRecord()">保存</button>
  </div>
</div></div>

<div id="umask"><div id="ued">
  <h3>账户管理</h3>
  <div class="hint">点子账号行里的按钮重置名称与密码 / 分配空间 / 删除；管理员（当前本地账号）不可改不可删。子账号密码只存不可逆哈希，丢了只能重置。</div>
  <div id="ulist" class="ulist"></div>
  <div class="grid">
    <div><label>子账号名</label><input id="uname" type="text"></div>
    <div><label>密码（至少 6 位）</label><input id="upwd" type="password"></div>
    <div><label>可用空间（MB，0=不限）</label><input id="uquota" type="number" min="0" value="0"></div>
  </div>
  <div class="foot">
    <button onclick="closeUsers()">关闭</button>
    <button class="primary" onclick="createUser()">创建子账号</button>
  </div>
</div></div>

<div id="kmask">
  <div id="kbar"><b>Ketcher 结构画板</b>
    <span>画完点画板里的「保存回 ELN」，看到「已保存」后点下面关闭；关闭后本页会刷新结构图</span>
    <button onclick="closeKetcher()">关闭画板</button></div>
  <iframe id="kframe" src="about:blank" title="Ketcher"></iframe>
</div>

<div id="nmask"><div id="nbook">
  <div id="nbar"><b>实验笔记 · <span id="nbTitle"></span></b>
    <span class="hint">Ctrl+Enter 保存当前块 · Esc 关闭</span>
    <button onclick="closeNotebook()">关闭</button></div>
  <div id="nadd">
    <button onclick="nbAdd('text')">＋ 文本</button>
    <button onclick="nbAdd('step')">＋ 步骤</button>
    <button onclick="nbAdd('chem')">＋ 化学</button>
    <button onclick="nbAdd('table')">＋ 表格</button>
    <button onclick="nbAdd('calc')">＋ 计算</button>
  </div>
  <div id="nbody">
    <div id="ncat"></div>
    <div id="nblocks"></div>
  </div>
</div></div>

<div id="toast"></div>

<script>
const S={kind:'reaction',id:null,q:'',form:null,comps:[],attExp:false,authMode:false};
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;',
  '>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tok=new URLSearchParams(location.search).get('t')||'';
const qs=o=>Object.entries(o).filter(([,v])=>v!==''&&v!=null)
  .map(([k,v])=>k+'='+encodeURIComponent(v)).join('&');
const api=(p,o)=>fetch(p+'?'+qs(Object.assign({},o||{},{t:tok})))
  .then(r=>r.ok?r.json():r.json().then(e=>Promise.reject(e.error||r.status)));
/* 写接口助手：apiPost('/api/xxx',{...}) / apiDel('/api/yyy',{id:...})，
   出错直接抛 e.message（服务端 _err 的 msg），弹窗一行搞定 */
const apiPost=(p,o)=>fetch(p+'?'+qs({t:tok}),{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(o||{})})
  .then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d;});
const apiDel=(p,o)=>fetch(p+'?'+qs(Object.assign({},o||{},{t:tok})),{method:'DELETE'})
  .then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d;});

document.querySelectorAll('.tab').forEach(el=>el.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  el.classList.add('on');S.kind=el.dataset.kind;S.id=null;
  document.getElementById('detail').innerHTML='<div class="empty">从左侧选择一条记录</div>';
  loadList();
});
document.getElementById('q').oninput=e=>{clearTimeout(window._t);
  window._t=setTimeout(()=>{S.q=e.target.value.trim();loadList();},280);};
document.getElementById('btnNew').onclick=()=>openEditor(null);

/* 定稿 / 解锁（与桌面一致）：定稿免密并存定稿快照；解锁输当前登录账户密码 */
async function toggleLock(id, locked){
  let pwd='';
  if(locked){
    if(S.authMode){
      pwd=prompt('输入登录密码解锁：');
      if(pwd===null)return;
      if(!pwd){alert('请输入密码。');return;}
    }
  }else{
    if(!confirm('定稿后将变成只读，桌面端与网页端都不能再改。'+String.fromCharCode(10)+
                '需要修改时用登录密码解锁。'+String.fromCharCode(10)+String.fromCharCode(10)+
                '确定定稿？'))return;
  }
  try{
    const d=await apiPost('/api/lock',{kind:S.kind,id:id,password:pwd});
    openRec(id);
    flashTop(d.locked?'已定稿，生成定稿快照':'已解锁');
  }catch(e){alert('操作失败：'+(e.message||e));}
}

/* 附件清单开关：打开后导出 PDF/DOCX 时文末打印附件路径与文件名 */
function toggleAttExp(){
  S.attExp=!S.attExp;
  if(S.id)openRec(S.id);          // 重绘详情页，刷新开关样式与导出链接
}

/* 上传附件（可多选）：与桌面「+ 添加」一致，文件复制进服务器 attachments/ */
function pickAttach(){
  const inp=document.createElement('input');
  inp.type='file';inp.multiple=true;
  inp.onchange=async()=>{
    let ok=0;
    for(const f of inp.files){
      const b64=await new Promise((res,rej)=>{
        const rd=new FileReader();
        rd.onload=()=>res(rd.result.split(',')[1]);
        rd.onerror=()=>rej(rd.error);
        rd.readAsDataURL(f);
      });
      try{
        await apiPost('/api/attach_add',
          {owner_type:S.kind,owner_id:S.id,name:f.name,b64:b64});
        ok++;
      }catch(e){alert('上传「'+f.name+'」失败：'+(e.message||e));break;}
    }
    if(ok)openRec(S.id);
  };
  inp.click();
}

/* 移除附件：与桌面「移除」一致，只删登记，不动服务器上的文件 */
async function delAttach(aid){
  if(!confirm('移除这个附件的登记？（服务器上的文件不会被删除）'))return;
  try{
    await apiDel('/api/attach_remove',{aid:aid});
    openRec(S.id);
  }catch(e){alert('移除失败：'+(e.message||e));}
}

async function loadList(){
  const box=document.getElementById('list');box.innerHTML='<div class="empty">加载中…</div>';
  try{
    const d=await api('/api/list',{kind:S.kind,q:S.q,limit:200});
    if(!d.items.length){box.innerHTML='<div class="empty">没有记录，点右上角「+ 新建」</div>';return;}
    box.innerHTML=d.items.map(it=>`<div class="item" data-id="${it.id}">
      <div class="t">${esc(it.title)}</div>
      <div class="m">#${it.id}${it.meta?' · '+esc(it.meta):''}</div></div>`).join('');
    box.querySelectorAll('.item').forEach(el=>el.onclick=()=>openRec(+el.dataset.id));
    if(S.id)box.querySelectorAll('.item').forEach(x=>
      x.classList.toggle('on',+x.dataset.id===S.id));
  }catch(e){box.innerHTML='<div class="empty">加载失败：'+esc(e)+'</div>';}
}

async function openRec(id){
  S.id=id;
  document.querySelectorAll('.item').forEach(x=>
    x.classList.toggle('on',+x.dataset.id===id));
  const box=document.getElementById('detail');box.innerHTML='<div class="empty">加载中…</div>';
  try{
    const r=await api('/api/record',{kind:S.kind,id});
    let h=`<h2>${esc(r.title)}</h2><div class="badge">${esc(r.kind)}记录 #${r.id}
      ${r.locked?' · 🔒 已定稿':''}</div>`;
    h+=`<div class="toolbar">
      <button class="primary" onclick="openEditor(${r.id})">编辑</button>
      <button onclick="openKetcher(S.kind,${r.id})">绘制（Ketcher）</button>
      ${S.kind==='reaction'?`<button onclick="toggleLock(${r.id},${r.locked?'true':'false'})">${r.locked?'已定稿 · 解锁':'定稿'}</button>`:''}
      <button class="danger" onclick="delRecord(${r.id})">删除</button>
      <a href="/api/export?${qs(Object.assign({kind:S.kind,id:r.id,fmt:'pdf',t:tok},
        S.attExp?{att:1}:{}))}">
        <button>下载 PDF</button></a></div>`;
    if(r.fields.length){
      h+='<div class="kv">'+r.fields.map(([k,v])=>
        `<div class="k">${esc(k)}</div><div>${esc(v)}</div>`).join('')+'</div>';
    }
    if(r.image_svg){h+='<div class="svgbox">'+r.image_svg+'</div>';}
    if(r.comps){
      h+='<div class="sec">组成</div><table><tr>'+r.comps.head.map(c=>
        `<th>${esc(c)}</th>`).join('')+'</tr>';
      h+=r.comps.rows.map(row=>'<tr>'+row.map(c=>`<td>${esc(c)}</td>`).join('')+'</tr>').join('');
      h+='</table>';
    }
    if(r.summary){h+=`<div class="sum">${esc(r.summary)}</div>`;}
    if(r.procedure){h+='<div class="sec">操作</div><pre>'+esc(r.procedure)+'</pre>';}
    if(r.blocks){
      h+='<div class="sec" style="display:flex;align-items:baseline;gap:14px">'+
         '<span>实验笔记</span>'+
         (!r.locked?`<span style="font-weight:400;font-size:12px">
           <a href="javascript:void(0)" onclick="openNotebook()">打开笔记本</a>
           <a href="javascript:void(0)" onclick="newNote()" style="margin-left:10px;color:#1a7f37">＋ 记一笔</a></span>`:'')+
         '</div>';
      h+=r.blocks.map(b=>{
        if(b.kind==='table'){
          return `<div class="blk"><span class="bkind">表格</span><table><tr>`+
            b.cols.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr>'+
            b.rows.map(row=>'<tr>'+row.map(c=>`<td>${esc(c)}</td>`).join('')+'</tr>').join('')+
            '</table></div>';
        }
        const name={text:'文字',step:'步骤',chem:'结构',calc:'计算'}[b.kind]||'笔记';
        const body=b.kind==='text'
          ?(esc(b.text)||'<span class="dim">（空笔记，点「打开笔记本」补写）</span>')
          :esc(b.text);
        return `<div class="blk ${esc(b.kind)}"><span class="bkind">${name}</span>${body}</div>`;
      }).join('');
    }
    if(r.note){h+='<div class="sec">备注</div><pre>'+esc(r.note)+'</pre>';}
    if(true){
      const on=S.attExp;
      h+='<div class="sec" style="display:flex;align-items:baseline;justify-content:space-between">'+
         '<span>附件&nbsp;&nbsp;'+
         (r.locked?'<span style="font-weight:400;color:#b8c0cc">+ 添加</span>'
                  :'<a href="javascript:void(0)" onclick="pickAttach()" style="font-weight:400">+ 添加</a>')+
         '</span>'+
         (r.attachments.length?
           `<a href="javascript:void(0)" onclick="toggleAttExp()" style="${on?'color:#1a7f37;font-weight:600':''}" `+
           `title="打开后导出 PDF/DOCX 时，文末打印附件的路径与文件名（不含内容）">${on?'✓ 导出':'导出'}</a>`:'')+
         '</div>';
      if(r.attachments.length){
        h+=r.attachments.map(a=>
          `<div style="display:flex;align-items:center;gap:10px;border:1px solid var(--line);`+
          `background:#fafbfc;border-radius:6px;padding:5px 10px;margin:4px 0">`+
          `<span style="font-size:11px;color:#5b6b7f;width:44px;flex-shrink:0">${esc(a.kind||'文件')}</span>`+
          `<a href="/api/file?${qs({aid:a.id,t:tok})}" target="_blank" style="flex:1;min-width:0;`+
          `overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.title||a.path)}</a>`+
          (r.locked?'':`<a href="javascript:void(0)" style="color:#8a94a2;font-size:12px" `+
           `onclick="delAttach(${a.id})">移除</a>`)+
          `</div>`).join('');
      }else{
        h+='<div style="color:#8a94a2;font-size:12px;margin:2px 0">（还没有附件，点「+ 添加」上传）</div>';
      }
    }
    box.innerHTML=h;
  }catch(e){box.innerHTML='<div class="empty">加载失败：'+esc(e)+'</div>';}
}

async function openEditor(id){
  try{
    const f=await api('/api/form',{kind:S.kind,id:id||0});
    S.form=f;S.id=id||null;S.comps=f.comps||[];
    document.getElementById('edTitle').textContent=
      (id?'编辑':'新建')+(S.kind==='reaction'?'反应记录':'药剂记录');
    document.getElementById('edBody').innerHTML='<div class="grid">'+
      f.fields.map(fd=>{
        const val=esc(fd.value==null?'':fd.value);
        let inner;
        if(fd.multiline){
          inner=`<textarea id="f_${fd.key}">${val}</textarea>`;
        }else if(fd.choices){
          // 与桌面端一致：点选下拉，也允许输入自定义值（datalist 组合框）
          const dl='dl_'+fd.key;
          inner=`<input type="${fd.type||'text'}" id="f_${fd.key}" list="${dl}" value="${val}">`+
            `<datalist id="${dl}">`+fd.choices.map(c=>
              `<option value="${esc(c)}">`).join('')+`</datalist>`;
        }else{
          inner=`<input type="${fd.type||'text'}" id="f_${fd.key}" value="${val}">`;
        }
        const cls=(fd.multiline||fd.full)?'full':'';
        return `<div class="${cls}"><label>${esc(fd.label)}</label>${inner}</div>`;
      }).join('')+'</div>';
    renderComps();
    document.getElementById('mask').classList.add('on');
  }catch(e){alert('打开编辑器失败：'+e);}
}

function renderComps(){
  const box=document.getElementById('edComps');
  if(S.kind!=='reaction'){box.innerHTML='';return;}
  const opts=s=>`<option value="">（不关联）</option>`+S.form.samples.map(x=>
    `<option value="${x.id}" ${x.id===s?'selected':''}>${esc(x.name||('#'+x.id))}</option>`).join('');
  box.innerHTML=`<div class="sec">组成</div>
    <table class="comp-table"><tr><th>角色</th><th>物质</th><th>当量</th>
      <th>用量</th><th>单位</th><th>实测/g</th><th></th></tr>`+
    S.comps.map((c,i)=>`<tr data-i="${i}">
      <td><input type="text" data-f="role" value="${esc(c.role||'')}"></td>
      <td><select data-f="sample_id">${opts(c.sample_id)}</select></td>
      <td><input type="number" step="0.01" data-f="equivalents" value="${c.equivalents==null?'':c.equivalents}"></td>
      <td><input type="number" step="0.01" data-f="amount" value="${c.amount==null?'':c.amount}"></td>
      <td><input type="text" data-f="unit" value="${esc(c.unit||'')}"></td>
      <td><input type="number" step="0.001" data-f="actual" value="${c.actual==null?'':c.actual}"></td>
      <td><button class="mini" onclick="delComp(${i})">×</button></td></tr>`).join('')+
    `</table><button class="mini" onclick="addComp()">+ 添加一行</button>
     <div class="hint">物质选药剂后，桌面端打开时能直接看到对应结构。</div>`;
}

function readComps(){
  const rows=[...document.querySelectorAll('#edComps tr[data-i]')];
  return rows.map(tr=>{
    const o={role:'',sample_id:null,equivalents:null,amount:null,unit:'',actual:null};
    tr.querySelectorAll('[data-f]').forEach(el=>{
      const k=el.dataset.f;
      if(k==='role'||k==='unit')o[k]=el.value.trim();
      else if(k==='sample_id')o[k]=el.value?+el.value:null;
      else o[k]=el.value===''?null:+el.value;
    });
    return o;
  }).filter(c=>c.role||c.sample_id||c.amount);
}
function addComp(){S.comps=readComps();S.comps.push({role:'反应物'});renderComps();}
function delComp(i){S.comps=readComps();S.comps.splice(i,1);renderComps();}

async function saveRecord(){
  const fields={};
  S.form.fields.forEach(fd=>{
    const el=document.getElementById('f_'+fd.key);
    if(el)fields[fd.key]=el.value.trim();
  });
  const body={kind:S.kind,id:S.id||0,fields,comps:S.kind==='reaction'?readComps():[]};
  try{
    const r=await fetch('/api/save?'+qs({t:tok}),{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||r.status);
    closeEditor();S.id=d.id;await loadList();await openRec(d.id);
  }catch(e){alert('保存失败：'+e.message);}
}

async function delRecord(id){
  if(!confirm('确定删除这条记录？删除后不可恢复。'))return;
  try{
    const r=await fetch('/api/delete?'+qs({kind:S.kind,id,t:tok}),{method:'DELETE'});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||r.status);
    S.id=null;
    document.getElementById('detail').innerHTML='<div class="empty">已删除</div>';
    loadList();
  }catch(e){alert('删除失败：'+e.message);}
}
function closeEditor(){document.getElementById('mask').classList.remove('on');}
document.getElementById('mask').onclick=e=>{if(e.target.id==='mask')closeEditor();};
document.onkeydown=e=>{
  if(e.key==='Escape'){closeEditor();closeUsers();closeKetcher();closeNotebook();}
  if(e.key==='F5'){e.preventDefault();doRefresh();}   // 与桌面端一致：F5 刷新
  if(e.ctrlKey&&e.key==='Enter'&&
     document.getElementById('nmask').classList.contains('on')&&NB.edit>=0){
    e.preventDefault();nbSave(NB.edit);
  }
};

/* ---------- 网页笔记本（与桌面版对齐：五种块 · 增删改 · 上下移 · 复制 · 块目录） ---------- */
const NBK={text:'文本',step:'步骤',chem:'化学',table:'表格',calc:'计算'};
const NB={blocks:[],locked:false,kind:null,id:null,edit:-1,token:0};

async function openNotebook(){
  if(!S.id)return;
  NB.kind=S.kind;NB.id=S.id;NB.edit=-1;NB.token++;
  document.getElementById('nbTitle').textContent=(S.kind==='reaction'?'反应':'药剂')+' #'+S.id;
  await nbReload();
  document.getElementById('nmask').classList.add('on');
}
/* 「＋ 记一笔」：直接追加一个文本块并就地进入编辑（与桌面端行为一致） */
async function newNote(){
  if(!S.id)return;
  try{
    const d=await apiPost('/api/block/add',
      {owner_type:S.kind,owner_id:S.id,kind:'text',content:{md:''}});
    NB.kind=S.kind;NB.id=S.id;NB.edit=-1;
    document.getElementById('nbTitle').textContent=(S.kind==='reaction'?'反应':'药剂')+' #'+S.id;
    document.getElementById('nmask').classList.add('on');
    await nbReload();
    nbEdit(NB.blocks.findIndex(b=>b.id===d.id));
  }catch(e){alert('记一笔失败：'+e.message);}
}
async function nbReload(){
  const t=++NB.token;
  const d=await api('/api/blocks',{kind:NB.kind,id:NB.id});
  if(t!==NB.token)return;                 // 期间换过记录就丢弃
  NB.blocks=d.blocks||[];NB.locked=d.locked;
  nbRender();
}
function closeNotebook(){
  const m=document.getElementById('nmask');
  if(!m.classList.contains('on'))return;
  m.classList.remove('on');NB.edit=-1;
  if(S.id)openRec(S.id);                  // 详情页同步刷新
}
function nbShort(b){
  const t=b.kind==='table'?'表格':(b.text||'');
  return t.replace(/\\s+/g,' ').slice(0,24);
}
function nbRender(){
  const cat=[],rows=[];
  NB.blocks.forEach((b,i)=>{
    cat.push(`<div class="ncat-it" onclick="nbJump(${i})">${String(i+1).padStart(2,'0')}
      ${NBK[b.kind]||b.kind} · ${esc(nbShort(b))}</div>`);
    rows.push(nbCard(b,i));
  });
  document.getElementById('ncat').innerHTML=
    cat.join('')||'<div class="empty" style="padding:12px">还没有笔记</div>';
  document.getElementById('nblocks').innerHTML=
    rows.join('')||'<div class="empty">还没有笔记，点上方「＋ 文本」开始</div>';
}
function nbJump(i){
  const el=document.getElementById('nb_'+i);
  if(!el)return;
  el.scrollIntoView({block:'center'});
  el.style.outline='2px solid var(--accent)';
  setTimeout(()=>el.style.outline='',800);
}
function nbCard(b,i){
  const num=String(i+1).padStart(2,'0');
  const ops=NB.locked?'<span class="nops dim">🔒 已定稿</span>':`<span class="nops">
    <button class="mini" onclick="nbEdit(${i})">编辑</button>
    <button class="mini" onclick="nbMove(${i},-1)">▲</button>
    <button class="mini" onclick="nbMove(${i},1)">▼</button>
    <button class="mini" onclick="nbDup(${i})">复制</button>
    <button class="mini" onclick="nbDel(${i})">删除</button></span>`;
  let body;
  if(NB.edit===i){body=nbForm(b,i);}
  else if(b.kind==='table'){
    body='<table><tr>'+b.cols.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr>'+
      b.rows.map(row=>'<tr>'+row.map(c=>`<td>${esc(c)}</td>`).join('')+'</tr>').join('')+'</table>';
  }else{
    body=esc(b.text)||'<span class="dim">（空）</span>';
  }
  return `<div class="nbcard" id="nb_${i}"><div class="nbhead">
    <span class="nbnum">${num}</span><span class="bkind ${esc(b.kind)}">${NBK[b.kind]||''}</span>${ops}</div>
    <div class="nbbody">${body}</div></div>`;
}
function nbForm(b,i){
  const c=b.content||{};
  const H=s=>esc(s==null?'':s);
  let f='';
  if(b.kind==='text'){
    f=`<textarea id="nbf_md" style="min-height:110px">${H(c.md)}</textarea>`;
  }else if(b.kind==='step'){
    f=`<div class="grid"><div><label>标题</label>
        <input type="text" id="nbf_title" value="${H(c.title)}"></div>
       <div><label>用时</label><input type="text" id="nbf_time" value="${H(c.time)}"></div></div>
       <label class="chk" style="margin-top:8px"><input type="checkbox" id="nbf_done" ${c.done?'checked':''}>已完成</label>
       <div><label>内容</label><textarea id="nbf_body">${H(c.body)}</textarea></div>`;
  }else if(b.kind==='chem'){
    f=`<div><label>SMILES</label><textarea id="nbf_smiles">${H(c.smiles)}</textarea></div>
       <div><label>说明</label><input type="text" id="nbf_caption" value="${H(c.caption)}"></div>`;
  }else if(b.kind==='table'){
    f=`<div><label>列名（用 | 分隔）</label>
        <input type="text" id="nbf_cols" value="${H((c.cols||[]).join(' | '))}"></div>
       <div><label>每行一条，单元格用 | 分隔</label>
        <textarea id="nbf_rows" style="min-height:120px">${H((c.rows||[]).map(r=>r.join(' | ')).join('\\n'))}</textarea></div>`;
  }else if(b.kind==='calc'){
    f=`<div><label>表达式</label><textarea id="nbf_expr">${H(c.expr)}</textarea></div>
       <div class="grid"><div><label>结果</label>
        <input type="text" id="nbf_result" value="${H(c.result)}"></div>
       <div><label>备注</label><input type="text" id="nbf_note" value="${H(c.note)}"></div></div>`;
  }
  return `<div class="nbform">${f}
    <div style="display:flex;gap:6px;justify-content:flex-end;margin-top:8px">
      <button class="mini" onclick="nbCancel()">取消</button>
      <button class="mini primary" onclick="nbSave(${i})">保存 (Ctrl+Enter)</button></div></div>`;
}
function nbContent(b){
  const v=id=>{const el=document.getElementById('nbf_'+id);
    return el?(el.type==='checkbox'?el.checked:el.value):'';};
  if(b.kind==='text')return {md:v('md')};
  if(b.kind==='step')return {title:v('title'),time:v('time'),done:v('done'),body:v('body')};
  if(b.kind==='chem')return {smiles:v('smiles'),caption:v('caption')};
  if(b.kind==='table')return {cols:v('cols').split('|').map(x=>x.trim()).filter(x=>x),
    rows:v('rows').split('\\n').map(line=>line.split('|').map(x=>x.trim()))
      .filter(r=>r.some(x=>x))};
  if(b.kind==='calc')return {expr:v('expr'),result:v('result'),note:v('note')};
  return {};
}
function nbEdit(i){NB.edit=i;nbRender();const ta=document.getElementById('nbf_md')||
  document.querySelector('#nb_'+i+' textarea');if(ta)ta.focus();}
function nbCancel(){NB.edit=-1;nbRender();}
async function nbSave(i){
  const b=NB.blocks[i];if(!b)return;
  try{
    await apiPost('/api/block/save',{id:b.id,kind:b.kind,content:nbContent(b)});
    NB.edit=-1;await nbReload();
  }catch(e){alert('保存失败：'+e.message);}
}
async function nbAdd(kind){
  try{
    const d=await apiPost('/api/block/add',
      {owner_type:NB.kind,owner_id:NB.id,kind:kind,content:{}});
    await nbReload();
    nbEdit(NB.blocks.findIndex(x=>x.id===d.id));
  }catch(e){alert('添加失败：'+e.message);}
}
async function nbMove(i,delta){
  const b=NB.blocks[i];if(!b)return;
  try{
    await apiPost('/api/block/move',{id:b.id,delta:delta});
    NB.edit=-1;await nbReload();
  }catch(e){alert('移动失败：'+e.message);}
}
async function nbDup(i){
  const b=NB.blocks[i];if(!b)return;
  try{
    const d=await apiPost('/api/block/dup',{id:b.id});
    await nbReload();
    nbEdit(NB.blocks.findIndex(x=>x.id===d.id));
  }catch(e){alert('复制失败：'+e.message);}
}
async function nbDel(i){
  const b=NB.blocks[i];if(!b)return;
  if(!confirm('删除第 '+(i+1)+' 块（'+(NBK[b.kind]||b.kind)+'）？'))return;
  try{
    await apiDel('/api/block/delete',{id:b.id});
    NB.edit=-1;await nbReload();
  }catch(e){alert('删除失败：'+e.message);}
}

/* ---------- 顶栏 刷新 / 保存（与桌面端状态栏同名按钮一致） ---------- */
let flashTimer=null;
function flashTop(text){
  const t=document.getElementById('toast');
  t.textContent=text+'  '+new Date().toTimeString().slice(0,5);
  t.classList.add('on');
  clearTimeout(flashTimer);
  flashTimer=setTimeout(()=>t.classList.remove('on'),2600);
}
async function doRefresh(){
  await loadList();
  if(S.id)await openRec(S.id);   // 未提交的输入框内容会被库里的值覆盖
  flashTop('已刷新');
}
async function doSave(){
  try{
    if(S.id){
      const d=await apiPost('/api/snapshot',{kind:S.kind,id:S.id});
      await loadList();
      await openRec(S.id);
      flashTop('已保存'+(d&&d.time?' '+d.time:''));
    }else{
      await loadList();          // 与桌面端一致：没选记录就只刷列表
      flashTop('已保存');
    }
  }catch(e){alert('保存失败：'+e.message);}
}
document.getElementById('btnRefresh').onclick=doRefresh;
document.getElementById('btnSave').onclick=doSave;

/* ---------- 顶栏 Ketcher 画板 ---------- */
/* S.kdraw 记录这次画的是哪种记录、哪一条（id=0 表示画完自动建一条新记录） */
document.getElementById('btnKetcher').onclick=e=>{
  e.stopPropagation();
  document.getElementById('kmenu').classList.toggle('on');
};
document.addEventListener('click',e=>{
  if(!e.target.closest || !e.target.closest('#kwrap'))
    document.getElementById('kmenu').classList.remove('on');
});
function startKetcher(kind){
  document.getElementById('kmenu').classList.remove('on');
  const id=(S.kind===kind&&S.id)?S.id:0;
  openKetcher(kind,id);
}
function openKetcher(kind,id){
  S.kdraw={kind:kind,id:id};
  const f=document.getElementById('kframe');
  f.src='/ketcher/?'+qs({kind:kind,id:id,t:tok});
  document.getElementById('kmask').classList.add('on');
}
function closeKetcher(){
  const m=document.getElementById('kmask');
  if(!m.classList.contains('on'))return;
  m.classList.remove('on');
  const f=document.getElementById('kframe');
  f.src='about:blank';
  const kd=S.kdraw||{};
  loadList();                       // 可能新建了「网页绘制」记录，列表刷新
  if(kd.id&&kd.id===S.id)openRec(S.id);   // 画的是当前记录，刷新结构图
}

/* ---------- 账户：顶栏账号按钮 / 管理员建号 ---------- */
fetch('/api/me?'+qs({t:tok})).then(r=>r.json()).then(m=>{
  const b=document.getElementById('btnAcct');
  S.authMode=!!m.auth;
  if(m.user)b.textContent='账号：'+m.user;
  if(m.role==='admin'){
    b.onclick=openUsers;                 // 管理员点「账号」直接进账户管理
  }else{
    b.onclick=()=>alert('当前账户：'+m.user+String.fromCharCode(10)+'角色：普通用户');
  }
}).catch(()=>{});

document.getElementById('btnLogout').onclick=()=>{
  if(confirm('确认退出？退出后将：退出登录（清会话）→ 停止网页服务进程 →'+String.fromCharCode(10)+
             '尝试自动关闭本页。未保存的输入会丢失。'))
    location.href='/logout?stop=1';
};

/* ---------- 导入 SDF / MOL（与桌面「导入：SDF / MOL…」一致） ---------- */
document.getElementById('btnImport').onclick=()=>{
  document.getElementById('impfile').click();
};
document.getElementById('impfile').onchange=e=>{
  const f=e.target.files[0];
  e.target.value='';                     // 允许重复选同一个文件
  if(!f)return;
  const rd=new FileReader();
  rd.onload=async()=>{
    try{
      const b64=rd.result.split(',',2)[1];
      const d=await apiPost('/api/import',{name:f.name,b64:b64});
      flashTop('已导入 '+d.count+' 条药剂');
      await loadList();
    }catch(err){alert('导入失败：'+err.message);}
  };
  rd.readAsDataURL(f);
};

/* ---------- 导出（与桌面「导出…」子菜单一致） ---------- */
document.getElementById('btnExport').onclick=e=>{
  e.stopPropagation();
  document.getElementById('emenu').classList.toggle('on');
};
document.addEventListener('click',e=>{
  if(!e.target.closest || !e.target.closest('#ewrap'))
    document.getElementById('emenu').classList.remove('on');
});
function doExport(fmt,scope){
  document.getElementById('emenu').classList.remove('on');
  scope=scope||'record';
  if(scope==='record'&&!S.id){alert('先在左侧列表选中一条记录，再导出当前记录。');return;}
  const o={kind:S.kind,id:S.id||0,fmt:fmt,scope:scope,t:tok};
  if(S.attExp&&(fmt==='pdf'||fmt==='docx')&&scope==='record')o.att=1;
  location.href='/api/export?'+qs(o);
}

async function openUsers(){
  try{
    const d=await api('/api/users');
    document.getElementById('ulist').innerHTML=d.users.map(u=>{
      const badge=u.root?'管理员（当前本地账号）':(u.role==='admin'?'管理员':'子账号');
      const space=u.root?'不限额':`${u.used||0} / ${u.quota||0} MB`;
      const ops=u.root?'':`<button data-act="reset">重置</button>`+
        `<button data-act="quota">配额</button><button data-act="del">删</button>`;
      return `<div class="urow" data-name="${esc(u.name)}" data-root="${u.root?1:0}">`+
        `<span>${esc(u.name)}<i class="uBadge">${badge}</i>${ops}</span>`+
        `<span class="dim">${space} · ${esc(u.created||'')}</span></div>`;
    }).join('')||'<div>（暂无）</div>';
    document.getElementById('umask').classList.add('on');
  }catch(e){alert('读取账户失败：'+e);}
}
function closeUsers(){document.getElementById('umask').classList.remove('on');}
document.getElementById('umask').onclick=e=>{
  if(e.target.id==='umask')closeUsers();
};

/* 子账号行内操作：重置 / 配额 / 删除（管理员账户不可操作） */
document.getElementById('ulist').addEventListener('click',async e=>{
  const row=e.target.closest('.urow');
  if(!row||row.dataset.root==='1')return;
  const name=row.dataset.name;
  const act=e.target.dataset.act;
  if(act==='reset'){
    const nn=prompt('新的账号名（不变就直接确定）：',name);
    if(nn===null)return;
    const pw=prompt('新密码（至少 6 位）：');
    if(!pw)return;
    try{await apiPost('/api/user/reset',{name:name,new_name:nn.trim(),password:pw});
        flashTop('已重置 '+name);await openUsers();}
    catch(err){alert('重置失败：'+err.message);}
  }else if(act==='quota'){
    const q=prompt('可用硬盘空间（MB，0 = 不限制）：','0');
    if(q===null)return;
    try{const d=await apiPost('/api/user/quota',{name:name,quota_mb:+q||0});
        flashTop('配额已保存：'+d.used+' / '+d.quota+' MB');await openUsers();}
    catch(err){alert('设置失败：'+err.message);}
  }else if(act==='del'){
    if(!confirm('删除子账号「'+name+'」？其数据目录会保留。'))return;
    try{await apiPost('/api/user/delete',{name:name});flashTop('已删除 '+name);
        await openUsers();}
    catch(err){alert('删除失败：'+err.message);}
  }
});

async function createUser(){
  const name=document.getElementById('uname').value.trim();
  const password=document.getElementById('upwd').value;
  const quota=+document.getElementById('uquota').value||0;
  if(!name||!password){alert('账户名和密码都要填');return;}
  try{
    await apiPost('/api/user/create',{name,password,quota_mb:quota});
    document.getElementById('uname').value='';
    document.getElementById('upwd').value='';
    document.getElementById('uquota').value='0';
    await openUsers();
  }catch(e){alert('创建失败：'+e.message);}
}

loadList();
</script>
</body></html>
"""

# ------------------------------------------------------------------ 登录页
LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录 · ELN</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
     background:#f2f5fa;font:14px/1.6 "Microsoft YaHei","Segoe UI",system-ui,sans-serif;color:#1b2430}
.card{width:340px;max-width:92vw;background:#fff;border:1px solid #e3e7ee;border-radius:14px;
      padding:26px 24px;box-shadow:0 10px 30px rgba(20,30,50,.08)}
h1{font-size:17px;margin:0 0 4px}
p.sub{margin:0 0 18px;color:#6b7787;font-size:12px}
label{display:block;font-size:12px;color:#6b7787;margin:10px 0 4px}
input{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #dde3ea;border-radius:9px;
      font-size:14px;outline:none;font-family:inherit}
input:focus{border-color:#2f6fed}
button{width:100%;margin-top:18px;padding:10px;border:0;border-radius:9px;background:#2f6fed;
       color:#fff;font-size:14px;cursor:pointer;font-family:inherit}
button:disabled{opacity:.6;cursor:default}
#err{color:#c0392b;font-size:12px;min-height:18px;margin-top:10px}
</style></head>
<body>
<form class="card" onsubmit="return doLogin(event)">
  <h1>ELN 实验记录</h1>
  <p class="sub">请用你的 ELN 账户登录（与桌面端同一个账户）</p>
  <label>账户名</label>
  <input id="u" autocomplete="username" autofocus>
  <label>密码</label>
  <input id="p" type="password" autocomplete="current-password">
  <button id="go" type="submit">登录</button>
  <div id="err"></div>
</form>
<script>
const tok=new URLSearchParams(location.search).get('t')||'';
const withTok=p=>tok?p+'?t='+encodeURIComponent(tok):p;
async function doLogin(e){
  e.preventDefault();
  const u=document.getElementById('u').value.trim();
  const p=document.getElementById('p').value;
  const err=document.getElementById('err'), go=document.getElementById('go');
  err.textContent='';go.disabled=true;go.textContent='登录中…';
  try{
    const r=await fetch(withTok('/api/login'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user:u,password:p})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
    location.href=withTok('/');
  }catch(ex){
    err.textContent='登录失败：'+ex.message;
    go.disabled=false;go.textContent='登录';
  }
  return false;
}
</script>
</body></html>
"""
