import { useState, type FormEvent } from 'react';

export type ProviderConfig = {
  configured: boolean; api_base: string; model: string; has_api_key: boolean;
  output_mode: string; token_parameter: string; max_output: number;
};
export type ProviderDraft = Omit<ProviderConfig, 'configured' | 'has_api_key'> & {api_key: string | null};

export function ModelSettings({config, save}: {
  config: ProviderConfig; save: (value: ProviderDraft) => Promise<ProviderConfig>;
}) {
  const [draft, setDraft] = useState<ProviderDraft>({...config, api_key: ''});
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const changedEndpoint = draft.api_base.replace(/\/+$/, '') !== config.api_base.replace(/\/+$/, '');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setPending(true); setError(''); setMessage('');
    try {
      const saved = await save({api_base: draft.api_base, api_key: draft.api_key?.trim() || null,
        model: draft.model, output_mode: draft.output_mode,
        token_parameter: draft.token_parameter, max_output: draft.max_output});
      setDraft({...saved, api_key: ''});
      setMessage('已保存，下一次模型调用立即使用新配置。');
    } catch (e) { setError(e instanceof Error ? e.message : '配置保存失败，请重试。'); }
    finally { setPending(false); }
  };
  return <form onSubmit={submit} aria-label="模型配置">
    <h3>模型服务</h3>
    <p className="muted small">保存后立即生效。当前调用继续完成，后续调用使用新配置。</p>
    <fieldset disabled={pending} className="provider-fields">
      <label>API 地址<input type="url" required value={draft.api_base} onChange={e => setDraft({...draft, api_base: e.target.value})} placeholder="https://your-provider.example/v1"/></label>
      <label>模型名称<input required maxLength={200} value={draft.model} onChange={e => setDraft({...draft, model: e.target.value})}/></label>
      <label>API 密钥<input type="password" autoComplete="new-password" required={!config.has_api_key || changedEndpoint} value={draft.api_key || ''} onChange={e => setDraft({...draft, api_key: e.target.value})} placeholder={config.has_api_key && !changedEndpoint ? '已保存；留空保留原密钥' : '填写该服务的密钥'}/></label>
      <p className="muted small">密钥仅保存在本机，不回显。更换 API 地址时需填写对应密钥。</p>
      <label>输出格式<select aria-label="输出格式" value={draft.output_mode} onChange={e => setDraft({...draft, output_mode: e.target.value})}><option value="json_object">JSON 对象（json_object）</option><option value="json_schema">结构化输出（json_schema）</option><option value="text">文本 JSON（text）</option></select></label>
      <label>输出额度参数<select aria-label="输出额度参数" value={draft.token_parameter} onChange={e => setDraft({...draft, token_parameter: e.target.value})}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
      <label>单次输出 Token 上限<input type="number" min={1000} max={8000} required value={draft.max_output} onChange={e => setDraft({...draft, max_output: Number(e.target.value)})}/></label>
      <button className="primary" disabled={pending}>{pending ? '正在保存…' : '保存模型配置'}</button>
    </fieldset>
    {message && <p role="status" className="config-success">{message}</p>}
    {error && <p role="alert" className="config-failure">{error}</p>}
  </form>;
}
