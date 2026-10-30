import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  PhoneCall,
  Target,
  Heart,
  Clock,
  Download,
  Plus,
  ArrowRight,
  CalendarClock,
  BarChart3,
  Building2,
} from 'lucide-react';
import { statsApi } from '../../services/api/stats';
import { leadsApi } from '../../services/api/leads';
import { agentsApi } from '../../services/api/agents';
import { callsApi } from '../../services/api/calls';
import type { CallDocument, LeadDocument } from '../../types/api';
import { MCard, MStatCard, Avatar, Pill, ScoreBar, scorePct, leadStatusMeta, fmtDuration, timeAgo, primaryPill, whitePill } from './ui';

/* ---------- date bucketing helpers ---------- */
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function lastNDays(n: number): { key: string; label: string }[] {
  const out: { key: string; label: string }[] = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    out.push({
      key: dayKey(d),
      label: d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
    });
  }
  return out;
}

function bucketize<T extends { created_at: string }>(items: T[], days: { key: string; label: string }[]) {
  const counts = new Map(days.map((d) => [d.key, 0]));
  for (const it of items) {
    const k = dayKey(new Date(it.created_at));
    if (counts.has(k)) counts.set(k, (counts.get(k) || 0) + 1);
  }
  return days.map((d) => counts.get(d.key) || 0);
}

/* ---------- small building blocks ---------- */
function pctChange(series: number[]): number | null {
  const n = series.length;
  const cur = series.slice(n - 7).reduce((a, b) => a + b, 0);
  const prev = series.slice(n - 14, n - 7).reduce((a, b) => a + b, 0);
  if (prev === 0) return cur > 0 ? 100 : null;
  return ((cur - prev) / prev) * 100;
}

/* ---------- page ---------- */
export const ModernDashboard: React.FC = () => {
  const navigate = useNavigate();

  const { data: stats } = useQuery({ queryKey: ['global-stats'], queryFn: statsApi.getStats, refetchInterval: 15000 });
  const { data: leads = [] } = useQuery<LeadDocument[]>({
    queryKey: ['leads'],
    queryFn: () => leadsApi.getLeads({ limit: 500 }),
    refetchInterval: 15000,
  });
  const { data: agents = [] } = useQuery({ queryKey: ['agents'], queryFn: () => agentsApi.getAgents(50) });
  const { data: calls = [] } = useQuery<CallDocument[]>({
    queryKey: ['modern-calls'],
    queryFn: () => callsApi.getCalls({ limit: 200 }),
    refetchInterval: 15000,
  });

  const days = useMemo(() => lastNDays(14), []);
  const callsPerDay = useMemo(() => bucketize(calls, days), [calls, days]);
  const leadsPerDay = useMemo(() => bucketize(leads, days), [leads, days]);
  const activity = days.map((d, i) => ({ ...d, Calls: callsPerDay[i], Leads: leadsPerDay[i] }));

  const interested = leads.filter((l) => ['interested', 'qualified'].includes((l.status || '').toLowerCase())).length;
  const interestedRate = leads.length ? Math.round((interested / leads.length) * 100) : 0;

  const outcomeData = [
    { name: 'Completed', value: stats?.completed || 0, color: '#10B981' },
    { name: 'Failed', value: stats?.failed || 0, color: '#F43F5E' },
    { name: 'Busy', value: stats?.busy || 0, color: '#F59E0B' },
    { name: 'No answer', value: stats?.no_answer || 0, color: '#C4CBD4' },
  ];
  const outcomeTotal = outcomeData.reduce((a, b) => a + b.value, 0);

  const callsByAgent = useMemo(() => {
    const map = new Map<string, number>();
    for (const c of calls) if (c.agent_id) map.set(c.agent_id, (map.get(c.agent_id) || 0) + 1);
    return map;
  }, [calls]);
  const topAgents = [...agents]
    .map((a) => ({ agent: a, count: callsByAgent.get(a.agent_id) || 0 }))
    .sort((x, y) => y.count - x.count)
    .slice(0, 5);
  const maxAgentCalls = Math.max(1, ...topAgents.map((t) => t.count));

  const latestLeads = [...leads]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 6);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  const kpis = [
    {
      label: 'Total Calls',
      value: (stats?.total_calls ?? calls.length).toLocaleString('en-IN'),
      icon: PhoneCall,
      iconClass: 'bg-[#FFF1E6] text-[#EA580C]',
      deltaPct: pctChange(callsPerDay),
    },
    {
      label: 'Leads Captured',
      value: leads.length.toLocaleString('en-IN'),
      icon: Target,
      iconClass: 'bg-[#E7F8EE] text-[#16A34A]',
      deltaPct: pctChange(leadsPerDay),
    },
    {
      label: 'Interested Rate',
      value: `${interestedRate}%`,
      icon: Heart,
      iconClass: 'bg-[#F1EAFE] text-[#7C3AED]',
      subtext: `${interested} of ${leads.length} leads`,
    },
    {
      label: 'Avg. Call Duration',
      value: fmtDuration(stats?.average_duration_seconds),
      icon: Clock,
      iconClass: 'bg-[#E6F4FE] text-[#0284C7]',
      subtext: 'per completed call',
    },
  ];

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6 anim-enter">
        <div>
          <p className="text-[13px] font-semibold text-orange-600">
            {greeting} · {today}
          </p>
          <h1 className="text-[26px] leading-tight font-bold tracking-tight text-[#101828] mt-0.5">
            Dashboard Overview
          </h1>
          <p className="text-sm text-[#667085] mt-1">Here's what's happening with your calling operations today.</p>
        </div>
        <div className="flex items-center gap-2.5">
          <button type="button" className={whitePill} onClick={() => leadsApi.downloadLeadsExcel().catch(() => {})}>
            <Download className="w-4 h-4" /> Export Leads
          </button>
<button type="button" className={primaryPill} onClick={() => navigate('/calls')}>
            <PhoneCall className="w-4 h-4" /> View Calls
          </button>
        </div>
      </div>

      {/* KPI cards (design #2: icon + label header, big value, delta pill) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-6">
        {kpis.map((k, i) => (
          <MStatCard key={k.label} {...k} delay={i * 70} />
        ))}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
        <MCard className="p-6 xl:col-span-2">
          <div className="anim-enter" style={{ animationDelay: '120ms' }}>
            <div className="flex items-start justify-between mb-1">
              <div>
                <h3 className="text-[15px] font-bold text-[#101828]">Call Activity</h3>
                <p className="text-xs text-[#98A2B3] mt-0.5">Calls placed and leads captured · last 14 days</p>
              </div>
              <div className="flex items-center gap-4 text-xs font-medium text-[#667085]">
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#F97316]" /> Calls</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#10B981]" /> Leads</span>
              </div>
            </div>
            <div className="h-[260px] mt-3">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={activity} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
                  <defs>
                    <linearGradient id="actCalls" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#F97316" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="#F97316" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="actLeads" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#10B981" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#10B981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#EEF0F2" />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#98A2B3' }} axisLine={false} tickLine={false} dy={6} interval={1} />
                  <YAxis tick={{ fontSize: 11, fill: '#98A2B3' }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: '#fff', border: '1px solid #E8EAED', borderRadius: 14, fontSize: 12, boxShadow: '0 12px 32px -12px rgba(16,24,40,0.25)' }}
                    labelStyle={{ fontWeight: 700, color: '#101828' }}
                  />
                  <Area type="monotone" dataKey="Calls" stroke="#F97316" strokeWidth={2.5} fill="url(#actCalls)" />
                  <Area type="monotone" dataKey="Leads" stroke="#10B981" strokeWidth={2.5} fill="url(#actLeads)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </MCard>

        <MCard className="p-6">
          <div className="anim-enter" style={{ animationDelay: '190ms' }}>
            <h3 className="text-[15px] font-bold text-[#101828]">Call Outcomes</h3>
            <p className="text-xs text-[#98A2B3] mt-0.5">How calls are ending</p>
            <div className="relative w-[168px] h-[168px] mx-auto my-4">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={outcomeTotal > 0 ? outcomeData.filter((d) => d.value > 0) : [{ name: 'None', value: 1, color: '#EDF0F3' }]}
                    innerRadius={58}
                    outerRadius={80}
                    paddingAngle={outcomeTotal > 0 ? 3 : 0}
                    cornerRadius={6}
                    stroke="transparent"
                    dataKey="value"
                    isAnimationActive={false}
                  >
                    {(outcomeTotal > 0 ? outcomeData.filter((d) => d.value > 0) : [{ color: '#EDF0F3' }]).map((d, i) => (
                      <Cell key={i} fill={d.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-[26px] font-bold text-[#101828] leading-none tabular-nums">{outcomeTotal.toLocaleString('en-IN')}</span>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-[#98A2B3] mt-1">Total calls</span>
              </div>
            </div>
            <div className="space-y-2.5">
              {outcomeData.map((d) => (
                <div key={d.name} className="flex items-center gap-2.5 text-[13px]">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: d.color }} />
                  <span className="text-[#667085] font-medium flex-1">{d.name}</span>
                  <span className="font-bold text-[#101828] tabular-nums">{d.value.toLocaleString('en-IN')}</span>
                  <span className="text-[#98A2B3] tabular-nums w-10 text-right">
                    {outcomeTotal ? `${Math.round((d.value / outcomeTotal) * 100)}%` : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </MCard>
      </div>

      {/* Agents + latest leads */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
        <MCard className="p-6">
          <div className="anim-enter" style={{ animationDelay: '240ms' }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-bold text-[#101828]">Top Agents</h3>
              <button type="button" onClick={() => navigate('/agents')} className="text-xs font-semibold text-orange-600 hover:text-orange-500 inline-flex items-center gap-1">
                View all <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="space-y-4">
              {topAgents.length === 0 && <p className="text-[13px] text-[#98A2B3]">No agents yet. Create your first AI agent to start calling.</p>}
              {topAgents.map(({ agent, count }) => (
                <div key={agent.agent_id} className="flex items-center gap-3">
                  <Avatar name={agent.name} className="w-9 h-9 text-xs" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-[13px] font-semibold text-[#101828] truncate">{agent.name}</p>
                      <span className={`w-1.5 h-1.5 rounded-full ${agent.is_enabled ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                    </div>
                    <div className="h-1.5 rounded-full bg-[#EEF1F4] mt-1.5 overflow-hidden">
                      <div className="h-full rounded-full bg-gradient-to-r from-orange-500 to-amber-400 transition-all duration-700" style={{ width: `${Math.round((count / maxAgentCalls) * 100)}%` }} />
                    </div>
                  </div>
                  <span className="text-[13px] font-bold text-[#101828] tabular-nums">{count}<span className="text-[#98A2B3] font-medium text-[11px]"> calls</span></span>
                </div>
              ))}
            </div>
          </div>
        </MCard>

        <MCard className="p-6 xl:col-span-2">
          <div className="anim-enter" style={{ animationDelay: '300ms' }}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[15px] font-bold text-[#101828]">Latest Leads</h3>
              <button type="button" onClick={() => navigate('/leads')} className="text-xs font-semibold text-orange-600 hover:text-orange-500 inline-flex items-center gap-1">
                View all <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="divide-y divide-[#F1F2F4]">
              {latestLeads.length === 0 && <p className="text-[13px] text-[#98A2B3] py-6">No leads captured yet — they will appear here as calls complete.</p>}
              {latestLeads.map((lead) => {
                const meta = leadStatusMeta(lead.status);
                const city = lead.metadata?.customer_info?.city;
                return (
                  <div key={lead.lead_id} className="flex items-center gap-3.5 py-3">
                    <Avatar name={lead.name || lead.phone_number} />
                    <div className="flex-1 min-w-0">
                      <p className="text-[13.5px] font-semibold text-[#101828] truncate">{lead.name || 'Unknown caller'}</p>
                      <p className="text-xs text-[#98A2B3] truncate">
                        {lead.phone_number}
                        {city ? ` · ${city}` : ''} · {timeAgo(lead.created_at)}
                      </p>
                    </div>
                    <div className="hidden sm:block">
                      <ScoreBar value={scorePct(lead.confidence_score ?? lead.score)} />
                    </div>
                    <Pill tone={meta.tone}>{meta.label}</Pill>
                  </div>
                );
              })}
            </div>
          </div>
        </MCard>
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        {[
          { title: 'Start a Campaign', text: 'Launch outbound calls to a contact list', icon: CalendarClock, to: '/campaigns' },
          { title: 'Reports & Analytics', text: 'Deep-dive call and lead performance', icon: BarChart3, to: '/reports' },
          { title: 'Manage Businesses', text: 'Clients, agents and assignments', icon: Building2, to: '/businesses' },
        ].map((a, i) => (
          <button
            key={a.title}
            type="button"
            onClick={() => navigate(a.to)}
            className="anim-enter text-left bg-white border border-[#E8EAED] rounded-[24px] p-5 flex items-center gap-4 shadow-[0_1px_2px_rgba(16,24,40,0.05),0_16px_40px_-28px_rgba(16,24,40,0.22)] hover:shadow-[0_2px_4px_rgba(16,24,40,0.06),0_24px_50px_-28px_rgba(16,24,40,0.3)] hover:-translate-y-0.5 transition-all"
            style={{ animationDelay: `${340 + i * 60}ms` }}
          >
            <span className="w-11 h-11 rounded-2xl bg-orange-50 border border-orange-100 flex items-center justify-center shrink-0">
              <a.icon className="w-5 h-5 text-orange-600" strokeWidth={1.9} />
            </span>
            <span>
              <span className="block text-sm font-bold text-[#101828]">{a.title}</span>
              <span className="block text-xs text-[#98A2B3] mt-0.5">{a.text}</span>
            </span>
            <ArrowRight className="w-4 h-4 text-[#C4CBD4] ml-auto shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
};
