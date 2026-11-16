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
header input[type=search]{flex:1;min-width:140px}
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
.svgbox{text-align:center;margin:12px 0}
.svgbox svg{max-width:100%;height:auto}
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
#umask{display:none;position:fixed;inset:0;background:rgba(16,22,32,.42);z-index:21;
      padding:24px;overflow:auto}
#umask.on{display:block}
#ued{max-width:560px;margin:0 auto;background:var(--card);border-radius:12px;padding:18px;
     box-shadow:0 12px 40px rgba(0,0,0,.18)}
#ued h3{margin:0 0 12px;font-size:16px}
.ulist{font-size:13px;margin-bottom:12px}
.ulist div{padding:5px 0;border-bottom:1px solid var(--line);display:flex;
           justify-content:space-between}
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
  <input id="q" type="search" placeholder="搜索标题 / 编号 / 结构 / 备注…">
  <button id="btnNew" class="primary">+ 新建</button>
  <button id="btnUsers" style="display:none">用户</button>
  <span id="who" class="who">{{USER}}</span>
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
  <div id="ulist" class="ulist"></div>
  <div class="grid">
    <div><label>账户名</label><input id="uname" type="text"></div>
    <div><label>密码（至少 6 位）</label><input id="upwd" type="password"></div>
    <div><label>角色</label>
      <select id="urole">
        <option value="user">普通用户</option>
        <option value="admin">管理员</option>
      </select></div>
  </div>
  <div class="foot">
    <button onclick="closeUsers()">关闭</button>
    <button class="primary" onclick="createUser()">创建账户</button>
  </div>
</div></div>

<script>
const S={kind:'reaction',id:null,q:'',form:null,comps:[]};
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;',
  '>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tok=new URLSearchParams(location.search).get('t')||'';
const qs=o=>Object.entries(o).filter(([,v])=>v!==''&&v!=null)
  .map(([k,v])=>k+'='+encodeURIComponent(v)).join('&');
const api=(p,o)=>fetch(p+'?'+qs(Object.assign({},o||{},{t:tok})))
  .then(r=>r.ok?r.json():r.json().then(e=>Promise.reject(e.error||r.status)));

document.querySelectorAll('.tab').forEach(el=>el.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  el.classList.add('on');S.kind=el.dataset.kind;S.id=null;
  document.getElementById('detail').innerHTML='<div class="empty">从左侧选择一条记录</div>';
  loadList();
});
document.getElementById('q').oninput=e=>{clearTimeout(window._t);
  window._t=setTimeout(()=>{S.q=e.target.value.trim();loadList();},280);};
document.getElementById('btnNew').onclick=()=>openEditor(null);

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
      <button class="danger" onclick="delRecord(${r.id})">删除</button>
      <a href="/api/export?${qs({kind:S.kind,id:r.id,fmt:'pdf',t:tok})}">
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
    if(r.note){h+='<div class="sec">备注</div><pre>'+esc(r.note)+'</pre>';}
    if(r.attachments.length){
      h+='<div class="sec">附件</div>'+r.attachments.map(a=>
        `<a href="/api/file?${qs({aid:a.id,t:tok})}"><button class="mini">${esc(a.title||a.path)}</button></a>`).join(' ');
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
        const inner=fd.multiline
          ? `<textarea id="f_${fd.key}">${val}</textarea>`
          : `<input type="${fd.type||'text'}" id="f_${fd.key}" value="${val}">`;
        return `<div class="${fd.multiline?'full':''}"><label>${esc(fd.label)}</label>${inner}</div>`;
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
document.onkeydown=e=>{if(e.key==='Escape'){closeEditor();closeUsers();}};

/* ---------- 账户：当前用户 / 管理员建号 ---------- */
fetch('/api/me').then(r=>r.json()).then(m=>{
  const who=document.getElementById('who');
  if(m.user){
    who.innerHTML=esc(m.user)+(m.role==='admin'?'（管理员）':'')+
      ' <a href="/logout">退出</a>';
  }
  if(m.role==='admin'){
    const b=document.getElementById('btnUsers');
    b.style.display='';b.onclick=openUsers;
  }
}).catch(()=>{});

async function openUsers(){
  try{
    const d=await api('/api/users');
    document.getElementById('ulist').innerHTML=d.users.map(u=>
      `<div><span>${esc(u.name)}</span><span>${u.role==='admin'?'管理员':'普通用户'}
       · ${esc(u.created||'')}</span></div>`).join('')||'<div>（暂无）</div>';
    document.getElementById('umask').classList.add('on');
  }catch(e){alert('读取账户失败：'+e);}
}
function closeUsers(){document.getElementById('umask').classList.remove('on');}
document.getElementById('umask').onclick=e=>{
  if(e.target.id==='umask')closeUsers();
};

async function createUser(){
  const name=document.getElementById('uname').value.trim();
  const password=document.getElementById('upwd').value;
  const role=document.getElementById('urole').value;
  if(!name||!password){alert('账户名和密码都要填');return;}
  try{
    const r=await fetch('/api/user/create?'+qs({t:tok}),{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,password,role})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||r.status);
    document.getElementById('uname').value='';
    document.getElementById('upwd').value='';
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
async function doLogin(e){
  e.preventDefault();
  const u=document.getElementById('u').value.trim();
  const p=document.getElementById('p').value;
  const err=document.getElementById('err'), go=document.getElementById('go');
  err.textContent='';go.disabled=true;go.textContent='登录中…';
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user:u,password:p})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||('HTTP '+r.status));
    location.href='/';
  }catch(ex){
    err.textContent='登录失败：'+ex.message;
    go.disabled=false;go.textContent='登录';
  }
  return false;
}
</script>
</body></html>
"""
