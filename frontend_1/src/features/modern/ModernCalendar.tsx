import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight, PhoneCall, Target, CalendarClock, CalendarDays, ExternalLink } from 'lucide-react';
import { calendarApi } from '../../services/api/calendar';
import { agentsApi } from '../../services/api/agents';
import { MCard, MPageHeader, Pill, callStateMeta, leadStatusMeta, fmtDuration, scorePct } from './ui';
import { clsx } from 'clsx';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function isoOf(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function timeOf(iso?: string | null): string {
  if (!iso) return '';
  try {
    const clean = iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`;
    const d = new Date(clean);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  } catch {
    return '';
  }
}

export const ModernCalendar: React.FC = () => {
  const navigate = useNavigate();
  const today = useMemo(() => new Date(), []);
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [selected, setSelected] = useState<string>(() => isoOf(today));

  const year = cursor.getFullYear();
  const month = cursor.getMonth() + 1;

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['calendar-summary', year, month],
    queryFn: () => calendarApi.getSummary(year, month),
  });

  const { data: day, isLoading: dayLoading } = useQuery({
    queryKey: ['calendar-day', selected],
    queryFn: () => calendarApi.getDay(selected),
  });

  const { data: agents = [] } = useQuery({ queryKey: ['agents'], queryFn: () => agentsApi.getAgents(50) });
  const agentName = useMemo(() => new Map(agents.map((a) => [a.agent_id, a.name])), [agents]);

  // 6-week grid starting on the Monday of the week containing the 1st.
  const cells = useMemo(() => {
    const first = new Date(year, month - 1, 1);
    const startOffset = (first.getDay() + 6) % 7; // Monday-first
    const start = new Date(year, month - 1, 1 - startOffset);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const iso = isoOf(d);
      const counts = summary?.days ? summary.days[iso] : undefined;
      return { date: d, iso, inMonth: d.getMonth() === month - 1, counts };
    });
  }, [cursor, summary, year, month]);

  const moveMonth = (delta: number) => {
    const next = new Date(year, month - 1 + delta, 1);
    setCursor(next);
    setSelected(isoOf(next));
  };

  const monthLabel = cursor.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });

  const selectedLabel = useMemo(() => {
    try {
      const parts = selected.split('-');
      if (parts.length === 3) {
        const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        return d.toLocaleDateString('en-IN', {
          weekday: 'long',
          day: 'numeric',
          month: 'long',
          year: 'numeric',
        });
      }
    } catch {}
    return selected;
  }, [selected]);

  const calls = day?.calls || [];
  const leads = day?.leads || [];
  const followups = day?.followups || [];

  return (
    <div>
      <MPageHeader
        title="Calendar"
        subtitle="What happened on any date — calls made, leads captured, and follow-ups due."
        actions={
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => moveMonth(-1)}
              className="w-10 h-10 rounded-full bg-white dark:bg-white/[0.06] border border-[#E4E7EC] dark:border-white/[0.1] flex items-center justify-center text-[#344054] dark:text-neutral-200 hover:bg-[#F9FAFB] dark:hover:bg-white/[0.1] transition-colors"
              aria-label="Previous month"
            >
              <ChevronLeft className="w-4.5 h-4.5" />
            </button>
            <button
              type="button"
              onClick={() => {
                setCursor(new Date(today.getFullYear(), today.getMonth(), 1));
                setSelected(isoOf(today));
              }}
              className="h-10 px-4 rounded-full bg-white dark:bg-white/[0.06] border border-[#E4E7EC] dark:border-white/[0.1] text-[13px] font-bold text-[#344054] dark:text-neutral-200 hover:bg-[#F9FAFB] dark:hover:bg-white/[0.1] transition-colors"
            >
              Today
            </button>
            <button
              type="button"
              onClick={() => moveMonth(1)}
              className="w-10 h-10 rounded-full bg-white dark:bg-white/[0.06] border border-[#E4E7EC] dark:border-white/[0.1] flex items-center justify-center text-[#344054] dark:text-neutral-200 hover:bg-[#F9FAFB] dark:hover:bg-white/[0.1] transition-colors"
              aria-label="Next month"
            >
              <ChevronRight className="w-4.5 h-4.5" />
            </button>
          </div>
        }
      />

      <MCard className="overflow-hidden mb-6">
        <div className="px-6 pt-5 pb-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="w-9 h-9 rounded-xl bg-orange-50 dark:bg-orange-500/15 border border-orange-100 dark:border-orange-500/30 flex items-center justify-center">
              <CalendarDays className="w-[18px] h-[18px] text-orange-600 dark:text-orange-400" strokeWidth={1.9} />
            </span>
            <h3 className="text-[17px] font-extrabold tracking-tight text-[#101828] dark:text-white">{monthLabel}</h3>
          </div>
          {summaryLoading && (
            <span className="text-xs text-[#98A2B3] dark:text-neutral-400">Loading monthly activity…</span>
          )}
        </div>
        <div className="grid grid-cols-7 border-t border-[#F1F2F4] dark:border-white/[0.08]">
          {WEEKDAYS.map((w) => (
            <div key={w} className="px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-[#98A2B3] dark:text-neutral-400 border-b border-[#F1F2F4] dark:border-white/[0.08]">
              {w}
            </div>
          ))}
          {cells.map((cell) => {
            const isToday = cell.iso === isoOf(today);
            const isSelected = cell.iso === selected;
            const c = cell.counts;
            return (
              <button
                key={cell.iso}
                type="button"
                onClick={() => {
                  setSelected(cell.iso);
                  if (!cell.inMonth) {
                    setCursor(new Date(cell.date.getFullYear(), cell.date.getMonth(), 1));
                  }
                }}
                className={clsx(
                  'h-[104px] p-2.5 text-left align-top border-b border-r border-[#F5F6F7] dark:border-white/[0.07] transition-colors [&:nth-child(7n)]:border-r-0',
                  cell.inMonth
                    ? 'bg-white dark:bg-transparent hover:bg-[#FAFAFB] dark:hover:bg-white/[0.04]'
                    : 'bg-[#FBFBFC] dark:bg-white/[0.02]',
                  isSelected && 'bg-orange-50/60 dark:bg-orange-500/15 hover:bg-orange-50/60 dark:hover:bg-orange-500/20'
                )}
              >
                <span
                  className={clsx(
                    'inline-flex w-7 h-7 items-center justify-center rounded-full text-[13px] font-bold tabular-nums',
                    isToday
                      ? 'bg-orange-500 text-white font-black shadow-md ring-2 ring-orange-500/30'
                      : cell.inMonth
                      ? 'text-[#344054] dark:text-neutral-200'
                      : 'text-[#C4CBD4] dark:text-neutral-600',
                    isSelected && !isToday && 'ring-2 ring-orange-400 text-orange-600 dark:text-orange-400 font-extrabold'
                  )}
                >
                  {cell.date.getDate()}
                </span>
                {c && (c.calls > 0 || c.leads > 0 || c.followups > 0) && (
                  <span className="mt-1.5 space-y-1 block">
                    {c.calls > 0 && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-[#667085] dark:text-neutral-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-orange-500 shrink-0" />
                        {c.calls} call{c.calls === 1 ? '' : 's'}
                      </span>
                    )}
                    {c.leads > 0 && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-[#667085] dark:text-neutral-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                        {c.leads} lead{c.leads === 1 ? '' : 's'}
                      </span>
                    )}
                    {c.followups > 0 && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-[#667085] dark:text-neutral-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-violet-500 shrink-0" />
                        {c.followups} due
                      </span>
                    )}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </MCard>

      <h3 className="text-[16px] font-extrabold tracking-tight text-[#101828] dark:text-white mb-3">{selectedLabel}</h3>
      {dayLoading && <MCard className="p-8 text-center text-sm text-[#98A2B3] dark:text-neutral-400">Loading date activity…</MCard>}
      {!dayLoading && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <MCard className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <PhoneCall className="w-4 h-4 text-orange-600 dark:text-orange-400" />
                <h4 className="text-sm font-bold text-[#101828] dark:text-white">Calls ({calls.length})</h4>
              </div>
              {calls.length > 0 && (
                <button
                  type="button"
                  onClick={() => navigate('/calls')}
                  className="text-[11px] font-semibold text-orange-600 dark:text-orange-400 hover:text-orange-500 flex items-center gap-0.5"
                >
                  All Calls <ExternalLink className="w-3 h-3" />
                </button>
              )}
            </div>
            <div className="space-y-3">
              {calls.length === 0 && <p className="text-[13px] text-[#98A2B3] dark:text-neutral-400">No calls on this date.</p>}
              {calls.slice(0, 10).map((c) => {
                const meta = callStateMeta(c.state);
                return (
                  <div
                    key={c.call_id}
                    onClick={() => navigate('/calls')}
                    className="flex items-center gap-2.5 p-2 rounded-xl hover:bg-[#F9FAFB] dark:hover:bg-white/[0.04] cursor-pointer transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-bold text-[#101828] dark:text-white tabular-nums truncate">{c.phone_number}</p>
                      <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 truncate">
                        {timeOf(c.created_at)} · {(c.agent_id && agentName.get(c.agent_id)) || 'AI Agent'} · {fmtDuration(c.duration)}
                      </p>
                    </div>
                    <Pill tone={meta.tone}>{meta.label}</Pill>
                  </div>
                );
              })}
              {calls.length > 10 && (
                <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 pt-1 text-center">+ {calls.length - 10} more calls in history</p>
              )}
            </div>
          </MCard>

          <MCard className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Target className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <h4 className="text-sm font-bold text-[#101828] dark:text-white">Leads ({leads.length})</h4>
              </div>
              {leads.length > 0 && (
                <button
                  type="button"
                  onClick={() => navigate('/leads')}
                  className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 hover:text-emerald-500 flex items-center gap-0.5"
                >
                  All Leads <ExternalLink className="w-3 h-3" />
                </button>
              )}
            </div>
            <div className="space-y-3">
              {leads.length === 0 && <p className="text-[13px] text-[#98A2B3] dark:text-neutral-400">No leads captured on this date.</p>}
              {leads.slice(0, 10).map((l) => {
                const meta = leadStatusMeta(l.status || 'new');
                return (
                  <div
                    key={l.lead_id}
                    onClick={() => navigate('/leads')}
                    className="flex items-center gap-2.5 p-2 rounded-xl hover:bg-[#F9FAFB] dark:hover:bg-white/[0.04] cursor-pointer transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-bold text-[#101828] dark:text-white truncate">{l.name || 'Interested caller'}</p>
                      <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 tabular-nums truncate">
                        {l.phone_number} · score {Math.round(scorePct(l.score))}
                      </p>
                    </div>
                    <Pill tone={meta.tone}>{meta.label}</Pill>
                  </div>
                );
              })}
              {leads.length > 10 && (
                <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 pt-1 text-center">+ {leads.length - 10} more leads captured</p>
              )}
            </div>
          </MCard>

          <MCard className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <CalendarClock className="w-4 h-4 text-violet-600 dark:text-violet-400" />
                <h4 className="text-sm font-bold text-[#101828] dark:text-white">Follow-ups due ({followups.length})</h4>
              </div>
              {followups.length > 0 && (
                <button
                  type="button"
                  onClick={() => navigate('/followups')}
                  className="text-[11px] font-semibold text-violet-600 dark:text-violet-400 hover:text-violet-500 flex items-center gap-0.5"
                >
                  All Follow-ups <ExternalLink className="w-3 h-3" />
                </button>
              )}
            </div>
            <div className="space-y-3">
              {followups.length === 0 && <p className="text-[13px] text-[#98A2B3] dark:text-neutral-400">No follow-ups due on this date.</p>}
              {followups.slice(0, 10).map((f) => (
                <div
                  key={f.followup_id}
                  onClick={() => navigate('/followups')}
                  className="flex items-center gap-2.5 p-2 rounded-xl hover:bg-[#F9FAFB] dark:hover:bg-white/[0.04] cursor-pointer transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-bold text-[#101828] dark:text-white tabular-nums truncate">{f.phone_number}</p>
                    <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 truncate">
                      {timeOf(f.scheduled_at)} · {f.notes || 'Scheduled callback'}
                    </p>
                  </div>
                  <Pill tone={f.status === 'completed' ? 'emerald' : f.status === 'cancelled' ? 'rose' : 'amber'}>
                    {f.status === 'completed' ? 'Done' : f.status === 'cancelled' ? 'Cancelled' : 'Pending'}
                  </Pill>
                </div>
              ))}
              {followups.length > 10 && (
                <p className="text-[11px] text-[#98A2B3] dark:text-neutral-400 pt-1 text-center">+ {followups.length - 10} more follow-ups scheduled</p>
              )}
            </div>
          </MCard>
        </div>
      )}
    </div>
  );
};
