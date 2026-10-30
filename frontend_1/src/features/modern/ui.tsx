import React from 'react';
import { clsx } from 'clsx';
import { Info, ArrowUp, ArrowDown } from 'lucide-react';

/**
 * Shared building blocks for the Modern experience.
 * Design language: soft gray canvas, solid white cards (24px radius),
 * hairline borders, one accent (brand orange), pill controls.
 */

export const MCard: React.FC<{ className?: string; children: React.ReactNode }> = ({
  className,
  children,
}) => (
  <div
    className={clsx(
      'bg-white dark:bg-[#12141a]/90 dark:backdrop-blur-xl border border-[#E8EAED] dark:border-white/[0.08] rounded-[24px]',
      'shadow-[0_1px_2px_rgba(16,24,40,0.05),0_16px_40px_-28px_rgba(16,24,40,0.22)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.4)]',
      className
    )}
  >
    {children}
  </div>
);

/**
 * Stat card in the "design #2" language: icon-in-circle + label header
 * row, one large value, and a delta pill with a comparison caption.
 * Used for every KPI/stat strip across the Modern experience.
 */
export const MStatCard: React.FC<{
  label: string;
  value: string;
  icon: React.ElementType;
  iconClass?: string;
  deltaPct?: number | null;
  deltaCaption?: string;
  subtext?: string;
  delay?: number;
}> = ({ label, value, icon: Icon, iconClass = 'bg-[#F2F4F7] dark:bg-white/[0.06] text-[#344054] dark:text-neutral-300', deltaPct, deltaCaption = 'vs previous 7 days', subtext, delay = 0 }) => (
  <MCard className="p-[22px]">
    <div className="anim-enter" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-3">
        <span className={clsx('w-11 h-11 rounded-full flex items-center justify-center shrink-0', iconClass)}>
          <Icon className="w-5 h-5" strokeWidth={1.9} />
        </span>
        <p className="text-[15px] font-semibold text-[#101828] dark:text-white flex-1 leading-snug">{label}</p>
        <Info className="w-[18px] h-[18px] text-[#C4CBD4] dark:text-neutral-500 shrink-0" />
      </div>
      <p className="text-[34px] leading-none font-extrabold tracking-tight text-[#101828] dark:text-white mt-4 tabular-nums">{value}</p>
      <div className="flex items-center gap-2 mt-3.5 min-h-[22px]">
        {deltaPct !== undefined && deltaPct !== null && isFinite(deltaPct) ? (
          <>
            <span
              className={clsx(
                'inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-bold',
                deltaPct >= 0 ? 'bg-[#E7F8EE] dark:bg-emerald-500/15 text-[#16A34A] dark:text-emerald-400' : 'bg-[#FDECEC] dark:bg-rose-500/15 text-[#DC2626] dark:text-rose-400'
              )}
            >
              {deltaPct >= 0 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
              {Math.abs(deltaPct).toFixed(0)}%
            </span>
            <span className="text-[13px] text-[#98A2B3] dark:text-neutral-400">{deltaCaption}</span>
          </>
        ) : (
          <span className="text-[13px] text-[#98A2B3] dark:text-neutral-400">{subtext || ''}</span>
        )}
      </div>
    </div>
  </MCard>
);

export const MPageHeader: React.FC<{
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}> = ({ title, subtitle, actions }) => (
  <div className="flex flex-wrap items-end justify-between gap-4 mb-6 anim-enter">
    <div>
      <h1 className="text-[26px] leading-tight font-bold tracking-tight text-[#101828] dark:text-white">{title}</h1>
      {subtitle && <p className="text-sm text-[#667085] dark:text-neutral-400 mt-1">{subtitle}</p>}
    </div>
    {actions && <div className="flex items-center gap-2.5 flex-wrap">{actions}</div>}
  </div>
);

export const primaryPill =
  'inline-flex items-center gap-2 h-10 px-5 rounded-full bg-[#101828] text-white text-[13px] font-semibold shadow-[0_1px_2px_rgba(16,24,40,0.25)] hover:bg-[#1D2939] transition-all active:scale-[0.98]';
export const whitePill =
  'inline-flex items-center gap-2 h-10 px-5 rounded-full bg-white dark:bg-white/[0.06] border border-[#E4E7EC] dark:border-white/[0.1] text-[#344054] dark:text-white text-[13px] font-semibold shadow-[0_1px_2px_rgba(16,24,40,0.05)] hover:bg-[#F9FAFB] dark:hover:bg-white/[0.1] transition-all active:scale-[0.98]';

const AVATAR_BG = [
  'bg-orange-100 text-orange-700',
  'bg-emerald-100 text-emerald-700',
  'bg-sky-100 text-sky-700',
  'bg-violet-100 text-violet-700',
  'bg-rose-100 text-rose-700',
  'bg-amber-100 text-amber-700',
];

export const Avatar: React.FC<{ name?: string | null; className?: string }> = ({
  name,
  className,
}) => {
  const label = (name || 'Unknown').trim();
  const initials = label
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('') || '?';
  const idx = label.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_BG.length;
  return (
    <div
      className={clsx(
        'rounded-full flex items-center justify-center font-semibold shrink-0 w-10 h-10 text-[13px]',
        AVATAR_BG[idx],
        className
      )}
      aria-hidden="true"
    >
      {initials}
    </div>
  );
};

type Tone = 'emerald' | 'rose' | 'amber' | 'sky' | 'slate' | 'violet';
const TONES: Record<Tone, string> = {
  emerald: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200/70 dark:border-emerald-500/20',
  rose: 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-200/70 dark:border-rose-500/20',
  amber: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200/70 dark:border-amber-500/20',
  sky: 'bg-sky-50 dark:bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-200/70 dark:border-sky-500/20',
  slate: 'bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-neutral-300 border-slate-200 dark:border-white/[0.1]',
  violet: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 border-violet-200/70 dark:border-violet-500/20',
};

export const Pill: React.FC<{ tone?: Tone; children: React.ReactNode; className?: string }> = ({
  tone = 'slate',
  children,
  className,
}) => (
  <span
    className={clsx(
      'inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[11px] font-semibold whitespace-nowrap',
      TONES[tone],
      className
    )}
  >
    {children}
  </span>
);

export function leadStatusMeta(status?: string | null): { label: string; tone: Tone } {
  switch ((status || '').toLowerCase()) {
    case 'interested':
      return { label: 'Interested', tone: 'emerald' };
    case 'qualified':
      return { label: 'Qualified', tone: 'violet' };
    case 'not_interested':
      return { label: 'Not Interested', tone: 'rose' };
    case 'closed':
      return { label: 'Closed', tone: 'slate' };
    case 'new':
      return { label: 'New', tone: 'amber' };
    default:
      return { label: (status || 'New').replace(/_/g, ' '), tone: 'sky' };
  }
}

export function callStateMeta(state?: string | null): { label: string; tone: Tone } {
  switch ((state || '').toUpperCase()) {
    case 'COMPLETED':
      return { label: 'Completed', tone: 'emerald' };
    case 'FAILED':
      return { label: 'Failed', tone: 'rose' };
    case 'BUSY':
      return { label: 'Busy', tone: 'amber' };
    case 'NO_ANSWER':
      return { label: 'No Answer', tone: 'slate' };
    case 'QUEUED':
      return { label: 'Queued', tone: 'sky' };
    case 'HANGUP':
      return { label: 'Hangup', tone: 'slate' };
    default:
      return { label: 'Live', tone: 'emerald' };
  }
}

export const ScoreBar: React.FC<{ value: number }> = ({ value }) => {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const color = v >= 70 ? 'bg-emerald-500' : v >= 40 ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-[#EEF1F4] overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all duration-700', color)} style={{ width: `${v}%` }} />
      </div>
      <span className="text-xs font-semibold text-[#344054] tabular-nums">{v}%</span>
    </div>
  );
};

/** Lead scores arrive as a 0–1 fraction from the API; normalize to 0–100. */
export function scorePct(raw?: number | null): number {
  const v = raw ?? 0;
  return v <= 1 ? v * 100 : v;
}

export function fmtDuration(totalSeconds?: number | null): string {
  const s = Math.max(0, Math.round(totalSeconds || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${String(r).padStart(2, '0')}s` : `${r}s`;
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (isNaN(then)) return '';
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

export const MEmpty: React.FC<{ title: string; text?: string }> = ({ title, text }) => (
  <div className="py-12 text-center">
    <p className="text-sm font-semibold text-[#344054] dark:text-neutral-300">{title}</p>
    {text && <p className="text-[13px] text-[#98A2B3] dark:text-neutral-400 mt-1">{text}</p>}
  </div>
);
