import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowRight, BookOpen, Check, ChevronRight, Download, FlaskConical, GitBranch,
  Layers, Lightbulb, Pause, Play, Plus, Send, Settings2, Sparkles, Square, X } from 'lucide-react';
import type { Direction, Event, Project, Source } from './types';
import { ModelSettings, type ProviderConfig } from './ModelSettings';

async function api<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? undefined : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw new Error(typeof value.detail === 'string' ? value.detail : `请求失败（${response.status}），请检查输入。`);
  }
  return response.json();
}
const statuses: Record<string, string> = {running: '探索中', pausing: '正在暂停', paused: '已暂停', completed: '本轮完成', cancelled: '已结束', failed: '需要处理'};
const claimStates: Record<string, string> = {proposed: '研究设想', inferred: '机制推断', supported: '有来源支持', contested: '存在争议'};

function Modal({title, children, close}: {title: string; children: ReactNode; close: () => void}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} onCancel={close} aria-label={title}>
    <header><h2>{title}</h2><button className="icon-button" onClick={close} aria-label="关闭"><X size={20}/></button></header>{children}
  </dialog>;
}

function SourceLink({source, onClick}: {source?: Source; onClick: () => void}) {
  return <button className="source-link" onClick={onClick}><BookOpen size={14}/>{source?.title || '查看来源'}</button>;
}

function MechanismView({direction}: {direction: Direction}) {
  const [field, setField] = useState<'object'|'operation'|'output'|'signal'|'locus'>('operation');
  const fields = {object: '处理对象', operation: '核心操作', output: '输出表示', signal: '决策信号', locus: '作用位置'};
  return <section className="mechanism-view">
    <div className="section-heading"><h3>方法作用在哪里</h3><span className="tag">拟议机制</span></div>
    <div className="diagram" role="group" aria-label="方法机制图">
      <button className={'site-node ' + (field === 'locus' ? 'chosen' : '')} onClick={() => setField('locus')}><Layers size={16}/><span>作用位置</span><strong>{direction.mechanism.locus}</strong></button>
      <div className="flow">
        {(['object', 'operation', 'output'] as const).map((key, i) => <div className="flow-part" key={key}>
          {i > 0 && <ArrowRight className="flow-arrow" size={20} aria-hidden="true"/>}
          <button className={'node ' + (field === key ? 'chosen' : '')} onClick={() => setField(key)} aria-pressed={field === key}>
            <span>{fields[key]}</span><strong>{direction.mechanism[key]}</strong>
          </button>
        </div>)}
      </div>
      <button className={'signal-node ' + (field === 'signal' ? 'chosen' : '')} onClick={() => setField('signal')}><span>决策依据</span><strong>{direction.mechanism.signal}</strong></button>
    </div>
    <div className="node-detail" aria-live="polite"><span>{fields[field]}</span><p>{direction.mechanism[field]}</p></div>
    <h3>成立条件</h3><ul>{direction.mechanism.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
  </section>;
}

export default function App() {
  const [projects, setProjects] = useState<Pick<Project, 'id'|'title'|'question'|'revision'>[]>([]);
  const [id, setId] = useState('');
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState('overview');
  const [events, setEvents] = useState<Event[]>([]);
  const [history, setHistory] = useState<Project[]>([]);
  const [config, setConfig] = useState<ProviderConfig>({configured: false, model: '',
    models: [{id: 'default', api_base: '', model: '', has_api_key: false}],
    assignments: {exploration: 'default', literature: 'default', review: 'default'}});
  const [configLoaded, setConfigLoaded] = useState(false);
  const [modal, setModal] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [kind, setKind] = useState('instruction');
  const [scope, setScope] = useState('direction');
  const [sourceId, setSourceId] = useState('');
  const currentId = useRef(id);
  const refreshSequence = useRef(0);
  currentId.current = id;
  const refreshIndex = useCallback(async () => setProjects(await api('/projects')), []);
  const refresh = useCallback(async (projectId: string) => {
    const sequence = ++refreshSequence.current;
    const p = await api<Project>('/projects/' + projectId);
    if (currentId.current === projectId && sequence === refreshSequence.current) {
      setProject(p);
      setSelected(old => p.directions.some(d => d.id === old) ? old : p.directions[0]?.id || '');
    }
  }, []);
  useEffect(() => { refreshIndex().catch(e => setError(e.message)); api<typeof config>('/config').then(c => {setConfig(c); setConfigLoaded(true);}).catch(e => setError(e.message)); }, [refreshIndex]);
  useEffect(() => {
    setProject(null); setEvents([]); setSourceId(''); setSelected(''); setTab('overview'); setHistory([]);
    if (!id) return;
    refresh(id).catch(e => setError(e.message));
    const stream = new EventSource(`/api/projects/${id}/events`);
    stream.addEventListener('update', ev => {
      const event = JSON.parse((ev as MessageEvent).data) as Event;
      setEvents(old => old.some(e => e.seq === event.seq) ? old : [...old, event].slice(-60));
      refresh(id).catch(e => setError(e.message));
    });
    return () => stream.close();
  }, [id, refresh]);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await fn(); if (id) await refresh(id); await refreshIndex(); }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); }
  };
  const run = project?.runs[0];
  const active = run && ['running', 'pausing', 'paused'].includes(run.status);
  const direction = project?.directions.find(d => d.id === selected);
  const source = project?.sources.find(s => s.id === sourceId);
  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    act(async () => {
      const p = await api<Project>('/projects', Object.fromEntries(data));
      setId(p.id); setModal('');
    });
  };
  const showSource = (sid: string) => { setSourceId(sid); setTab('sources'); };

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Research Idea Agent 首页"><span className="brand-mark"><GitBranch size={22}/></span><span>Research<br/><b>Idea Agent</b></span></a>
      <button className="new-project" onClick={() => setModal('project')}><Plus size={17}/>新建研究课题</button>
      <div className="sidebar-label">研究空间 <span>{projects.length.toString().padStart(2, '0')}</span></div>
      <nav aria-label="研究课题">{projects.map(p => <button key={p.id} onClick={() => setId(p.id)} className={'project-nav ' + (p.id === id ? 'active' : '')}><span className="project-dot"/>{p.title}<ChevronRight size={14}/></button>)}</nav>
      <div className="sidebar-bottom"><span className={'status-dot ' + (config.configured ? 'online' : '')}/>{config.configured ? config.model : '尚未连接模型'}<p>个人研究工作台 · 本地存储</p></div>
    </aside>

    <main>
      <header className="topbar"><div className="breadcrumb"><FlaskConical size={16}/>研究工作台 <ChevronRight size={14}/><span>{project?.title || '开始探索'}</span></div>
        <button className="subtle" onClick={() => setModal('settings')}><Settings2 size={16}/>运行设置</button>
      </header>
      {error && <div className="error" role="alert">{error}<button aria-label="关闭错误提示" onClick={() => setError('')}><X size={16}/></button></div>}
      {!id ? <div className="welcome">
        <div className="eyebrow">A SPACE FOR RESEARCH</div><h1>找到值得研究的问题，<br/><em>让好的想法走得更远。</em></h1>
        <p>从一个问题、一篇论文或尚未成形的构思出发，理解已有基础，发展具有创新性、影响力和可行性的研究方向。</p>
        <button className="primary" onClick={() => setModal('project')}><Plus size={18}/>建立第一个课题<ArrowRight size={18}/></button>
        <div className="welcome-grid"><div><Lightbulb/><h3>发现与发展</h3><p>找到关键问题，沿着已有工作继续推进。</p></div><div><Layers/><h3>看清具体机制</h3><p>比较作用部位、方法差异与成立条件。</p></div><div><GitBranch/><h3>持续积累</h3><p>保留方向、证据和经验，随时回来继续。</p></div></div>
      </div> : !project ? <div className="loading">正在打开课题…</div> : <>
        <section className="project-header">
          <div><div className="eyebrow">RESEARCH SPACE · V{project.revision}</div><h1>{project.title}</h1><p>{project.question}</p>{project.constraints && <div className="constraint">研究条件 · {project.constraints}</div>}</div>
          <div className="run-actions">
            {active ? <><span className={'run-status ' + run.status}>{statuses[run.status]}</span><button className="primary" disabled={busy || run.status === 'pausing'} onClick={() => act(() => api(`/runs/${run.id}/commands`, {command: run.status === 'paused' ? 'resume' : 'pause'}))}>{run.status === 'paused' ? <Play size={16}/> : <Pause size={16}/>}{run.status === 'paused' ? '继续探索' : '暂停'}</button><button className="icon-button" aria-label="结束本轮探索" onClick={() => act(() => api(`/runs/${run.id}/commands`, {command: 'cancel'}))}><Square size={16}/></button></> : <button className="primary" disabled={busy || !config.configured} onClick={() => act(() => api(`/projects/${id}/runs`, {}))}><Sparkles size={16}/>{project.directions.length ? '继续发展方案' : '开始探索'}</button>}
            <a className="icon-button" aria-label="导出研究快照" href={`/api/projects/${id}/export`}><Download size={17}/></a>
          </div>
        </section>
        {!config.configured && <div className="config-notice"><Settings2 size={18}/><div>连接模型后即可开始探索。<span>在右上角运行设置中填写 API 地址、密钥和模型，保存后即可使用。</span></div></div>}
        <div className="workspace">
          <section className="directions-panel">
            <div className="section-heading"><h2>研究方向 <span>{project.directions.length.toString().padStart(2, '0')}</span></h2><button className="subtle" onClick={() => setModal('source')}><Plus size={15}/>导入材料</button></div>
            {project.directions.length ? project.directions.map((d, index) => <button key={d.id} onClick={() => {setSelected(d.id); setTab('overview');}} className={'direction-card ' + (selected === d.id ? 'selected' : '')}>
              <span className="card-index">方向 {(index + 1).toString().padStart(2, '0')}<span>{d.needs_update ? '待更新' : project.selections[d.id] === 'retained' ? '已保留' : project.selections[d.id] === 'parked' ? '已搁置' : '探索中'}</span></span>
              <h3>{d.title}</h3><p>{d.question}</p><span className="card-footer">展开研究方案 <ArrowRight size={15}/></span>
            </button>) : <div className="empty-directions"><Lightbulb size={28}/><h3>方向从这里生长</h3><p>导入已有材料，或直接开始探索。第一批构思形成后会在这里出现。</p></div>}
            {run && <div className="budget"><span>本轮进展</span><strong>{run.step} 个研究步骤</strong><div>{run.calls} / {run.budget.max_calls} 次模型调用</div><div>{run.tokens.toLocaleString()} / {run.budget.max_tokens.toLocaleString()} tokens{run.usage_estimated ? '（含预估）' : ''}</div>{run.reason && <p>{run.reason}</p>}</div>}
          </section>
          <section className="research-panel">
            <div className="tabs" role="tablist" aria-label="研究视图">{[['overview','研究方案'],['mechanism','方法结构'],['compare','已有工作'],['sources',`资料 · ${project.sources.length}`],['memory','经验'],['history','历史']].map(([key,label]) => <button role="tab" aria-selected={tab === key} key={key} onClick={() => {setTab(key); if (key === 'history') act(async () => setHistory(await api(`/projects/${id}/history`)));}}>{label}</button>)}</div>
            <div className="research-content">
              {direction && ['overview','mechanism','compare'].includes(tab) && <div className="detail-heading"><div><span className="eyebrow">RESEARCH DIRECTION</span><h2>{direction.title}</h2></div><button className="subtle" disabled={busy} onClick={() => act(() => api(`/projects/${id}/directions/${direction.id}/selection`, {expected_revision: project.revision, selection: project.selections[direction.id] === 'retained' ? 'exploring' : 'retained'}))}><Check size={16}/>{project.selections[direction.id] === 'retained' ? '已保留' : '保留方向'}</button></div>}
              {direction?.needs_update && ['overview','mechanism','compare'].includes(tab) && <div className="pending">已收到纠正。这里保留上次方案，继续探索后将更新相关判断。</div>}
              {tab === 'overview' && (direction ? <>
                <div className="research-question"><span>核心问题</span><p>{direction.question}</p></div>
                <div className="quality-grid">{[['创新性', direction.innovation],['影响力', direction.impact],['可行性', direction.feasibility]].map(([label,text],i) => <section key={label}><span className="quality-index">0{i+1}</span><h3>{label}</h3><p>{text}</p></section>)}</div>
                <h3>贡献与依据</h3>{direction.claims.map((claim,i) => <div className="claim" key={i}><span className="tag">{claimStates[claim.status]}</span><p>{claim.text}</p>{claim.source_ids.map(sid => <SourceLink key={sid} source={project.sources.find(s => s.id === sid)} onClick={() => showSource(sid)}/>)}</div>)}
                <div className="next-step"><ArrowRight size={20}/><div><h3>下一步如何推进</h3><p>{direction.next_step}</p></div></div>
                {!!direction.unknowns.length && <details><summary>关键未知 · {direction.unknowns.length}</summary><ul>{direction.unknowns.map((u,i) => <li key={i}>{u}</li>)}</ul></details>}
              </> : <div className="empty-main"><div className="orbit"><Sparkles size={35}/></div><h2>{active ? '正在理解问题与已有基础' : '从研究问题走向优秀构思'}</h2><p>方案形成后，在这里查看创新贡献、影响潜力、实施路径和方法结构。</p><button className="secondary" onClick={() => setModal('source')}><BookOpen size={16}/>导入论文片段</button></div>)}
              {tab === 'mechanism' && (direction ? <MechanismView direction={direction}/> : <p className="muted">选择一个研究方向后查看方法。</p>)}
              {tab === 'compare' && (direction ? <>{direction.comparisons.length ? direction.comparisons.map((c,i) => <article className="comparison" key={i}><SourceLink source={project.sources.find(s => s.id === c.source_id)} onClick={() => showSource(c.source_id)}/><dl><dt>已有基础</dt><dd>{c.shared_foundation}</dd><dt>具体差异</dt><dd>{c.difference}</dd><dt>进一步的机会</dt><dd>{c.next_opportunity}</dd></dl></article>) : <p className="muted">尚未形成有来源的具体方法对照，可导入相关工作并继续探索。</p>}</> : <p className="muted">选择一个研究方向后查看对照。</p>)}
              {tab === 'sources' && <><div className="section-heading"><h3>研究材料</h3><button className="secondary" onClick={() => setModal('source')}><Plus size={16}/>导入</button></div>{source ? <article className="source-detail"><button className="subtle" onClick={() => setSourceId('')}>返回资料列表</button><h3>{source.title}</h3><span className="tag">{source.kind === 'abstract' ? '论文摘要' : '用户提供的片段'}</span><p className="muted">{source.locator}</p><p className="passage">{source.text}</p>{source.url && <a href={source.url} target="_blank" rel="noreferrer">打开原始来源 ↗</a>}</article> : project.sources.map(s => <button className="source-row" key={s.id} onClick={() => setSourceId(s.id)}><BookOpen size={18}/><span><strong>{s.title}</strong><small>{s.kind === 'abstract' ? 'arXiv 摘要' : s.locator}</small></span><ChevronRight size={16}/></button>)}{!project.sources.length && <p className="muted">可粘贴论文摘要、方法片段或研究笔记。联网探索也会补充 arXiv 摘要。</p>}</>}
              {tab === 'memory' && <><div className="section-heading"><h3>课题经验</h3><button className="secondary" onClick={() => setModal('memory')}><Plus size={16}/>记录经验</button></div><p className="muted">记录具体判断与适用条件，供本课题后续探索使用。</p>{project.memories.map(m => <article className="memory" key={m.id}><span className="tag">研究笔记</span><h3>{m.statement}</h3><p>适用条件：{m.conditions}</p></article>)}</>}
              {tab === 'history' && <><h3>研究版本</h3>{history.map(h => <details key={h.revision}><summary>版本 {h.revision} · {h.directions.length} 个方向 · {h.sources.length} 份材料</summary>{h.directions.map(d => <div key={d.id}><h4>{d.title}</h4><p>{d.question}</p><p>{d.innovation}</p></div>)}</details>)}</>}
            </div>
            <section className="activity" aria-label="探索进展"><div className="activity-label"><span className={active && run.status === 'running' ? 'pulse' : 'quiet-dot'}/>研究进展</div><div className="activity-events" aria-live="polite">{events.slice(-4).map(e => <p key={e.seq}><time>{new Date(e.created * 1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</time>{e.payload.summary}</p>)}{!events.length && <p>课题已准备就绪。</p>}</div></section>
            <form className="feedback" onSubmit={e => {e.preventDefault(); if (!feedback.trim()) return; act(async () => {await api(`/projects/${id}/feedback`, {text: feedback, kind, direction_id: scope === 'direction' && selected ? selected : null, expected_revision: project.revision}); setFeedback('');});}}>
              <label className="sr-only" htmlFor="feedback">研究反馈</label><textarea id="feedback" value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="补充想法、纠正方法理解，或提出下一步研究要求…" maxLength={4000}/>
              <div className="feedback-controls"><select aria-label="反馈类型" value={kind} onChange={e => setKind(e.target.value)}><option value="instruction">探索要求</option><option value="correction">事实纠正</option><option value="preference">研究偏好</option><option value="constraint">资源约束</option></select><select aria-label="反馈范围" value={scope} onChange={e => setScope(e.target.value)}><option value="direction">当前方向</option><option value="project">整个课题</option></select><button className="primary" disabled={busy || !feedback.trim()}><Send size={15}/>提交反馈</button></div>
            </form>
          </section>
        </div>
      </>}
    </main>

    {modal === 'project' && <Modal title="建立研究课题" close={() => setModal('')}><form onSubmit={submitCreate}><label>课题名称<input name="title" required maxLength={160} placeholder="例如：长视频理解中的信息保留" autoFocus/></label><label>希望探索的问题<textarea name="question" required minLength={5} maxLength={6000} rows={4} placeholder="你关注什么问题？已有怎样的想法或观察？"/></label><label>已有条件与偏好<textarea name="constraints" maxLength={3000} rows={2} placeholder="可用数据、计算资源、偏好的研究方式…"/></label><button className="primary" disabled={busy}>建立课题<ArrowRight size={16}/></button></form></Modal>}
    {modal === 'source' && <Modal title="导入研究材料" close={() => setModal('')}><form onSubmit={e => {e.preventDefault(); const data=Object.fromEntries(new FormData(e.currentTarget)); act(async () => {await api(`/projects/${id}/sources`, {...data, url: data.url || null}); setModal('');});}}><label>资料标题<input name="title" required maxLength={300}/></label><label>来源网址<input name="url" type="url" placeholder="https://arxiv.org/abs/…"/></label><label>所在位置<input name="locator" defaultValue="摘要" maxLength={300}/></label><label>原文或笔记<textarea name="text" required minLength={20} maxLength={20000} rows={7}/></label><p className="muted small">这里保存原文片段。网址仅作来源链接，不会自动抓取全文。</p><button className="primary" disabled={busy}>导入材料</button></form></Modal>}
    {modal === 'memory' && <Modal title="记录课题经验" close={() => setModal('')}><form onSubmit={e => {e.preventDefault(); const data=Object.fromEntries(new FormData(e.currentTarget)); act(async () => {await api(`/projects/${id}/memories`, data); setModal('');});}}><label>经验或判断<textarea name="statement" required minLength={5} maxLength={3000} rows={3}/></label><label>适用条件<textarea name="conditions" required maxLength={3000} rows={3}/></label><button className="primary" disabled={busy}>保存经验</button></form></Modal>}
    {modal === 'settings' && <Modal title="探索设置" close={() => setModal('')}><div className="settings-body">
      {configLoaded ? <ModelSettings config={config} save={async draft => {const saved = await api<ProviderConfig>('/config', draft); setConfig(saved); return saved;}}/> : <p>正在读取模型配置…</p>}
      </div></Modal>}
  </div>;
}
