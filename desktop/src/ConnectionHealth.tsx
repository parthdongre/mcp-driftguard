import { useEffect, useState } from 'react';
import { request } from './bridge';
import type { Overview } from './types';
import { formatTime } from './review-utils';
import { Disclosure } from './Disclosure';

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
  return <section className="panel connection-setup"><Disclosure title="Gateway process activity" level={2}><p>Recent local heartbeats show process activity. They do not verify client routing or upstream behavior.</p>
    {!native ? <p className="small muted">Open the native app to inspect local gateway activity.</p> : unavailable ? <p role="status">Activity could not be refreshed. Treat the connection state as unknown.</p> : health.length ? health.map(item => {
      const age = checked - Date.parse(item.heartbeat_at);
      const recent = !!item.active && age >= 0 && age <= 15000;
      return <Disclosure title={item.server_id} key={item.server_id}><p>Last heartbeat {formatTime(item.heartbeat_at)}</p><span className={`badge ${recent ? 'positive' : ''}`}>{recent ? 'Recent heartbeat' : item.active ? 'Heartbeat stale' : 'Gateway stopped'}</span></Disclosure>;
    }) : <p className="small muted">No gateway process has reported activity. Configure your MCP client to start one.</p>}
  </Disclosure></section>;
}
