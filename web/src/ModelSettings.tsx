import { useState, type FormEvent } from 'react';

type Model = {id: string; api_base: string; model: string; has_api_key: boolean};
type Assignments = {exploration: string; literature: string; review: string};
export type ProviderConfig = {configured: boolean; model: string; models: Model[]; assignments: Assignments};
export type ProviderDraft = {models: (Omit<Model, 'has_api_key'> & {api_key: string | null})[]; assignments: Assignments};
const roles = {exploration: '研究探索', literature: '文献分析', review: '方案审查'};
const toDraft = (config: ProviderConfig): ProviderDraft => ({
  models: config.models.map(m => ({id: m.id, api_base: m.api_base, model: m.model, api_key: ''})),
  assignments: {...config.assignments},
});

export function ModelSettings({config, save}: {
  config: ProviderConfig; save: (value: ProviderDraft) => Promise<ProviderConfig>;
}) {
  const [draft, setDraft] = useState(() => toDraft(config));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const update = (id: string, field: 'api_base'|'api_key'|'model', value: string) => {
    setDraft(d => ({...d, models: d.models.map(m => m.id === id ? {...m, [field]: value} : m)}));
    setMessage('');
  };
  const remove = (id: string) => setDraft(d => ({
    models: d.models.filter(m => m.id !== id),
    assignments: Object.fromEntries(Object.entries(d.assignments).map(([task, mid]) =>
      [task, mid === id ? d.models[0].id : mid])) as Assignments,
  }));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setPending(true); setError(''); setMessage('');
    try {
      const saved = await save({...draft, models: draft.models.map(m => ({...m, api_key: m.api_key?.trim() || null}))});
      setDraft(toDraft(saved));
      setMessage('已保存，后续任务使用新的模型配置与分工。');
    } catch (e) { setError(e instanceof Error ? e.message : '配置保存失败，请重试。'); }
    finally { setPending(false); }
  };
  return <form onSubmit={submit} aria-label="模型配置">
    <p className="muted small">填入一个模型即可开始。保存后立即生效，当前调用会继续完成。</p>
    <fieldset disabled={pending} className="provider-fields">
      {draft.models.map((m, index) => {
        const saved = config.models.find(old => old.id === m.id);
        const keepKey = saved?.has_api_key && saved.api_base.replace(/\/+$/, '') === m.api_base.replace(/\/+$/, '');
        return <section className="model-entry" key={m.id} aria-label={index === 0 ? '默认模型' : `模型 ${index + 1}`}>
          <div className="section-heading"><h3>{index === 0 ? '默认模型' : `模型 ${index + 1}`}</h3>
            {index > 0 && <button type="button" className="subtle" onClick={() => remove(m.id)}>移除</button>}</div>
          <label>API URL<input type="url" required value={m.api_base} onChange={e => update(m.id, 'api_base', e.target.value)} placeholder="https://your-provider.example/v1"/></label>
          <label>API Key<input type="password" autoComplete="new-password" required={!keepKey} value={m.api_key || ''} onChange={e => update(m.id, 'api_key', e.target.value)} placeholder={keepKey ? '已保存；留空保留原密钥' : '填写该服务的密钥'}/></label>
          <label>模型名<input required maxLength={200} value={m.model} onChange={e => update(m.id, 'model', e.target.value)} placeholder="服务商提供的模型名称"/></label>
        </section>;
      })}
      <button type="button" className="secondary" onClick={() => {setMessage(''); setDraft(d => ({...d,
        models: [...d.models, {id: crypto.randomUUID(), api_base: '', api_key: '', model: ''}]}));}}>添加模型</button>
      {draft.models.length > 1 && <section className="task-assignments"><h3>任务分工</h3><p className="muted small">可以让不同模型负责不同环节，也可以共用一个模型。</p>
        {(Object.keys(roles) as (keyof Assignments)[]).map(task => <label key={task}>{roles[task]}
          <select aria-label={roles[task]} value={draft.assignments[task]} onChange={e => {setMessage(''); setDraft(d => ({...d, assignments: {...d.assignments, [task]: e.target.value}}));}}>
            {draft.models.map((m, i) => <option key={m.id} value={m.id}>{i === 0 ? '默认模型' : `模型 ${i + 1}`} · {m.model || '待填写'}</option>)}
          </select></label>)}
      </section>}
      <p className="muted small">密钥仅保存在本机，不回显。更换 API URL 时需填写对应密钥。</p>
      <button className="primary" disabled={pending}>{pending ? '正在保存…' : '保存模型配置'}</button>
    </fieldset>
    {message && <p role="status" className="config-success">{message}</p>}
    {error && <p role="alert" className="config-failure">{error}</p>}
  </form>;
}
