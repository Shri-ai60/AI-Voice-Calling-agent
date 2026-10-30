import React, { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CalendarClock, AlertCircle, CalendarCheck2, CheckCircle2, ListChecks, Check, PhoneCall } from 'lucide-react';
import { followupsApi } from '../../services/api/followups';
import { useToast } from '../../app/providers/ToastProvider';
import { getErrorMessage } from '../../services/api/client';
import type { FollowupDocument } from '../../types/api';
import { MCard, MStatCard, MPageHeader, Pill } from './ui';

function dayBucket(iso: string): 'overdue' | 'today' | 'upcoming' {
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfTomorrow = startOfToday + 24 * 3600 * 1000;
  if (d.getTime() < startOfToday) return 'overdue';
  if (d.getTime() < startOfTomorrow) return 'today';
  return 'upcoming';
}

export const ModernFollowups: React.FC = () => {
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: followups = [], isLoading } = useQuery<FollowupDocument[]>({
    queryKey: ['followups'],
    queryFn: () => followupsApi.getFollowups({ limit: 200 }),
    refetchInterval: 5000,
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => followupsApi.updateFollowup(id, { status: 'completed' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['followups'] }),
  });

  const dispatchMutation = useMutation({
    mutationFn: () => followupsApi.dispatchDueFollowups(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['followups'] });
      if (data.placed_count > 0) {
        toast.success('Follow-up Calls Dispatched', `${data.placed_count} scheduled call(s) have been initiated!`);
      } else {
        toast.info('No Follow-ups Due', 'All scheduled follow-up calls are timed for later or completed.');
      }
    },
    onError: (err) => {
      toast.error('Dispatch failed', getErrorMessage(err));
    },
  });

  const callMutation = useMutation({
    mutationFn: (id: string) => followupsApi.callFollowup(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['followups'] });
      toast.success('Follow-up Call Initiated', `Connecting outbound call to ${data.phone_number}...`);
    },
    onError: (err) => {
      toast.error('Call failed', getErrorMessage(err));
    },
  });

  const groups = useMemo(() => {
    const open = followups.filter((f) => f.status === 'pending' || f.status === 'scheduled');
    const done = followups.filter((f) => f.status === 'completed');
    const by = (b: string) =>
      open
        .filter((f) => dayBucket(f.scheduled_at) === b)
        .sort((a, b2) => new Date(a.scheduled_at).getTime() - new Date(b2.scheduled_at).getTime());
    return { overdue: by('overdue'), today: by('today'), upcoming: by('upcoming'), done: done.length, open: open.length };
  }, [followups]);

  const dueCount = groups.overdue.length + groups.today.length;

  const stats = [
    { label: 'Open Follow-ups', value: groups.open.toLocaleString('en-IN'), icon: ListChecks, iconClass: 'bg-[#F2F4F7] text-[#344054]', subtext: 'waiting to be called' },
    { label: 'Overdue', value: groups.overdue.length.toLocaleString('en-IN'), icon: AlertCircle, iconClass: 'bg-[#FDECEC] text-[#DC2626]', subtext: 'past their scheduled time' },
    { label: 'Due Today', value: groups.today.length.toLocaleString('en-IN'), icon: CalendarClock, iconClass: 'bg-[#FFF1E6] text-[#EA580C]', subtext: 'scheduled for today' },
    { label: 'Completed', value: groups.done.toLocaleString('en-IN'), icon: CalendarCheck2, iconClass: 'bg-[#E7F8EE] text-[#16A34A]', subtext: 'follow-ups done' },
  ];

  const Section: React.FC<{ title: string; tone: 'rose' | 'amber' | 'sky'; items: FollowupDocument[] }> = ({ title, tone, items }) => {
    if (items.length === 0) return null;
    return (
      <div className="mb-6">
        <h3 className="text-[13px] font-bold uppercase tracking-wider text-[#98A2B3] mb-3">{title}</h3>
        <MCard className="overflow-hidden">
          <div className="divide-y divide-[#F1F2F4]">
            {items.map((f) => (
              <div key={f.followup_id} className="flex items-center gap-4 px-6 py-4 hover:bg-[#FAFAFB] transition-colors">
                <span
                  className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                    tone === 'rose' ? 'bg-[#FDECEC] text-[#DC2626]' : tone === 'amber' ? 'bg-[#FFF1E6] text-[#EA580C]' : 'bg-[#E6F4FE] text-[#0284C7]'
                  }`}
                >
                  <CalendarClock className="w-[18px] h-[18px]" strokeWidth={1.9} />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-[#101828] tabular-nums">{f.phone_number}</p>
                  <p className="text-xs text-[#98A2B3] truncate">{f.notes || 'Scheduled callback'}</p>
                </div>
                <span className="hidden sm:block text-[13px] font-semibold text-[#344054]">
                  {new Date(f.scheduled_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
                </span>
                <Pill tone={tone}>{title}</Pill>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => callMutation.mutate(f.followup_id)}
                    disabled={callMutation.isPending && callMutation.variables === f.followup_id}
                    title="Call Now"
                    aria-label="Call Now"
                    className="w-8 h-8 rounded-full bg-orange-600 hover:bg-orange-500 text-white flex items-center justify-center transition-all shadow-sm active:scale-95 cursor-pointer disabled:opacity-50 shrink-0"
                  >
                    {callMutation.isPending && callMutation.variables === f.followup_id ? (
                      <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                      <PhoneCall className="w-3.5 h-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => completeMutation.mutate(f.followup_id)}
                    className="inline-flex items-center gap-1 h-8 px-3 rounded-full bg-[#E7F8EE] text-[#16A34A] text-xs font-bold hover:bg-[#D3F2DF] transition-colors cursor-pointer"
                  >
                    <Check className="w-3.5 h-3.5" /> Done
                  </button>
                </div>
              </div>
            ))}
          </div>
        </MCard>
      </div>
    );
  };

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <MPageHeader
          title="Follow-ups"
          subtitle="Callbacks your agents promised — grouped by what needs attention first."
        />
        <button
          type="button"
          onClick={() => dispatchMutation.mutate()}
          disabled={dispatchMutation.isPending}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-orange-600 hover:bg-orange-500 text-white font-bold text-xs shadow-md transition-all active:scale-95 cursor-pointer disabled:opacity-50 self-start sm:self-auto"
        >
          <PhoneCall className="w-4 h-4" />
          <span>Start Follow-up Calls ({dueCount} Due)</span>
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-6">
        {stats.map((st, i) => (
          <MStatCard key={st.label} {...st} delay={i * 60} />
        ))}
      </div>

      {isLoading && <MCard className="p-8 text-center text-sm text-[#98A2B3]">Loading follow-ups…</MCard>}
      {!isLoading && groups.open === 0 && (
        <MCard className="p-8 text-center">
          <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
          <p className="text-sm font-semibold text-[#344054]">All caught up</p>
          <p className="text-[13px] text-[#98A2B3] mt-1">No open follow-ups right now.</p>
        </MCard>
      )}

      <Section title="Overdue" tone="rose" items={groups.overdue} />
      <Section title="Today" tone="amber" items={groups.today} />
      <Section title="Upcoming" tone="sky" items={groups.upcoming} />
    </div>
  );
};
