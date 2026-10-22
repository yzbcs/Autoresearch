"use strict";
(() => {
  if (location.protocol === "file:") {
    document.body.innerHTML = '<main><h1>请从本地服务打开 Auto Figure</h1><p><a href="http://127.0.0.1:8760/auto-figure/">打开 AutoResearch 工作台</a></p></main>';
    return;
  }
  const $ = (s) => document.querySelector(s);
  const prefix = location.pathname.startsWith("/auto-figure") ? "/auto-figure" : "";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  const names = {inspect:"读取论文",plan:"规划插图位置",prepare:"准备缺图论文",generate:"FigureCrafter 绘图",patch:"插入论文",compile:"编译 PDF",review:"图文复核"};
  const statuses = {awaiting_references:"等待确认参考图",idle:"待开始",running:"运行中",ready:"已通过复核",failed:"执行失败",paused:"已暂停",needs_revision:"需要修改",stale:"上游已更新"};
  let referenceFiles = [null,null,null], referenceDirty = false;
  let selected = new URLSearchParams(location.search).get("project"), current, busy = false, key = "";
  async function api(path, payload) {
    const response = await fetch(prefix + path, payload === undefined ? {cache:"no-store"} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || "请求失败"); return data;
  }
  function notice(message="") { $("#notice").textContent=message; $("#notice").hidden=!message; }
  function fileUrl(name) { return `${prefix}/api/projects/${encodeURIComponent(selected)}/files/${name.split("/").map(encodeURIComponent).join("/")}`; }
  async function refresh() {
    try {
      const {projects} = await api("/api/projects");
      if (selected && !projects.some(p=>p.id===selected)) { selected=null;current=null;key="";referenceDirty=false;referenceFiles=[null,null,null]; }
      if (!selected && projects.length) selected=projects[0].id;
      $("#projects").innerHTML=projects.map(p=>`<button data-id="${esc(p.id)}" class="${p.id===selected?"selected":""}"><strong>${esc(p.title)}</strong><small>${esc(statuses[p.status])} · ${esc(names[p.step])}</small></button>`).join("") || "<p>暂无绘图任务</p>";
      if (!selected) $("#detail").innerHTML='<h2>开始论文绘图</h2><p>全流程会在 Auto Table 复核通过后自动将论文交接到这里。也可以点击“新建任务”，接续已有论文或上传 LaTeX ZIP。</p><p>确认三张参考图后开始绘图，完成后下载含图完整论文 PDF、独立主图 PDF 和可编辑 PPTX。</p>';
      if (selected) {
        current=await api(`/api/projects/${encodeURIComponent(selected)}`);
        const next=JSON.stringify(current);
        if(next!==key && !referenceDirty && !($("#detail").contains(document.activeElement) && ["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName))) { key=next; render(); }
      }
    } catch(e) { notice(e.message); }
    setTimeout(refresh,2000);
  }
  function render() {
    const p=current, base=`attempt-${p.attempt}/`, out=p.outputs;
    $("#detail").innerHTML=`<h2>${esc(p.title)}</h2><small>第 ${p.attempt} 轮 · ${esc(statuses[p.status])}</small><ol class="steps">${Object.entries(names).map(([k,n])=>`<li class="${p.step===k?"current":""} ${p.completed_steps.includes(k)?"done":""}">${n}</li>`).join("")}</ol><p>${esc(p.message)}</p>
      ${p.source?`<p>来自 AutoTable 第 ${p.source.attempt} 轮 · <a href="/auto-table/?project=${encodeURIComponent(p.source.table_id)}">查看来源论文 ↗</a></p>`:""}
      ${p.backend==='figurecrafter'?`<section class="reference-section"><h3>三张风格参考图</h3><p>${p.references_confirmed?'本轮已确认。更换参考图将创建新轮次并保留旧稿。':'请选择三张参考图；可沿用默认图或上传 PNG/JPEG（每张最多 6 MB），确认后开始绘图。'}</p><div class="reference-grid">${p.references.map((r,i)=>`<div><a href="${fileUrl(r.path)}" target="_blank" rel="noopener"><img class="reference-image" data-ref-preview="${i}" src="${fileUrl(r.path)}" alt="参考图 ${i+1}"></a><label>参考图 ${i+1}<small>${esc(r.name)}</small><select data-ref-choice="${i}" ${p.status==='running'?'disabled':''}><option value="keep">保留当前图</option>${[1,2,3].map(n=>`<option value="${n}">默认参考图 ${n}</option>`).join('')}</select><input type="file" data-ref-file="${i}" accept="image/png,image/jpeg" ${p.status==='running'?'disabled':''}></label></div>`).join('')}</div>${p.status!=='running'&&p.status!=='stale'?'<div class="actions"><button data-action="defaults" class="secondary">恢复默认三张</button><button data-action="confirm-references">确认三张参考图并开始绘图</button></div>':''}</section>`:'<p>历史 AutoFigure-Edit 任务仅保留查看与下载，请新建 FigureCrafter 任务。</p>'}
      <div class="actions">${p.status==="running"?'<button data-action="stop" class="secondary">停止当前步骤</button>':p.status!=="stale" && p.backend==="figurecrafter" && p.references_confirmed?`<button data-action="start" ${["ready","needs_revision"].includes(p.status)?"hidden":""}>开始 / 继续</button><button data-action="revise" class="secondary">修改要求并重新生成</button>`:""}</div>
      ${p.status!=="running"?`<label>修改要求 / 复核反馈<textarea id="feedback" rows="2">${esc(p.requirements)}</textarea></label><details><summary>修改本轮绘图配置</summary><textarea id="revision-config" rows="4">${esc(JSON.stringify(p.config,null,2))}</textarea></details>`:""}
      ${out.preview?`<img class="preview" src="${fileUrl(base+out.preview)}" alt="方法主图预览">`:""}
      <div class="actions">${[["pptx","可编辑主图 PPTX"],["figure_pdf","独立主图 PDF"],["svg","历史主图 SVG"],["pdf","含图完整论文 PDF"],["zip","LaTeX 源码 ZIP"],["bundle","完整交付包"]].filter(([k])=>out[k]).map(([k,n])=>`<a href="${fileUrl(base+out[k])}" target="_blank" rel="noopener" download>${n} ↓</a>`).join("")}</div>
      ${p.status==='needs_revision'?'<button data-action="retry-review" class="secondary">重新复核当前论文</button>':''}
      ${p.review?`<h3>复核结果：${p.review.passed?"通过":"未通过"}</h3><pre>${esc(p.review.findings.join("\n"))}</pre>`:""}
      ${out.pdf?`<details><summary>预览含图论文 PDF</summary><iframe src="${fileUrl(base+out.pdf)}" title="含图论文 PDF"></iframe></details>`:""}
      <details><summary>源码差异、日志与全部产物</summary><div class="files">${p.artifacts.map(a=>`<a href="${fileUrl(a.name)}" target="_blank" rel="noopener">${esc(a.name)}</a>`).join("")}</div></details>`;
  }
  $("#new").onclick=async()=> { $("#create").hidden=!$("#create").hidden; try { const d=await api("/api/table-projects"); $("#table").innerHTML='<option value="">上传论文 LaTeX ZIP</option>'+d.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join(""); }catch(e){notice(e.message);} };
  $("#table").onchange=()=>{$("#uploads").hidden=!!$("#table").value;};
  function encode(file) { return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve({name:file.name,content_base64:r.result.split(",")[1]});r.onerror=reject;r.readAsDataURL(file);}); }
  $("#create").onsubmit=async event=>{
    event.preventDefault();if(busy)return;busy=true;const button=event.target.querySelector('button[type="submit"]');button.disabled=true;
    try{
      const payload=Object.fromEntries(new FormData(event.target));payload.config=JSON.parse($("#config").value||"{}");
      let p;
      if($("#table").value){payload.project_id=$("#table").value;p=await api("/api/import-table",payload);}
      else {const files=[$("#zip").files[0],$("#pdf").files[0]].filter(Boolean);if(!$("#zip").files[0])throw new Error("请选择论文 ZIP。");if(files.some(f=>f.size>20*1024*1024))throw new Error("单个文件不能超过 20 MB。");payload.files=await Promise.all(files.map(encode));p=await api("/api/projects",payload);}
      selected=p.id;key="";referenceDirty=false;referenceFiles=[null,null,null];$("#create").hidden=true;notice("论文已保存，请在下方确认三张参考图。");
    }catch(e){notice(e.message);}finally{busy=false;button.disabled=false;}
  };
  $("#projects").onclick=e=>{const b=e.target.closest("[data-id]");if(b){selected=b.dataset.id;key="";referenceFiles=[null,null,null];referenceDirty=false;}};
  $("#detail").onchange=async e=>{
    const f=e.target.dataset.refFile, choice=e.target.dataset.refChoice;
    if(f!==undefined){const file=e.target.files[0];referenceFiles[Number(f)]=file||null;referenceDirty=true;if(file){const data=await encode(file);$(`[data-ref-preview="${f}"]`).src=`data:${file.type};base64,${data.content_base64}`;}}
    if(choice!==undefined){referenceDirty=true;referenceFiles[Number(choice)]=null;$(`[data-ref-file="${choice}"]`).value='';$(`[data-ref-preview="${choice}"]`).src=e.target.value==='keep'?fileUrl(current.references[Number(choice)].path):`${prefix}/default-references/${e.target.value}.png`;}
  };
  $("#detail").onclick=async e=>{
    const b=e.target.closest("[data-action]");if(!b||busy)return;
    const action=b.dataset.action;
    if(action==='defaults'){referenceFiles=[null,null,null];referenceDirty=true;[0,1,2].forEach(i=>{$(`[data-ref-choice="${i}"]`).value=String(i+1);$(`[data-ref-file="${i}"]`).value='';$(`[data-ref-preview="${i}"]`).src=`${prefix}/default-references/${i+1}.png`;});return;}
    busy=true;b.disabled=true;
    try {
      if(action==='confirm-references'){
        const slots=await Promise.all([0,1,2].map(async i=>{if(referenceFiles[i])return encode(referenceFiles[i]);const n=$(`[data-ref-choice="${i}"]`).value;return n==='keep'?{keep:true}:{default:Number(n)};}));
        await api(`/api/projects/${encodeURIComponent(selected)}/references`,{slots,confirm:true});
        referenceFiles=[null,null,null];referenceDirty=false;
        await api(`/api/projects/${encodeURIComponent(selected)}/start`,{});
      }else if(action==='retry-review'){
        await api(`/api/projects/${encodeURIComponent(selected)}/start`,{retry_review:true});
      }else{
        const revise=action==='revise';await api(`/api/projects/${encodeURIComponent(selected)}/${revise?'start':action}`,revise?{revise:true,requirements:$("#feedback").value,feedback:$("#feedback").value,config:JSON.parse($("#revision-config").value)}:{});
      }
      key='';notice();
    }catch(e){notice(e.message);}finally{busy=false;b.disabled=false;}
  };
  api("/api/health").then(h=>{$("#health").textContent=`FigureCrafter ${h.figure.version}；绘图环境：${h.figure.python?'可用':'未安装'}；Codex：${h.codex_cli?'可用':'未找到'}；LibreOffice：${h.figure.soffice?'可用':'未找到'}；LaTeX：${h.latex?'可用':'未找到'}；默认三张参考图：${h.figure.default_references?'可用':'缺失'}`;}).catch(e=>notice(e.message));
  refresh();
})();
