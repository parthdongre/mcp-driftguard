/** An installed config and a currently valid gateway binding are different states.
 * Keep recovery controls available when a profile or client config has drifted.
 */
export interface HarnessConnectionState {
  detected: boolean;
  installed: boolean;
  configured: boolean;
  attached: number;
}

export function harnessPresentation(client: HarnessConnectionState) {
  const connected = client.configured;
  const needsRepair = client.installed && !connected;
  const description = needsRepair
    ? 'Managed configuration needs repair — disconnect, then reconnect'
    : client.attached && !connected
      ? 'Existing MCP session still attached — restart the client'
      : client.attached
        ? 'MCP session attached'
        : connected
          ? 'Configured — open a new client session'
          : client.detected
            ? 'Detected on this device'
            : 'Not detected';
  return {
    connected,
    needsRepair,
    description,
    canConnect: !client.installed && client.detected,
    canDisconnect: client.installed,
    badge: connected ? (client.attached ? 'Connected' : 'Configured') : null,
  };
}
