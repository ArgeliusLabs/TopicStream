'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const lines = id => $(id).value.split(/\n/).map(s=>s.trim()).filter(Boolean);
const commas = id => $(id).value.split(',').map(s=>s.trim()).filter(Boolean);
let token, currentId, current, openedEvidence, timer;
const endpoint = (suffix='') => `/api/cases/${currentId}${suffix}`;
const busy = () => current && ['queued','running'].includes(current.job.status);
function message(text, error=false) { $('message').hidden=!text; $('message').textContent=text; $('message').className=error?'error':'notice'; }
async function api(path, body) {
  const response=await fetch(path, body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-TopicStream-Token':token},body:JSON.stringify(body)});
  const value=await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
function handle(fn) { return async event => { event?.preventDefault(); try { await fn(event); } catch(error) { message(error.message,true); } }; }
function utcDate(value) { return new Date(value).toISOString().slice(0,10); }
function queryPreview() {
  const tags=lines('tags').map(t=>'#'+t.replace(/^#/,'')); const terms=lines('terms');
  $('query-preview').textContent=`X: ${[...tags,...terms.map(t=>'"'+t+'"')].join(' OR ') || '(none)'}\nBluesky: ${[...tags,...terms].join(' · ') || '(none)'}\nMastodon: ${tags.join(' · ') || 'No hashtag selected; no phrase-only search'}\nExclusions and languages filter retrieved posts locally; they do not reduce paid retrieval.`;
}
async function listCases() {
  const cases=await api('/api/cases');
  $('case-list').innerHTML=cases.map(c=>`<button class="case-item ${c.id===currentId?'active':''}" data-case="${c.id}"><strong>${escapeHTML(c.topic)}</strong><small>${c.synthetic?'SYNTHETIC · ':''}${escapeHTML(c.status)}</small></button>`).join('') || '<p class="hint">Your saved cases will appear here.</p>';
  $('case-list').querySelectorAll('[data-case]').forEach(button=>button.addEventListener('click',handle(()=>openCase(button.dataset.case))));
}
function newCase() { clearTimeout(timer); currentId=null; current=null; $('create-view').hidden=false; $('detail-view').hidden=true; $('breadcrumb').textContent='Workspace / New investigation'; message(''); $('topic').focus(); listCases().catch(e=>message(e.message,true)); }
async function openCase(id) { clearTimeout(timer); currentId=id; $('create-view').hidden=true; $('detail-view').hidden=false; message(''); await refresh(); await listCases(); }
const table = (head, rows) => `<table><thead><tr>${head.map(h=>`<th>${escapeHTML(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
const cells = values => `<tr>${values.map(v=>`<td>${escapeHTML(v)}</td>`).join('')}</tr>`;
async function refresh() {
  const id=currentId; if (!id) return;
  const detail=await api(`/api/cases/${id}`); if(id!==currentId) return;
  const previousStatus=current?.job.status;
  current=detail; render(); clearTimeout(timer);
  if(previousStatus!==detail.job.status) { await listCases(); if(!busy()) message(''); }
  if(busy()) timer=setTimeout(()=>refresh().catch(e=>message(e.message,true)),1200);
}
function render() {
  const d=current, a=d.analysis, cfg=d.config;
  $('breadcrumb').textContent='Workspace / Investigation'; $('case-title').textContent=d.case.topic;
  $('case-kind').textContent=d.case.synthetic?'SYNTHETIC EXAMPLE · INVENTED ACCOUNTS':'INVESTIGATION';
  $('case-scope').textContent=`${cfg.start_utc.slice(0,10)} → ${cfg.end_utc.slice(0,10)} UTC · ${[...cfg.tags.map(t=>'#'+t),...cfg.terms].join(' · ')}`;
  $('job-message').textContent=`${d.job.status}: ${d.job.message}`; $('cancel').hidden=!busy();
  $('collect').disabled=busy() || d.case.synthetic || !Object.values(cfg.sources).some(s=>s.enabled); $('analyze').disabled=busy(); $('import-form').querySelector('button').disabled=busy();
  $('export').href=endpoint('/export'); $('report').href=endpoint('/report'); $('report').hidden=!a;
  $('metrics').innerHTML=[[d.posts,'Posts in scope'],[a?Object.keys(a.accounts).length:'—','Accounts analyzed'],[a?a.groups.length:'—','Recurring groups'],[`$${d.spent_usd.toFixed(4)}`,'X ledger · used / reserved']].map(([value,label])=>`<div class="metric"><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></div>`).join('');
  $('assessment').innerHTML=`<span class="eyebrow">CURRENT ASSESSMENT</span><h2>${escapeHTML(a?.assessment || 'Ready for evidence')}</h2><p>${escapeHTML(a?.authenticity || 'Import an export or collect public posts from your enabled sources, then inspect the findings.')}</p>${a?`<p class="hint">${escapeHTML(a.interpretation)}${a.limits.truncated_posts?' Analysis is limited to the earliest '+a.posts_analyzed+' posts.':''}</p>`:''}`;
  $('groups').innerHTML=a?.groups.length ? a.groups.map((g,index)=>`<article class="panel group-card"><div class="row between wrap"><div><span class="eyebrow">GROUP ${String(index+1).padStart(2,'0')}</span><h3>${g.accounts.length} accounts · ${g.edges.length} recurring connections</h3></div><button class="secondary" data-group="${g.id}">Inspect evidence →</button></div><p>${escapeHTML(g.explanation)}</p><div class="row wrap">${g.families.map(f=>`<span class="pill">${escapeHTML(f)}</span>`).join('')}<span class="hint">${g.post_keys.length} supporting posts · density ${g.density} · rank ${g.ranking_score}</span></div></article>`).join('') : '<div class="empty">'+(a?'No group met the recurrence thresholds. Check coverage before interpreting this result.':'Your findings will appear after analysis.')+'</div>';
  $('groups').querySelectorAll('[data-group]').forEach(button=>button.addEventListener('click',handle(()=>showEvidence(button.dataset.group))));
  $('baseline').hidden=!a;
  if(a) $('baseline').innerHTML=`<h3>Comparison with shuffled timing</h3><p><strong>${a.recurring_edges}</strong> recurring connections observed. Shuffled runs: <strong>${escapeHTML(a.baseline.recurring_edges_per_shuffle.join(', ') || 'unavailable')}</strong>.</p><p class="hint">${escapeHTML(a.baseline.method)}. ${escapeHTML(a.baseline.limitation)}</p><p class="hint">${a.limits.missing_stable_id_accounts} accounts lack stable IDs. ${a.limits.high_volume_events_not_compared} very large events were excluded from pair comparisons.</p>`;
  $('coverage-table').innerHTML=d.coverage.length ? table(['Source / query','Interval UTC','Status','Reason / sampling','Posts'],d.coverage.map(c=>cells([`${c.source} / ${c.label}`,`${c.start_utc} → ${c.end_utc}`,c.status,`${c.stop_reason} · ${c.sampling}`,c.retrieved]))) : '<p>No collection or import coverage recorded yet.</p>';
  $('saved-plan').innerHTML=`<h3>Saved search plan</h3><p>Sources: ${escapeHTML(Object.entries(cfg.sources).filter(([,v])=>v.enabled).map(([k])=>k).join(', ') || 'Import only')}</p><p>Excluded phrases: ${escapeHTML(cfg.exclude_terms.join(', ') || 'None')} · Languages: ${escapeHTML(cfg.languages.join(', ') || 'Any')}</p><p>Case budget: $${cfg.sources.x.budget_usd.toFixed(2)}. This ledger covers this case database. Separate cases, tools, or applications can spend outside it.</p><p class="hint">Query fingerprint: ${escapeHTML(cfg.query_fingerprint)}</p>`;
  $('log').textContent=(d.job.log || []).join('\n') || 'No jobs yet.';
}
function graph(group, accounts) {
  const shown=group.accounts.slice(0,40), n=shown.length, points=new Map(shown.map((id,i)=>[id,[300+215*Math.cos(2*Math.PI*i/n),205+155*Math.sin(2*Math.PI*i/n)]]));
  const edges=group.edges.filter(e=>points.has(e.a)&&points.has(e.b)).map(e=>{const [x1,y1]=points.get(e.a),[x2,y2]=points.get(e.b);return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#9dcabc" stroke-width="2"><title>${escapeHTML(e.a+' ↔ '+e.b+': '+e.episodes+' episodes')}</title></line>`;}).join('');
  const nodes=shown.map((id,i)=>{const [x,y]=points.get(id);return `<g><circle cx="${x}" cy="${y}" r="16" fill="#08664d"><title>${escapeHTML(accounts[id]?.handle || id)}</title></circle><text x="${x}" y="${y+5}" text-anchor="middle" fill="white" font-size="12">${i+1}</text></g>`;}).join('');
  return `<svg viewBox="0 0 600 410" role="img" aria-label="Recurring account connections">${edges}${nodes}</svg><p class="hint">Each line is a recurring pair, not proof of common ownership. ${n<group.accounts.length?'Graph shows the first 40 accounts; the export contains all connections.':''}</p><ol class="account-legend">${shown.map(id=>`<li>${escapeHTML(accounts[id]?.handle || id)} <small>${escapeHTML(id)}</small></li>`).join('')}</ol>`;
}
function postLink(post) {
  let href=post.url;
  if(!href && post.source==='x' && /^\d+$/.test(post.post_id)) href='https://x.com/i/status/'+post.post_id;
  try { const url=new URL(href); if(!['http:','https:'].includes(url.protocol)||url.username||url.password) return ''; return `<a href="${escapeHTML(url.href)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>`; } catch { return ''; }
}
function reviewHistory() {
  $('review-history').innerHTML='<h3>Review history</h3>'+current.reviews.filter(r=>r.group_id===openedEvidence.group.id).map(r=>`<div class="review"><strong>${escapeHTML(r.assessment)}</strong><p>${escapeHTML(r.explanation)}</p><small>${escapeHTML(r.created_utc)}${r.dataset_hash!==openedEvidence.dataset_hash?' · Earlier evidence version':''}</small></div>`).join('');
}
async function showEvidence(id) {
  const evidence=await api(endpoint('/groups/'+id)); openedEvidence=evidence;
  const g=evidence.group; $('evidence-title').textContent=`${g.accounts.length} accounts · ${g.post_keys.length} supporting posts`;
  $('evidence-content').innerHTML=`<p>${escapeHTML(g.explanation)}</p><div class="graph">${graph(g,current.analysis.accounts)}</div><h3>Alternative explanations to examine</h3><ul>${g.alternatives.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ul><h3>Timeline of shared activity</h3><div class="scroll">${table(['UTC','Trace','Accounts','Evidence'],evidence.events.map(e=>cells([e.start,e.family+': '+e.trace,e.accounts.length,e.post_keys.length+' posts'])))}</div><h3>Supporting posts</h3>${evidence.posts.map(p=>`<article class="evidence-post"><label class="check"><input type="checkbox" name="evidence" value="${escapeHTML(p.key)}"> <strong>${escapeHTML(p.author)}</strong> · ${escapeHTML(p.created_utc)}</label><p>${escapeHTML(p.text)}</p><div class="row between"><small>${escapeHTML(p.key)}</small>${postLink(p)}</div></article>`).join('')}<p class="fine">Evidence version: ${escapeHTML(evidence.dataset_hash)}</p>`;
  $('review-form').reset(); $('review-status').textContent=''; reviewHistory(); $('evidence-dialog').showModal();
}
$('plan-form').addEventListener('submit',handle(async()=>{const p=await api('/api/plan',{topic:$('topic').value}); $('terms').value=p.terms.join('\n'); $('tags').value=p.tags.join('\n'); $('case-form').hidden=false; queryPreview(); $('terms').focus();}));
['terms','tags','excludes','languages'].forEach(id=>$(id).addEventListener('input',queryPreview));
$('case-form').addEventListener('submit',handle(async()=>{const d=await api('/api/cases',{topic:$('topic').value,terms:lines('terms'),tags:lines('tags'),exclude_terms:commas('excludes'),languages:commas('languages'),start_utc:$('start').value+'T00:00:00Z',end_utc:$('end').value+'T00:00:00Z',sources:[...$('source-options').querySelectorAll('input:checked')].map(i=>i.value),budget_usd:Number($('budget').value)}); await openCase(d.case.id);}));
$('new-case').addEventListener('click',newCase);
$('demo').addEventListener('click',handle(async()=>{const d=await api('/api/demo',{}); await openCase(d.id);}));
['collect','analyze','cancel'].forEach(action=>$(action).addEventListener('click',handle(async()=>{await api(endpoint('/'+action),{}); await refresh(); await listCases();})));
document.querySelectorAll('[data-tab]').forEach(tab=>tab.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(t=>t.setAttribute('aria-selected',String(t===tab))); document.querySelectorAll('.tab-panel').forEach(p=>p.hidden=p.id!==tab.dataset.tab);}));
$('import-form').addEventListener('submit',handle(async()=>{const csv=$('csv-file').files[0], profiles=$('profiles-file').files[0]; if(!csv) return; if(csv.size>10*1024*1024||(profiles&&profiles.size>1024*1024)) throw new Error('Limit posts to 10 MB and profiles to 1 MB.'); await api(endpoint('/import'),{csv:await csv.text(),source:$('import-source').value,profiles:profiles?await profiles.text():null}); message('Import saved; analysis is queued.'); await refresh();}));
$('close-evidence').addEventListener('click',()=>$('evidence-dialog').close());
$('review-form').addEventListener('submit',async event=>{event.preventDefault(); try { await api(endpoint('/review'),{group_id:openedEvidence.group.id,dataset_hash:openedEvidence.dataset_hash,assessment:$('review-assessment').value,explanation:$('review-explanation').value,evidence:[...$('evidence-content').querySelectorAll('input:checked')].map(i=>i.value)}); await refresh(); reviewHistory(); $('review-status').textContent='Review saved.'; } catch(error) { $('review-status').textContent=error.message; }});
(async()=>{try { const session=await api('/api/session'); token=session.token; Object.entries(session.credentials).forEach(([name,available])=>$(name+'-status').textContent=available?'available':'credentials missing'); const end=new Date(); $('end').value=utcDate(end); $('start').value=utcDate(end.getTime()-7*86400000); await listCases(); } catch(error) {message(error.message,true);} })();
