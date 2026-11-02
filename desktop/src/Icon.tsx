export type IconName = 'shield' | 'overview' | 'connections' | 'review' | 'timeline' | 'activity' |
  'research' | 'settings' | 'arrow' | 'plus' | 'check' | 'close' | 'search' | 'refresh' |
  'download' | 'sun' | 'moon' | 'chevron' | 'lock' | 'file' | 'alert' | 'external';

const paths: Record<IconName, string[]> = {
  shield: ['M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z', 'm8 12 3 3 5-6'],
  overview: ['M3 3h7v7H3z', 'M14 3h7v7h-7z', 'M3 14h7v7H3z', 'M14 14h7v7h-7z'],
  connections: ['M8 12H5a4 4 0 0 1 0-8h4a4 4 0 0 1 4 4v1', 'M16 12h3a4 4 0 0 1 0 8h-4a4 4 0 0 1-4-4v-1', 'm8 16 8-8'],
  review: ['M9 4H5v16h14V4h-4', 'M9 2h6v5H9z', 'm8 13 2 2 5-5', 'M8 18h8'],
  timeline: ['M4 3v18h17', 'm8 15 4-6 4 3 5-8'],
  activity: ['M3 12h4l3-8 4 16 3-8h4'],
  research: ['M9 3h6', 'M10 3v6L4 19a1.3 1.3 0 0 0 1 2h14a1.3 1.3 0 0 0 1-2L14 9V3', 'M8 14h8'],
  settings: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z', 'm10 3-1 3-3 1-3-1-2 4 2 2v3l-2 2 2 4 3-1 3 1 1 3h4l1-3 3-1 3 1 2-4-2-2v-3l2-2-2-4-3 1-3-1-1-3h-4Z'],
  arrow: ['M5 12h14', 'm13 6 6 6-6 6'], plus: ['M12 5v14', 'M5 12h14'],
  check: ['m5 12 4 4L19 6'], close: ['m6 6 12 12', 'M18 6 6 18'],
  search: ['M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z', 'm15 15 6 6'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M6 7a7 7 0 0 1 12-1l2 6', 'M18 17a7 7 0 0 1-12 1l-2-6'],
  download: ['M12 3v12', 'm7 10 5 5 5-5', 'M4 17v4h16v-4'],
  sun: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z', 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1'],
  moon: ['M20 15a9 9 0 0 1-11-11 9 9 0 1 0 11 11Z'],
  chevron: ['m9 5 7 7-7 7'], lock: ['M7 10V7a5 5 0 0 1 10 0v3', 'M5 10h14v11H5z', 'M12 14v3'],
  file: ['M5 3h9l5 5v13H5z', 'M14 3v6h5', 'M8 13h8m-8 4h6'],
  alert: ['m12 3 10 18H2L12 3Z', 'M12 9v5m0 3v1'],
  external: ['M14 3h7v7', 'm10 14 11-11', 'M10 3H3v18h18v-7'],
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths[name].map((path, index) => <path d={path} key={index} />)}
  </svg>;
}
