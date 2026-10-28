import type { ReactNode } from 'react';
import { Icon } from './Icon';

/** Native disclosure keeps mouse, keyboard and screen-reader behavior aligned. */
export function Disclosure({ title, children, className = '', defaultOpen = false, level = 3 }: {
  title: string; children: ReactNode; className?: string; defaultOpen?: boolean; level?: 2 | 3 | 4;
}) {
  const Heading = `h${level}` as 'h2' | 'h3' | 'h4';
  return <details className={`disclosure ${className}`} open={defaultOpen || undefined}>
    <summary><Heading>{title}</Heading><Icon name="chevron" size={16} /></summary>
    <div className="disclosure-body">{children}</div>
  </details>;
}
