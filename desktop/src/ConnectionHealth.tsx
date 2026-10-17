import { useEffect, useState } from 'react';
import { request } from './bridge';
import type { Overview } from './types';
import { formatTime } from './review-utils';

export function ConnectionHealth({ native }: { native: boolean }) {
  const [health, setHealth] = useState<NonNullable<Overview['gateway_health']>>([]);
  const [checked, setChecked] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const overview = await request<Overview>({ action: 'overview' });
        if (active) { setHealth(overview.gateway_health ?? []); setChecked(Date.now()); setUnavailable(false); }
      } catch { if (active) setUnavailable(true); }
      if (active) timer = setTimeout(() => void poll(), 5000);
    };
    if (native) void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [native]);
  return <section className="panel connection-setup"><div className="section-heading"><div><h2>Gateway process activity</h2><p>Recent local heartbeats show process activity. They do not verify client routing or upstream behavior.</p></div></div>
    {!native ? <p className="small muted">Open the native app to inspect local gateway activity.</p> : unavailable ? <p role="status">Activity could not be refreshed. Treat the connection state as unknown.</p> : health.length ? health.map(item => {
      const age = checked - Date.parse(item.heartbeat_at);
      const recent = !!item.active && age >= 0 && age <= 15000;
      return <div className="setting-row" key={item.server_id}><div><strong>{item.server_id}</strong><p>Last heartbeat {formatTime(item.heartbeat_at)}</p></div><span className={`badge ${recent ? 'positive' : ''}`}>{recent ? 'Recent heartbeat' : item.active ? 'Heartbeat stale' : 'Gateway stopped'}</span></div>;
    }) : <p className="small muted">No gateway process has reported activity. Configure your MCP client to start one.</p>}
  </section>;
}
