import { renderAppShell, bindAppShell, escapeHTML as esc, showToast } from '../components/app-shell.js';
import { renderSortableHeader, sortRows, getNextSortState, updateSortHeaders } from '../components/table-sort.js';

// 本地原型数据；不请求 API、不读写飞书或正式数据。刷新恢复初始场景。
const scenario = new URLSearchParams(location.search).get('scene') || 'partial';
const factories = [{ name:'希舟', enabled:true },{ name:'旭之梦', enabled:false }];
const rows = [
  { id:1, code:'6942649418812', name:'云朵探险家护耳帽', spec:'蔚海蓝M', factory:'希舟', date:'2026-09-21', quantity:1800, shipped:1800 },
  { id:2, code:'6942649418829', name:'云朵探险家护耳帽', spec:'蔚海蓝L', factory:'希舟', date:'2026-09-21', quantity:4200, shipped:3139 },
  { id:3, code:'6942649418836', name:'云朵探险家护耳帽', spec:'晨雾米M', factory:'希舟', date:'2026-09-21', quantity:900, shipped:915 },
  { id:4, code:'6942649418843', name:'云朵探险家护耳帽', spec:'晨雾米L', factory:'希舟', date:'', quantity:2100, shipped:580 },
  { id:5, code:'6942649418850', name:'云朵探险家护耳帽', spec:'星夜蓝M', factory:'旭之梦', date:'2026-09-21', quantity:1800, shipped:1440 },
  { id:6, code:'6942649418867', name:'云朵探险家护耳帽', spec:'星夜蓝L', factory:'', date:'', quantity:4200, shipped:2000 },
].map(row=>({...row, dispatched:['all','withdrawal'].includes(scenario)||(scenario!=='draft'&&row.id<=2), manual:new Set()}));
if(scenario==='all') rows.forEach(r=>{r.factory='希舟';r.date='2026-09-21';});
if(scenario==='withdrawal') rows.forEach((r,index)=>{r.factory=index<4?'希舟':'旭之梦';r.date='2026-09-21';});
const productCatalog = rows.map(({code,name,spec})=>({code,name,spec}));
const factoriesWithShipments = scenario==='withdrawal'?new Set(['希舟']):new Set();
const selected = new Set();
let sort={key:'id',direction:'asc'};
let sourceUpdated=false;
const logs=[];
const fmt=v=>Number.isFinite(Number(v))&&v!==''?Number(v).toLocaleString('zh-CN'):'—';
const validQuantity=r=>Number.isInteger(Number(r.quantity))&&Number(r.quantity)>0;
const validShipped=r=>r.shipped!==''&&Number.isInteger(Number(r.shipped))&&Number(r.shipped)>=0;
const pending=r=>!validQuantity(r)||!validShipped(r)?null:Math.max(Number(r.quantity)-Number(r.shipped),0);
const issues=r=>[
  ...(!productCatalog.some(p=>p.code===r.code&&p.name===r.name&&p.spec===r.spec)?['产品资料未匹配']:[]),
  ...(!r.factory?['工厂未匹配']:!factories.find(f=>f.name===r.factory)?.enabled?['工厂无审核通过且已启用账号']:[]),
  ...(!r.date?['缺合同出货时间']:[]),
  ...(!(Number.isInteger(Number(r.quantity))&&Number(r.quantity)>0)?['下单数量须为正整数']:[]),
  ...(!(r.shipped!==''&&Number.isInteger(Number(r.shipped))&&Number(r.shipped)>=0)?['初始已发数量须为非负整数']:[]),
];
function status(){
 if(rows.every(r=>!r.dispatched))return ['草稿','draft'];
 if(rows.every(r=>r.dispatched&&pending(r)===0))return ['已完成','success'];
 if(rows.some(r=>pending(r)>0&&r.date&&r.date<'2026-09-11'))return ['已逾期','danger'];
 return ['未完成','info'];
}
function edit(r,key){
 if(r.dispatched || key!=='date')return esc(fmtOrText(r,key));
 return `<input aria-label="第${r.id}条合同出货时间" data-edit="date" data-id="${r.id}" type="date" value="${esc(r.date)}">`;
}
function fmtOrText(r,key){return ['quantity','shipped'].includes(key)?fmt(r[key]):r[key]||'—';}
function content(){
 const count=rows.filter(r=>r.dispatched).length, hasPending=count<rows.length;
 const [label,tone]=status();
 const headers=[['产品编码','code'],['产品名称','name'],['颜色/规格','spec'],['工厂','factory']];
 const total=rows.reduce((a,r)=>a+Number(r.quantity||0),0), shipped=rows.reduce((a,r)=>a+Number(r.shipped||0),0);
 return `<article class="order-workspace order-detail-page dispatch-page">
 <section class="section-card detail-overview-card"><header class="detail-page-header"><button class="detail-back-button" data-back>‹ 返回</button><div class="detail-title-row"><span class="status-badge is-${tone}">${label}</span>${count?'<button class="detail-outline-button" data-withdraw>撤回派工</button>':''}<button class="detail-outline-button" disabled title="沿用已有合同资格，本示例存在已发数量">导出加工合同</button></div></header>
 <div class="detail-overview-content"><dl class="detail-summary-grid">${[['分类','帽子'],['跟单人员','松子'],['合同出货时间',[...new Set(rows.map(r=>r.date).filter(Boolean))].sort().join('、')||'—'],['订单数量',rows.every(validQuantity)?fmt(total):'—'],['已发数量',rows.every(validShipped)?fmt(shipped):'—'],['未发数量',rows.every(r=>pending(r)!==null)?fmt(rows.reduce((a,r)=>a+pending(r),0)):'—']].map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></div></section>
 <section class="section-card detail-section-card"><header class="detail-section-header"><div class="dispatch-heading"><h2>订单明细</h2><span class="dispatch-count">已派工 ${count}/${rows.length} 条 · ${count===0?'未派工':hasPending?'部分派工':'全部派工'}</span></div>${hasPending?`<div class="dispatch-actions"><button class="detail-outline-button" data-update>更新未派工明细</button><button class="detail-primary-button" data-dispatch ${!selected.size?'disabled':''}>派工（已选 ${selected.size} 条）</button></div>`:''}</header>
 <div class="detail-table-scroll"><table class="dispatch-table"><colgroup>${hasPending?'<col style="width:40px">':''}<col style="width:52px"><col style="width:160px"><col><col style="width:130px"><col style="width:125px"><col style="width:90px"><col style="width:170px"><col style="width:105px"><col style="width:105px"><col style="width:95px"><col style="width:135px"></colgroup><thead><tr>${hasPending?`<th class="dispatch-check"><input type="checkbox" data-all aria-label="选择全部未派工明细" ${rows.filter(r=>!r.dispatched).every(r=>selected.has(r.id))?'checked':''}></th>`:''}<th class="dispatch-seq">序号</th>${headers.map(([title,key])=>renderSortableHeader(title,key)).join('')}<th>派工状态</th>${[['合同出货时间','date'],['下单数量','quantity'],['已发数量','shipped'],['未发数量','pending'],['发货进度','progress']].map(([title,key])=>renderSortableHeader(title,key)).join('')}</tr></thead><tbody>${sortRows(rows,sort,(r,key)=>key==='pending'?pending(r):key==='progress'?Number(r.shipped)/Number(r.quantity):r[key]).map(r=>`<tr>${hasPending?`<td class="dispatch-check">${r.dispatched?'':`<input type="checkbox" data-select="${r.id}" aria-label="选择第${r.id}条" ${selected.has(r.id)?'checked':''}>`}</td>`:''}<td class="dispatch-seq">${r.id}</td><td class="dispatch-code">${edit(r,'code')}</td><td title="${esc(r.name)}">${edit(r,'name')}</td><td>${esc(r.spec)}</td><td>${edit(r,'factory')}</td><td><span class="status-badge is-${r.dispatched?'info':'draft'}">${r.dispatched?'已派工':'未派工'}</span></td><td>${edit(r,'date','date')}</td><td>${edit(r,'quantity','number')}</td><td>${r.dispatched?fmt(r.shipped):edit(r,'shipped','number')}</td><td>${pending(r)===null?'—':fmt(pending(r))}</td><td><span class="detail-progress"><span><i style="width:${Math.min(100,Math.max(0,Number(r.shipped)/Number(r.quantity)*100))||0}%"></i></span><em>${r.quantity?Math.round(r.shipped/r.quantity*100):'—'}%</em></span></td></tr>`).join('')}</tbody></table></div></section>
 <section class="section-card"><header class="detail-section-header"><h2>关联发货单</h2></header><div class="detail-empty-row">${scenario==='withdrawal'?'希舟 · FH20260911-001 · 已发货':'暂无关联发货单'}</div></section>
 <section class="section-card"><header class="detail-section-header"><h2>操作日志</h2></header><div class="dispatch-logs">已从飞书导入订单资料${logs.map(log=>`<br>${esc(log)}`).join('')}</div></section></article>`;
}
function render(){
 document.querySelector('#app').innerHTML=renderAppShell({content:content(),notifications:[],activeModule:'orders',topbarTitle:'订单详情 · 407#',sidebarSectionLabel:'订单与发货',sideNavItems:[{label:'订单列表',icon:'orders',route:'/orders',isActive:true},{label:'待导入订单',icon:'import',route:'/pending-imports'},{label:'发货单列表',icon:'shipment',route:'/shipments'},{label:'返修退回',icon:'repair',route:'/repairs'}]});
 bindAppShell([]);
 document.querySelectorAll('[data-route]').forEach(b=>b.addEventListener('click',()=>location.href='./index.html#'+b.dataset.route));
 document.querySelector('[data-back]').onclick=()=>location.href='./index.html#/orders';
 document.querySelectorAll('[data-select]').forEach(el=>el.onchange=()=>{const id=Number(el.dataset.select);el.checked?selected.add(id):selected.delete(id);render();});
 document.querySelector('[data-all]')?.addEventListener('change',e=>{rows.filter(r=>!r.dispatched).forEach(r=>e.target.checked?selected.add(r.id):selected.delete(r.id));render();});
 document.querySelectorAll('[data-edit]').forEach(el=>el.onchange=()=>{const r=rows.find(r=>r.id===Number(el.dataset.id));r[el.dataset.edit]=el.value;r.manual.add(el.dataset.edit);render();});
 document.querySelectorAll('[data-sort-key]').forEach(el=>el.onclick=e=>{sort=getNextSortState(e,sort);render();});
 updateSortHeaders(document.querySelector('.dispatch-table'),sort);
 document.querySelector('[data-update]')?.addEventListener('click',()=>updatePreview());
 document.querySelector('[data-dispatch]')?.addEventListener('click',()=>updatePreview(dispatchPreview));
 document.querySelector('[data-withdraw]')?.addEventListener('click',withdrawPreview);
}
function modal(title,body,confirm,disabled=false,confirmLabel='确认'){
 const d=document.createElement('dialog');d.className='modal dispatch-modal';
 d.innerHTML=`<header><h2>${esc(title)}</h2><button aria-label="关闭" data-close>×</button></header><div class="modal-body">${body}</div><footer><button class="order-secondary-button" data-close>取消</button>${confirm?`<button class="order-primary-button" data-confirm ${disabled?'disabled':''}>${esc(confirmLabel)}</button>`:''}</footer>`;
 document.body.append(d);d.showModal();
 d.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>d.close());
 d.querySelector('[data-confirm]')?.addEventListener('click',()=>{d.close();confirm();});
 d.addEventListener('close',()=>d.remove());
 return d;
}
function updatePreview(next){
 const changes=rows.filter(r=>!r.dispatched&&!sourceUpdated&&r.id===4).flatMap(r=>[
  ...(!r.manual.has('shipped')?[{r,key:'shipped',label:'已发数量',value:620}]:[]),
  ...(!r.manual.has('date')?[{r,key:'date',label:'合同出货时间',value:'2026-09-21'}]:[]),
 ]);
 if(!changes.length){if(next)next();else modal('更新未派工明细','<p>未派工明细没有可更新的来源变化，人工补填内容已保留。</p>');return;}
 modal('更新未派工明细',`<p>来源资料有变化，请确认后${next?'继续派工':'更新'}。已派工明细和人工补填内容保持不变。</p><table><thead><tr><th>明细</th><th>字段</th><th>当前值</th><th>来源新值</th></tr></thead><tbody>${changes.map(c=>`<tr><td>第${c.r.id}条 · ${esc(c.r.spec)}</td><td>${c.label}</td><td>${esc(c.r[c.key]||'—')}</td><td>${esc(c.value)}</td></tr>`).join('')}</tbody></table>`,()=>{changes.forEach(c=>c.r[c.key]=c.value);sourceUpdated=true;logs.push('确认更新未派工明细来源资料');render();if(next)next();});
}
function dispatchPreview(){
 const chosen=rows.filter(r=>selected.has(r.id)&&!r.dispatched), blocked=chosen.some(r=>issues(r).length);
 if(!chosen.length)return;
 modal('确认派工',`<p>${blocked?'所选明细存在未通过项，本次不会派工。请取消勾选或补齐资料后重试。':'所选明细校验通过。确认后对应工厂可以查看本次派工明细。'}</p><table><thead><tr><th>明细</th><th>工厂</th><th>校验结果</th></tr></thead><tbody>${chosen.map(r=>`<tr><td>第${r.id}条 · ${esc(r.spec)}</td><td>${esc(r.factory||'—')}</td><td class="${issues(r).length?'dispatch-error':'dispatch-pass'}">${esc(issues(r).join('；')||'通过')}</td></tr>`).join('')}</tbody></table>`,()=>{chosen.forEach(r=>{r.dispatched=true;selected.delete(r.id);});logs.push(`本次派工 ${chosen.length} 条明细`);render();showToast('派工成功','所选明细已派工。');},blocked);
}
function withdrawPreview(){
 const activeFactories=[...new Set(rows.filter(r=>r.dispatched).map(r=>r.factory))];
 const d=modal('撤回派工',`<p>撤回后，该工厂的明细恢复为未派工，其他工厂不受影响。</p><div class="withdraw-field"><label for="withdraw-factory">选择工厂</label><select id="withdraw-factory" data-withdraw-factory><option value="">请选择</option>${activeFactories.map(factory=>{const count=rows.filter(r=>r.dispatched&&r.factory===factory).length,blocked=factoriesWithShipments.has(factory);return `<option value="${esc(factory)}" ${blocked?'disabled':''}>${esc(factory)}（${count} 条${blocked?'，已有有效发货，不可撤回':''}）</option>`;}).join('')}</select></div>`,()=>{
  const factory=d.querySelector('[data-withdraw-factory]').value;
  rows.filter(r=>r.dispatched&&r.factory===factory).forEach(r=>{r.dispatched=false;});
  selected.clear();logs.push(`撤回 ${factory} 全部派工明细`);render();showToast('撤回成功',`${factory}的派工明细已撤回。`);
 },true,'确认撤回');
 const select=d.querySelector('[data-withdraw-factory]'),confirm=d.querySelector('[data-confirm]');
 select.addEventListener('change',()=>{confirm.disabled=!select.value;});
}
render();
