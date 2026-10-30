import React, { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, useNavigate } from 'react-router-dom';
import { clsx } from 'clsx';
import {
  Bot,
  PhoneCall,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowRight,
  PhoneOff,
  RefreshCw,
  Building2,
  Eye,
  Target,
  FileText,
  ChevronDown,
  CalendarClock,
  UserPlus,
  MoreVertical,
  Zap,
  Check,
  Search,
  Layers,
} from 'lucide-react';
import { generateBusinessDashboardPdf } from '../../utils/businessPdfExport';
import { Business } from '../../app/providers/BusinessProvider';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { CallStateBadge } from '../../components/ui/Badge';
import { MetricCard } from '../../components/ui/MetricCard';
import { CallDetailDrawer } from '../calls/CallDetailDrawer';
import { agentsApi } from '../../services/api/agents';
import { callsApi } from '../../services/api/calls';
import { statsApi } from '../../services/api/stats';
import { leadsApi } from '../../services/api/leads';
import { useActiveCalls } from '../../hooks/useActiveCalls';
import { useToast } from '../../app/providers/ToastProvider';
import { useBusiness } from '../../app/providers/BusinessProvider';
import { AgentDocument, AgentDashboardResponse, CallDocument, LeadDocument } from '../../types/api';
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip as RechartsTooltip,
} from 'recharts';

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const {
    businesses,
    selectedBusinessId,
    selectedBusiness,
    isAllBusinesses,
    selectBusiness,
  } = useBusiness();

  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [isBizDropdownOpen, setIsBizDropdownOpen] = useState(false);
  const [bizSearch, setBizSearch] = useState('');
  const bizDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (bizDropdownRef.current && !bizDropdownRef.current.contains(e.target as Node)) {
        setIsBizDropdownOpen(false);
      }
    };
    if (isBizDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isBizDropdownOpen]);

  const filteredBusinesses = businesses.filter(
    (b) =>
      b.name.toLowerCase().includes(bizSearch.toLowerCase()) ||
      b.industry.toLowerCase().includes(bizSearch.toLowerCase())
  );

  // 1. Fetch all agents from backend
  const { data: agents = [], isLoading: agentsLoading, refetch: refetchAgents } = useQuery<AgentDocument[]>({
    queryKey: ['agents'],
    queryFn: () => agentsApi.getAgents(50),
    staleTime: 5000,
    refetchInterval: 10000,
  });

  // 2. Fetch leads from backend
  const { data: leads = [], isLoading: leadsLoading, refetch: refetchLeads } = useQuery<LeadDocument[]>({
    queryKey: ['leads'],
    queryFn: () => leadsApi.getLeads(),
    staleTime: 2500,
    refetchInterval: 4000,
  });

  // 3. Global Stats query
  const { data: globalStats, isLoading: statsLoading, refetch: refetchGlobal } = useQuery({
    queryKey: ['global-stats'],
    queryFn: statsApi.getStats,
    staleTime: 2500,
    refetchInterval: 3000,
  });

  // 4. Live Active Calls Stream
  const { activeCalls, refetch: refetchActive } = useActiveCalls();

  // Determine agents scoped to current business
  const scopedAgents = React.useMemo(() => {
    if (isAllBusinesses || !selectedBusiness) return agents;
    return agents.filter((a) => selectedBusiness.assignedAgentIds.includes(a.agent_id));
  }, [agents, selectedBusiness, isAllBusinesses]);

  // Primary active agent for telemetry within this business
  const primaryAgent = scopedAgents[0] || agents[0];
  const primaryAgentId = primaryAgent?.agent_id || '';

  // 5. Fetch Agent-Specific Dashboard Telemetry for primary agent
  const {
    data: agentDashboard,
    isLoading: dashLoading,
    refetch: refetchDash,
  } = useQuery<AgentDashboardResponse>({
    queryKey: ['agent-dashboard', primaryAgentId],
    queryFn: () => agentsApi.getAgentDashboard(primaryAgentId),
    enabled: !!primaryAgentId,
    staleTime: 2500,
    refetchInterval: 3000,
  });

  // Filter active calls for current business / scoped agents
  const scopedActiveCalls = React.useMemo(() => {
    if (isAllBusinesses) return activeCalls;
    const agentIds = new Set(scopedAgents.map((a) => a.agent_id));
    return activeCalls.filter((c) => !c.agent_id || agentIds.has(c.agent_id));
  }, [activeCalls, scopedAgents, isAllBusinesses]);

  // Filter leads for current business
  const scopedLeads = React.useMemo(() => {
    if (isAllBusinesses) return leads;
    const agentIds = new Set(scopedAgents.map((a) => a.agent_id));
    return leads.filter((l) => !l.agent_id || agentIds.has(l.agent_id));
  }, [leads, scopedAgents, isAllBusinesses]);

  const handleHangup = async (callId: string) => {
    try {
      await callsApi.hangupCall(callId);
      toast.info('Hangup requested', `Terminated call ${callId}`);
      refetchActive();
    } catch (err: any) {
      toast.error('Failed to hangup', err.message || 'Could not terminate call');
    }
  };

  // Telephony counts
  const totalCalls = isAllBusinesses ? (globalStats?.total_calls ?? 0) : (agentDashboard?.total_calls ?? 0);
  const completedCalls = isAllBusinesses ? (globalStats?.completed ?? 0) : (agentDashboard?.completed_calls ?? 0);
  const failedCalls = isAllBusinesses ? (globalStats?.failed ?? 0) : (agentDashboard?.failed_calls ?? 0);
  const totalOutcome = completedCalls + failedCalls;
  const completedPct = totalOutcome > 0 ? Math.round((completedCalls / totalOutcome) * 100) : 0;
  const failedPct = totalOutcome > 0 ? 100 - completedPct : 0;

  const outcomeChartData = React.useMemo(() => {
    if (totalOutcome === 0) {
      return [{ name: 'No Calls', value: 1, color: 'rgba(255,255,255,0.08)' }];
    }
    return [
      { name: 'Completed', value: completedCalls, color: '#22c55e' },
      { name: 'Failed', value: failedCalls, color: '#ef4444' },
    ].filter((item) => item.value > 0);
  }, [completedCalls, failedCalls, totalOutcome]);

  // Fetch real recent completed calls
  const { data: allRecentCalls = [] } = useQuery<CallDocument[]>({
    queryKey: ['recent-calls-global'],
    queryFn: () => callsApi.getCalls({ limit: 10 }),
    refetchInterval: 3000,
  });

  const recentCalls: CallDocument[] = React.useMemo(() => {
    if (isAllBusinesses) return allRecentCalls;
    if (agentDashboard?.recent_calls && agentDashboard.recent_calls.length > 0) {
      return agentDashboard.recent_calls;
    }
    const agentIds = new Set(scopedAgents.map((a) => a.agent_id));
    return allRecentCalls.filter((c) => !c.agent_id || agentIds.has(c.agent_id));
  }, [isAllBusinesses, allRecentCalls, agentDashboard, scopedAgents]);

  const handleDownloadPdf = () => {
    const targetBusiness: Business = selectedBusiness || {
      id: 'all_clients',
      name: 'Agency Global Clients Portfolio',
      industry: 'Enterprise Agency Operations',
      contactEmail: 'operations@voxora.ai',
      contactPhone: '',
      status: 'active',
      assignedAgentIds: agents.map((a) => a.agent_id),
      createdAt: new Date().toISOString(),
    };

    const statsToPass = isAllBusinesses
      ? {
          total_calls: globalStats?.total_calls ?? 0,
          completed_calls: globalStats?.completed ?? 0,
          failed_calls: globalStats?.failed ?? 0,
          active_calls: globalStats?.active ?? 0,
          queued_calls: globalStats?.queued ?? 0,
          average_duration_seconds: globalStats?.average_duration_seconds ?? 0,
          total_duration_seconds: (globalStats?.completed ?? 0) * (globalStats?.average_duration_seconds ?? 0),
          total_leads: leads.length,
          qualified_leads: leads.filter((l) => l.status === 'qualified' || l.status === 'interested').length,
          interested_count: leads.filter((l) => l.status === 'interested' || l.status === 'qualified').length,
          not_interested_count: leads.filter((l) => l.status === 'lost' || l.status === 'disqualified').length,
          uncertain_count: leads.filter((l) => l.status === 'contacted' || l.status === 'new').length,
        }
      : {
          total_calls: agentDashboard?.total_calls ?? 0,
          completed_calls: agentDashboard?.completed_calls ?? 0,
          failed_calls: agentDashboard?.failed_calls ?? 0,
          active_calls: agentDashboard?.active_calls ?? 0,
          queued_calls: agentDashboard?.queued_calls ?? 0,
          average_duration_seconds: agentDashboard?.average_duration_seconds ?? 0,
          total_duration_seconds: (agentDashboard?.completed_calls ?? 0) * (agentDashboard?.average_duration_seconds ?? 0),
          total_leads: scopedLeads.length,
          qualified_leads: scopedLeads.filter((l) => l.status === 'qualified' || l.status === 'interested').length,
          interested_count: agentDashboard?.interested_count ?? scopedLeads.filter((l) => l.status === 'interested' || l.status === 'qualified').length,
          not_interested_count: agentDashboard?.not_interested_count ?? 0,
          uncertain_count: agentDashboard?.uncertain_count ?? 0,
        };

    generateBusinessDashboardPdf({
      business: targetBusiness,
      assignedAgents: scopedAgents,
      stats: statsToPass,
      recentCalls: recentCalls,
    });

    toast.success('PDF Exported', `Generated telemetry dashboard report for ${targetBusiness.name}`);
  };

  const businessName = isAllBusinesses ? 'Agency Workspace' : selectedBusiness?.name || 'Workspace';
  const businessInitials = isAllBusinesses
    ? 'AG'
    : selectedBusiness?.name
    ? selectedBusiness.name.slice(0, 2).toUpperCase()
    : 'AG';

  const formatTimestamp = (iso?: string) => {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const month = d.toLocaleDateString('en-US', { month: 'short' });
      const day = d.getDate();
      const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
      return `${month} ${day}, ${time}`;
    } catch {
      return '';
    }
  };

  return (
    <div className="space-y-6">
      {/* 1. Page Title & Action Controls Row */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="relative inline-block text-left" ref={bizDropdownRef}>
          <button
            type="button"
            onClick={() => setIsBizDropdownOpen((prev) => !prev)}
            className="flex items-center gap-2 group text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-500/30 rounded-xl py-1 px-1.5 -ml-1.5 transition-colors hover:bg-slate-100/60 dark:hover:bg-white/[0.04]"
            title="Switch business portfolio"
          >
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
              <span>Overview</span>
              <span className="text-slate-400 dark:text-neutral-500 font-normal">/</span>
              <span className="text-slate-900 dark:text-white group-hover:text-orange-400 transition-colors">
                {businessName}
              </span>
            </h1>
            <ChevronDown
              className={clsx(
                'w-4 h-4 text-slate-400 dark:text-neutral-400 transition-transform duration-200 shrink-0 group-hover:text-orange-400',
                isBizDropdownOpen && 'rotate-180 text-orange-400'
              )}
            />
          </button>

          {isBizDropdownOpen && (
            <div className="absolute left-0 mt-2 w-72 sm:w-80 rounded-2xl bg-white dark:bg-[#15171e] border border-slate-200/90 dark:border-white/[0.12] shadow-2xl z-50 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
              {/* Search Field */}
              <div className="p-2.5 border-b border-slate-100 dark:border-white/[0.08] bg-slate-50/50 dark:bg-[#121319]">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    value={bizSearch}
                    onChange={(e) => setBizSearch(e.target.value)}
                    placeholder="Search businesses..."
                    className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-white dark:bg-[#1a1c24] border border-slate-200 dark:border-white/[0.10] rounded-lg text-slate-900 dark:text-neutral-100 placeholder:text-slate-400 dark:placeholder:text-neutral-500 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500/20"
                    autoFocus
                  />
                </div>
              </div>

              {/* Businesses List */}
              <div className="max-h-64 overflow-y-auto p-1.5 space-y-0.5">
                {/* All Businesses option */}
                <button
                  type="button"
                  onClick={() => {
                    selectBusiness('all');
                    setIsBizDropdownOpen(false);
                  }}
                  className={clsx(
                    'w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs text-left transition-colors',
                    isAllBusinesses
                      ? 'bg-orange-500/10 font-semibold text-orange-400'
                      : 'text-slate-700 dark:text-neutral-300 hover:bg-slate-50 dark:hover:bg-white/[0.04]'
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Layers className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <div className="flex flex-col min-w-0">
                      <span className="truncate font-medium">All Businesses (Agency View)</span>
                      <span className="text-[10px] text-slate-400 dark:text-neutral-500 truncate">Aggregate metrics & all agents</span>
                    </div>
                  </div>
                  {isAllBusinesses && <Check className="w-3.5 h-3.5 text-orange-400 shrink-0" />}
                </button>

                <div className="px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 dark:text-neutral-500 uppercase tracking-wider">
                  Client Businesses ({businesses.length})
                </div>

                {filteredBusinesses.map((biz) => {
                  const isSelected = selectedBusinessId === biz.id;
                  return (
                    <button
                      key={biz.id}
                      type="button"
                      onClick={() => {
                        selectBusiness(biz.id);
                        setIsBizDropdownOpen(false);
                      }}
                      className={clsx(
                        'w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs text-left transition-colors',
                        isSelected
                          ? 'bg-orange-500/10 font-semibold text-orange-400'
                          : 'text-slate-700 dark:text-neutral-300 hover:bg-slate-50 dark:hover:bg-white/[0.04]'
                      )}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <Building2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <div className="flex flex-col min-w-0">
                          <span className="truncate font-medium">{biz.name}</span>
                          <span className="text-[10px] text-slate-400 dark:text-neutral-500 truncate">{biz.industry}</span>
                        </div>
                      </div>
                      {isSelected && <Check className="w-3.5 h-3.5 text-orange-400 shrink-0" />}
                    </button>
                  );
                })}

                {filteredBusinesses.length === 0 && (
                  <div className="p-3 text-center text-xs text-slate-400 dark:text-neutral-500">
                    No matching businesses
                  </div>
                )}
              </div>

              {/* Manage businesses footer link */}
              <div className="p-2 border-t border-slate-100 dark:border-white/[0.08] bg-slate-50 dark:bg-[#121319]">
                <NavLink
                  to="/businesses"
                  onClick={() => setIsBizDropdownOpen(false)}
                  className="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-neutral-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/[0.06] transition-colors"
                >
                  <span>Manage all businesses</span>
                  <ArrowRight className="w-3 h-3 text-orange-400" />
                </NavLink>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          {/* Download Dashboard PDF */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleDownloadPdf}
            leftIcon={<FileText className="w-3.5 h-3.5 text-neutral-400 group-hover:text-white" />}
          >
            Download Dashboard PDF
          </Button>

          {/* Business Agents */}
          {isAllBusinesses ? (
            <NavLink to="/businesses">
              <Button variant="secondary" size="sm" leftIcon={<Building2 className="w-3.5 h-3.5 text-neutral-400" />}>
                Manage Businesses
              </Button>
            </NavLink>
          ) : (
            <NavLink to="/agents">
              <Button variant="secondary" size="sm" leftIcon={<Bot className="w-3.5 h-3.5 text-neutral-400" />}>
                Business Agents
              </Button>
            </NavLink>
          )}

          {/* Refresh */}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              refetchAgents();
              refetchLeads();
              refetchDash();
              refetchGlobal();
              refetchActive();
            }}
            leftIcon={<RefreshCw className="w-3.5 h-3.5 text-neutral-400" />}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* 2. Business Header Card */}
      <Card className="p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-white/[0.04] text-slate-900 dark:text-white border border-slate-200 dark:border-white/[0.08] flex items-center justify-center font-bold text-base shrink-0 shadow-sm">
              {businessInitials}
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2.5">
                <h2 className="text-base sm:text-lg font-bold text-slate-900 dark:text-white tracking-tight">
                  {businessName}
                </h2>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Operational
                </span>
              </div>
              <p className="text-[13px] text-slate-600 dark:text-[#C9C9D1] mt-0.5">
                {isAllBusinesses
                  ? 'Centralized operations across all client businesses and AI calling agents.'
                  : `${selectedBusiness?.industry || 'Agri-Tech & Rural Enterprise'} · ${scopedAgents.length} assigned AI agent(s)`}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* 3. Operational 4 KPI Cards Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          className="anim-enter"
          style={{ animationDelay: '0ms' }}
          label="Total Calls"
          value={totalCalls}
          subtext={isAllBusinesses ? 'Across all client businesses' : 'Attributed to this business'}
          icon={<PhoneCall className="w-4 h-4 text-orange-400" />}
          isLoading={isAllBusinesses ? (!globalStats && statsLoading) : (!agentDashboard && !globalStats && (dashLoading || statsLoading))}
        />
        <MetricCard
          className="anim-enter"
          style={{ animationDelay: '70ms' }}
          label="Live Active Calls"
          value={scopedActiveCalls.length}
          subtext="Full-duplex speech active"
          icon={<Activity className="w-4 h-4 text-orange-400" />}
          trend={{ value: scopedActiveCalls.length > 0 ? 'Active' : 'Idle', positive: scopedActiveCalls.length > 0 }}
        />
        <MetricCard
          className="anim-enter"
          style={{ animationDelay: '140ms' }}
          label="Captured Leads"
          value={scopedLeads.length}
          subtext="Qualified prospects"
          icon={<Target className="w-4 h-4 text-orange-400" />}
          isLoading={!leads.length && leadsLoading}
        />
        <MetricCard
          className="anim-enter"
          style={{ animationDelay: '210ms' }}
          label="Average Call Duration"
          value={`${(isAllBusinesses ? (globalStats?.average_duration_seconds ?? 0) : (agentDashboard?.average_duration_seconds ?? 0)).toFixed(1)}s`}
          subtext="Conversational handle time"
          icon={<Clock className="w-4 h-4 text-orange-400" />}
          isLoading={isAllBusinesses ? (!globalStats && statsLoading) : (!agentDashboard && !globalStats && (dashLoading || statsLoading))}
        />
      </div>

      {/* 4. Main 2-Column Composition (Matches Reference Screenshot) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT COLUMN (7 Cols) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Card: Live Active Conversations */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Activity className="w-4 h-4 text-orange-400" />
                  <span>Live Active Conversations</span>
                </CardTitle>
                <CardDescription>
                  Real-time active phone conversations currently in progress
                </CardDescription>
              </div>
              <NavLink to="/active-calls">
                <Button variant="ghost" size="xs" rightIcon={<ArrowRight className="w-3.5 h-3.5" />}>
                  View Monitor
                </Button>
              </NavLink>
            </CardHeader>
            <CardContent>
              {scopedActiveCalls.length === 0 ? (
                <div className="py-10 px-4 border border-dashed border-slate-200 dark:border-white/[0.08] rounded-2xl flex flex-col items-center justify-center text-center">
                  <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.08] flex items-center justify-center text-slate-500 dark:text-neutral-400 mb-3 shadow-inner">
                    <PhoneCall className="w-4 h-4" />
                  </div>
                  <h4 className="text-[13px] font-semibold text-slate-900 dark:text-[#F8F8FA]">
                    No calls currently active
                  </h4>
                  <p className="text-[12.5px] text-slate-600 dark:text-[#C9C9D1] mt-1 max-w-sm">
                    All channels are idle. Trigger outbound calls via Quick Call or Follow-ups.
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                  {scopedActiveCalls.map((call) => (
                    <div
                      key={call.call_id}
                      className="py-3 flex items-center justify-between gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-slate-900/[0.04] dark:bg-white/[0.06] text-orange-500 dark:text-orange-400 border border-slate-900/[0.07] dark:border-white/[0.09] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] flex items-center justify-center shrink-0">
                          <PhoneCall className="w-4 h-4" />
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="font-semibold text-[13.5px] text-slate-900 dark:text-[#F8F8FA] whitespace-nowrap">
                            {call.phone_number}
                          </span>
                          <span className="text-[12px] text-slate-500 dark:text-[#9D9DA8] font-mono">
                            ID: {call.call_id.slice(0, 8)}...
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 shrink-0">
                        <CallStateBadge state={call.state} size="xs" />
                        <span className="text-xs font-mono font-medium text-slate-600 dark:text-neutral-300 tabular-nums">
                          {call.duration.toFixed(1)}s
                        </span>
                        <Button
                          variant="danger"
                          size="xs"
                          onClick={() => handleHangup(call.call_id)}
                          leftIcon={<PhoneOff className="w-3 h-3" />}
                        >
                          Hangup
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Card: Assigned AI Agents */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Bot className="w-4 h-4 text-orange-400" />
                  <span>Assigned AI Agents ({businessName})</span>
                </CardTitle>
                <CardDescription>
                  Dedicated conversational AI models configured for calling operations
                </CardDescription>
              </div>
              <NavLink to="/agents">
                <Button variant="ghost" size="xs" rightIcon={<ArrowRight className="w-3.5 h-3.5" />}>
                  Manage All
                </Button>
              </NavLink>
            </CardHeader>
            <CardContent>
              {scopedAgents.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-400 dark:text-neutral-500">
                  No agents assigned to this business.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                  {scopedAgents.map((agent) => (
                    <div
                      key={agent.agent_id}
                      className="py-3 flex items-center justify-between gap-3 hover:bg-slate-50/50 dark:hover:bg-white/[0.03] rounded-xl px-2 transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-xl bg-slate-100 dark:bg-white/[0.04] text-slate-800 dark:text-white border border-slate-200 dark:border-white/[0.08] flex items-center justify-center font-bold text-xs shrink-0 shadow-sm">
                          <Bot className="w-4 h-4 text-orange-400" />
                        </div>
                        <div className="flex flex-col min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-[13.5px] text-slate-900 dark:text-[#F8F8FA] truncate">
                              {agent.name}
                            </span>
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[12px] font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">
                              Active
                            </span>
                          </div>
                          <span className="text-[12.5px] text-slate-600 dark:text-[#C9C9D1] font-mono">
                            Language: {agent.default_language} · Concurrency: {agent.concurrency}x
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <NavLink to={`/agents/${agent.agent_id}`}>
                          <Button variant="secondary" size="xs">
                            Workspace
                          </Button>
                        </NavLink>
                        <button
                          type="button"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:text-neutral-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/[0.05] transition-colors"
                        >
                          <MoreVertical className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Card: Recent Leads */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Target className="w-4 h-4 text-orange-400" />
                  <span>Recent Leads</span>
                </CardTitle>
                <CardDescription>Prospects classified with interest</CardDescription>
              </div>
              <NavLink to="/leads">
                <Button variant="ghost" size="xs" rightIcon={<ArrowRight className="w-3.5 h-3.5" />}>
                  All Leads
                </Button>
              </NavLink>
            </CardHeader>
            <CardContent>
              {scopedLeads.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-400 dark:text-neutral-500">
                  No leads captured yet for this business.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                  {scopedLeads.slice(0, 4).map((lead) => (
                    <div key={lead.lead_id} className="py-2.5 flex items-center justify-between gap-2 text-xs">
                      <div className="flex flex-col min-w-0">
                        <span className="font-semibold text-[13.5px] text-slate-900 dark:text-[#F8F8FA] truncate">
                          {lead.phone_number}
                        </span>
                        <span className="text-[12px] text-slate-600 dark:text-[#C9C9D1] truncate">
                          {lead.reasoning || lead.status || 'Qualified lead'}
                        </span>
                      </div>
                      <span className="text-[12px] font-semibold text-emerald-400 tabular-nums shrink-0">
                        {Math.round((lead.confidence_score || 0.85) * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* RIGHT COLUMN (5 Cols) */}
        <div className="lg:col-span-5 space-y-6">
          {/* Card: Call Outcome Breakdown (Standard Modern SaaS Design) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Zap className="w-4 h-4 text-orange-400" />
                  <span>Call Outcome Breakdown</span>
                </CardTitle>
                <CardDescription>Telephony performance summary</CardDescription>
              </div>
              <span className="text-[10px] font-medium text-slate-400 dark:text-neutral-400 border border-slate-200 dark:border-white/[0.08] bg-slate-50 dark:bg-white/[0.02] px-2.5 py-1 rounded-xl">
                Last 30 Days
              </span>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col sm:flex-row items-center justify-between gap-5 py-2">
                {/* Modern Donut Chart with Glass Center Core */}
                <div className="relative w-44 h-44 shrink-0 flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <defs>
                        <linearGradient id="completedGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                          <stop offset="0%" stopColor="#10B981" />
                          <stop offset="100%" stopColor="#059669" />
                        </linearGradient>
                        <linearGradient id="failedGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                          <stop offset="0%" stopColor="#F43F5E" />
                          <stop offset="100%" stopColor="#E11D48" />
                        </linearGradient>
                      </defs>

                      {/* Subtle Background Track Ring */}
                      <Pie
                        data={[{ value: 1 }]}
                        innerRadius={52}
                        outerRadius={70}
                        fill="rgba(128, 140, 155, 0.18)"
                        stroke="transparent"
                        dataKey="value"
                        isAnimationActive={false}
                      />

                      {/* Active Segment Pill Rings */}
                      <Pie
                        data={outcomeChartData}
                        innerRadius={52}
                        outerRadius={70}
                        paddingAngle={totalOutcome > 0 && completedCalls > 0 && failedCalls > 0 ? 5 : 0}
                        cornerRadius={5}
                        stroke="transparent"
                        dataKey="value"
                      >
                        {outcomeChartData.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={entry.color}
                            stroke="transparent"
                          />
                        ))}
                      </Pie>

                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: 'rgba(18, 18, 22, 0.95)',
                          backdropFilter: 'blur(16px)',
                          borderColor: 'rgba(255,255,255,0.08)',
                          borderRadius: '0.75rem',
                          fontSize: '11px',
                          color: '#fff',
                          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>

                  {/* Concentric Glass Center Core */}
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div className="w-[88px] h-[88px] rounded-full bg-white/80 dark:bg-black/50 backdrop-blur-md border border-slate-200/60 dark:border-white/[0.08] shadow-[0_4px_16px_rgba(16,24,40,0.10)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_4px_16px_rgba(0,0,0,0.35)] flex flex-col items-center justify-center">
                      <span className="text-2xl font-bold text-slate-900 dark:text-white tabular-nums tracking-tight leading-none">
                        {totalOutcome}
                      </span>
                      <span className="text-[9px] uppercase tracking-wider text-slate-400 dark:text-neutral-400 font-semibold mt-1">
                        Total Calls
                      </span>
                    </div>
                  </div>
                </div>

                {/* Outcome Telemetry Legend & Micro Progress Bars */}
                <div className="flex-1 space-y-3 w-full">
                  {/* Completed Row */}
                  <div className="space-y-1.5 p-2.5 rounded-xl bg-slate-50/70 dark:bg-white/[0.02] border border-slate-200/60 dark:border-white/[0.04]">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                        <span className="text-slate-700 dark:text-neutral-300 font-medium">Completed</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-900 dark:text-white tabular-nums">{completedCalls}</span>
                        <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20 tabular-nums">
                          {completedPct}%
                        </span>
                      </div>
                    </div>
                    {/* Micro Progress Bar */}
                    <div className="h-1.5 w-full bg-slate-200/70 dark:bg-white/[0.06] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full transition-all duration-500 shadow-[0_0_6px_rgba(16,185,129,0.3)]"
                        style={{ width: `${completedPct}%` }}
                      />
                    </div>
                  </div>

                  {/* Failed Row */}
                  <div className="space-y-1.5 p-2.5 rounded-xl bg-slate-50/70 dark:bg-white/[0.02] border border-slate-200/60 dark:border-white/[0.04]">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.5)]" />
                        <span className="text-slate-700 dark:text-neutral-300 font-medium">Failed</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-900 dark:text-white tabular-nums">{failedCalls}</span>
                        <span className="text-[10px] font-semibold text-rose-400 bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/20 tabular-nums">
                          {failedPct}%
                        </span>
                      </div>
                    </div>
                    {/* Micro Progress Bar */}
                    <div className="h-1.5 w-full bg-slate-200/70 dark:bg-white/[0.06] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-rose-500 to-rose-400 rounded-full transition-all duration-500 shadow-[0_0_6px_rgba(244,63,94,0.3)]"
                        style={{ width: `${failedPct}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Card: Quick Actions (Exact match to reference) */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Zap className="w-4 h-4 text-orange-400" />
                <span>Quick Actions</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {/* 1. Quick Call */}
                <button
                  type="button"
                  onClick={() => window.dispatchEvent(new CustomEvent('voxora-quick-dial'))}
                  className="flex flex-col items-center justify-center p-3 rounded-xl bg-orange-500/10 hover:bg-orange-500/15 border border-orange-500/30 text-orange-400 hover:text-orange-300 transition-all group shadow-sm"
                >
                  <PhoneCall className="w-4 h-4 mb-1.5 transition-transform group-hover:scale-110" />
                  <span className="text-xs font-semibold">Quick Call</span>
                </button>

                {/* 2. Follow-ups */}
                <button
                  type="button"
                  onClick={() => navigate('/followups')}
                  className="flex flex-col items-center justify-center p-3 rounded-xl bg-slate-50 dark:bg-white/[0.04] hover:bg-slate-100 dark:hover:bg-white/[0.07] border border-slate-200 dark:border-white/[0.08] text-slate-700 dark:text-neutral-300 hover:text-slate-900 dark:hover:text-white transition-all group shadow-sm"
                >
                  <CalendarClock className="w-4 h-4 mb-1.5 transition-transform group-hover:scale-110" />
                  <span className="text-xs font-semibold">Follow-ups</span>
                </button>

                {/* 3. Add Contact */}
                <button
                  type="button"
                  onClick={() => navigate('/contacts')}
                  className="flex flex-col items-center justify-center p-3 rounded-xl bg-slate-50 dark:bg-white/[0.04] hover:bg-slate-100 dark:hover:bg-white/[0.07] border border-slate-200 dark:border-white/[0.08] text-slate-700 dark:text-neutral-300 hover:text-slate-900 dark:hover:text-white transition-all group shadow-sm"
                >
                  <UserPlus className="w-4 h-4 mb-1.5 transition-transform group-hover:scale-110" />
                  <span className="text-xs font-semibold">Add Contact</span>
                </button>

                {/* 4. Manage Agents */}
                <button
                  type="button"
                  onClick={() => navigate('/agents')}
                  className="flex flex-col items-center justify-center p-3 rounded-xl bg-slate-50 dark:bg-white/[0.04] hover:bg-slate-100 dark:hover:bg-white/[0.07] border border-slate-200 dark:border-white/[0.08] text-slate-700 dark:text-neutral-300 hover:text-slate-900 dark:hover:text-white transition-all group shadow-sm"
                >
                  <Bot className="w-4 h-4 mb-1.5 transition-transform group-hover:scale-110" />
                  <span className="text-xs font-semibold">Manage Agents</span>
                </button>
              </div>
            </CardContent>
          </Card>

          {/* Card: Recent Completed Calls */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <FileText className="w-4 h-4 text-orange-400" />
                  <span>Recent Completed Calls</span>
                </CardTitle>
                <CardDescription>Latest telephony sessions and recordings</CardDescription>
              </div>
              <NavLink to="/calls" className="text-xs text-orange-400 hover:text-orange-300 transition-colors flex items-center gap-1 font-medium">
                <span>Full Calls History</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </NavLink>
            </CardHeader>
            <CardContent>
              {recentCalls.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-400 dark:text-neutral-500">
                  No recent calls logged for this business.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-white/[0.05]">
                  {recentCalls.slice(0, 5).map((call) => (
                    <div
                      key={call.call_id}
                      onClick={() => setSelectedCallId(call.call_id)}
                      className="py-3 px-2 rounded-xl flex items-center justify-between gap-3 hover:bg-slate-50 dark:hover:bg-white/[0.04] cursor-pointer transition-colors group"
                    >
                      {/* Left: Phone Icon + Number & Timestamp */}
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-xl bg-slate-100 dark:bg-white/[0.04] border border-slate-200 dark:border-white/[0.08] text-slate-700 dark:text-[#C9C9D1] group-hover:text-orange-400 flex items-center justify-center shrink-0 transition-colors">
                          <PhoneCall className="w-3.5 h-3.5" />
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="font-semibold text-[13.5px] text-slate-900 dark:text-[#F8F8FA] whitespace-nowrap">
                            {call.phone_number}
                          </span>
                          <span className="text-[12px] text-slate-500 dark:text-[#9D9DA8] whitespace-nowrap">
                            {formatTimestamp(call.created_at)}
                          </span>
                        </div>
                      </div>

                      {/* Right: Status badge + Duration + Inspect action button */}
                      <div className="ml-auto flex items-center gap-2.5 sm:gap-3 shrink-0">
                        <CallStateBadge state={call.state} size="xs" />
                        <span className="text-[12px] font-mono font-medium text-slate-600 dark:text-[#C9C9D1] tabular-nums px-2 py-0.5 rounded-md bg-slate-100/70 dark:bg-white/[0.03] border border-slate-200/50 dark:border-white/[0.06]">
                          {(call.duration || 0).toFixed(1)}s
                        </span>
                        <Button
                          variant="secondary"
                          size="xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCallId(call.call_id);
                          }}
                          leftIcon={<Eye className="w-3 h-3" />}
                        >
                          Inspect
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Call Telemetry Slideover Drawer */}
      <CallDetailDrawer callId={selectedCallId} onClose={() => setSelectedCallId(null)} />
    </div>
  );
};
