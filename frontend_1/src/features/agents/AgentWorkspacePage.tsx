import React, { useState } from 'react';
import { useParams, NavLink, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Papa from 'papaparse';
import { PageHeader } from '../../components/layout/PageHeader';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { MetricCard } from '../../components/ui/MetricCard';
import { StatusIndicator } from '../../components/ui/StatusIndicator';
import { CallStateBadge, ProviderBadge } from '../../components/ui/Badge';
import { Skeleton } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { DataTable, Column } from '../../components/ui/DataTable';
import { CallDetailDrawer } from '../calls/CallDetailDrawer';
import { agentsApi } from '../../services/api/agents';
import { questionnairesApi } from '../../services/api/questionnaires';
import { useToast } from '../../app/providers/ToastProvider';
import { useBusiness } from '../../app/providers/BusinessProvider';
import { getErrorMessage } from '../../services/api/client';
import { AgentDashboardResponse, CallDocument, ProviderType } from '../../types/api';
import { generateAgentDashboardPdf } from '../../utils/agentPdfExport';
import {
  Bot,
  PhoneForwarded,
  PhoneCall,
  UploadCloud,
  FileText,
  Clock,
  ArrowLeft,
  Eye,
  Building2,
  Edit2,
} from 'lucide-react';
import { AgentFormDrawer } from './AgentFormDrawer';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip as RechartsTooltip } from 'recharts';

export const AgentWorkspacePage: React.FC = () => {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { getBusinessForAgent } = useBusiness();

  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [phoneText, setPhoneText] = useState('');
  const [concurrency, setConcurrency] = useState(2);
  const [provider, setProvider] = useState<ProviderType>('vobiz');
  const [language, setLanguage] = useState('Marathi');
  const [selectedQuestionnaireId, setSelectedQuestionnaireId] = useState('');
  const [isStartingCalls, setIsStartingCalls] = useState(false);
  const [isAssigning, setIsAssigning] = useState(false);
  const [isEditDrawerOpen, setIsEditDrawerOpen] = useState(false);

  // Queries
  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => agentsApi.getAgent(agentId!),
    enabled: !!agentId,
  });

  const { data: dashboard, isLoading: dashLoading, refetch: refetchDash } = useQuery<AgentDashboardResponse>({
    queryKey: ['agent-dashboard', agentId],
    queryFn: () => agentsApi.getAgentDashboard(agentId!),
    enabled: !!agentId,
    refetchInterval: 4000,
  });

  const { data: questionnaires = [] } = useQuery({
    queryKey: ['questionnaires'],
    queryFn: () => questionnairesApi.getQuestionnaires(),
  });

  const { data: allAgents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.getAgents(50),
  });

  const assignedBiz = agent ? getBusinessForAgent(agent.agent_id) : undefined;

  React.useEffect(() => {
    if (agent) {
      setProvider(agent.provider || 'vobiz');
      setLanguage(agent.default_language || 'Marathi');
      setConcurrency(agent.concurrency || 2);
      setSelectedQuestionnaireId(agent.questionnaire_id || '');
    }
  }, [agent]);

  // Handle CSV file upload for phone batch
  const handleCsvUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    Papa.parse(file, {
      complete: (result) => {
        const numbers = (result.data as string[][])
          .flat()
          .map((n) => String(n).trim())
          .filter((n) => n.length > 5 && (n.startsWith('+') || /^\d+$/.test(n)));

        if (numbers.length > 0) {
          setPhoneText(numbers.join('\n'));
          toast.success('CSV Loaded', `Extracted ${numbers.length} phone numbers.`);
        } else {
          toast.warning('No valid phone numbers found in CSV');
        }
      },
      error: () => toast.error('Failed to parse CSV file'),
    });
  };

  // Start Batch Calls
  const handleStartCalls = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId) return;

    const numbers = phoneText
      .split('\n')
      .map((n) => n.trim())
      .filter((n) => n.length > 0);

    if (numbers.length === 0) {
      toast.error('Please enter at least one phone number');
      return;
    }

    setIsStartingCalls(true);
    try {
      const res = await agentsApi.startCalls(agentId, {
        phone_numbers: numbers,
        concurrency,
        provider,
        language,
        questionnaire_id: selectedQuestionnaireId || undefined,
      });

      toast.success('Outbound Dispatch Successful', `Queued ${res.queued} calls for ${agent?.name || 'Agent'}.`);
      setPhoneText('');
      refetchDash();
    } catch (err: any) {
      toast.error('Failed to start calls', getErrorMessage(err));
    } finally {
      setIsStartingCalls(false);
    }
  };

  // Assign Questionnaire
  const handleAssignQuestionnaire = async () => {
    if (!agentId || !selectedQuestionnaireId) return;
    setIsAssigning(true);
    try {
      await questionnairesApi.assignQuestionnaire(agentId, selectedQuestionnaireId);
      toast.success('Questionnaire Assigned', 'Updated script for this agent.');
      queryClient.invalidateQueries({ queryKey: ['agent', agentId] });
    } catch (err: any) {
      toast.error('Failed to assign questionnaire', getErrorMessage(err));
    } finally {
      setIsAssigning(false);
    }
  };

  // Interest breakdown data for chart
  const interestData = React.useMemo(() => {
    if (!dashboard) return [];
    return [
      { name: 'Interested', value: dashboard.interested_count || 0, color: '#10b981' },
      { name: 'Not Interested', value: dashboard.not_interested_count || 0, color: '#f43f5e' },
      { name: 'Uncertain', value: dashboard.uncertain_count || 0, color: '#f59e0b' },
    ].filter((item) => item.value > 0);
  }, [dashboard]);

  const recentCalls = dashboard?.recent_calls || [];

  const callColumns: Column<CallDocument>[] = [
    {
      key: 'phone_number',
      header: 'Phone Number',
      render: (call) => <span className="font-semibold text-xs text-slate-900 dark:text-slate-100">{call.phone_number}</span>,
    },
    {
      key: 'state',
      header: 'State',
      render: (call) => (
        <div className="flex flex-col gap-0.5">
          <CallStateBadge state={call.state} size="xs" />
          {call.state === 'FAILED' && (call as any).termination_reason && (
            <span className="text-[10px] text-rose-500 font-medium leading-tight">
              {(call as any).termination_reason}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'duration',
      header: 'Duration',
      render: (call) => <span className="font-mono text-xs text-slate-600 dark:text-zinc-400">{call.duration.toFixed(1)}s</span>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (call) => (
        <Button
          variant="outline"
          size="xs"
          onClick={() => setSelectedCallId(call.call_id)}
          leftIcon={<Eye className="w-3 h-3" />}
        >
          Inspect
        </Button>
      ),
    },
  ];

  if (agentLoading) {
    return (
      <div className="space-y-6">
        <Skeleton height={80} />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={100} />)}
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <EmptyState
        icon={<Bot className="w-8 h-8 text-slate-400" />}
        title="Agent not found"
        description="This agent may have been removed or does not exist."
        actionLabel="Back to Agents"
        onAction={() => window.history.back()}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Back Button & Header */}
      <div>
        <NavLink
          to="/agents"
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 mb-2 font-medium"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Agents Directory
        </NavLink>
        <PageHeader
          category={assignedBiz ? `Client: ${assignedBiz.name}` : 'AI Agent Workspace'}
          title={agent.name}
          subtitle={agent.description || agent.system_prompt}
          actions={
            <div className="flex items-center gap-2.5 flex-wrap">
              {/* Quick Agent Switcher */}
              {allAgents.length > 1 && (
                <div className="w-44">
                  <Select
                    value={agentId}
                    onChange={(e) => navigate(`/agents/${e.target.value}`)}
                  >
                    {allAgents.map((ag) => (
                      <option key={ag.agent_id} value={ag.agent_id}>
                        {ag.name}
                      </option>
                    ))}
                  </Select>
                </div>
              )}

              {/* Edit Agent Button */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsEditDrawerOpen(true)}
                leftIcon={<Edit2 className="w-3.5 h-3.5 text-orange-500" />}
              >
                Edit Agent
              </Button>

              {/* Download Dashboard PDF Button as secondary glass button */}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  if (agent && dashboard) {
                    generateAgentDashboardPdf(agent, dashboard, assignedBiz?.name);
                    toast.success('PDF Downloaded', `Exported full dashboard report for ${agent.name}`);
                  }
                }}
                leftIcon={<FileText className="w-3.5 h-3.5 text-neutral-400" />}
              >
                Download Dashboard PDF
              </Button>

              <StatusIndicator
                status={agent.is_enabled ? 'active' : 'inactive'}
                label={agent.is_enabled ? 'Active' : 'Disabled'}
              />
              <ProviderBadge provider={agent.provider} size="xs" />
            </div>
          }
        />
      </div>

      {/* 4 Analytics Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MetricCard
          label="Total Calls Handled"
          value={dashboard?.total_calls ?? 0}
          subtext="Telemetry history"
          icon={<PhoneCall className="w-4 h-4 text-orange-400" />}
          isLoading={dashLoading}
        />
        <MetricCard
          label="Completed Sessions"
          value={dashboard?.completed_calls ?? 0}
          subtext="Successful connects"
          icon={<PhoneForwarded className="w-4 h-4 text-orange-400" />}
          isLoading={dashLoading}
        />
        <MetricCard
          label="Avg Duration"
          value={`${(dashboard?.average_duration_seconds ?? 0).toFixed(1)}s`}
          subtext="Spoken handle time"
          icon={<Clock className="w-4 h-4 text-orange-400" />}
          isLoading={dashLoading}
        />
        <MetricCard
          label="Lead Interest Count"
          value={dashboard?.interested_count ?? 0}
          subtext="Captured prospects"
          icon={<Bot className="w-4 h-4 text-orange-400" />}
          isLoading={dashLoading}
        />
      </div>

      {/* Main Grid: Outbound Batch Launch & Scripting */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Outbound Dispatch */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <PhoneForwarded className="w-4 h-4 text-slate-700 dark:text-zinc-300" />
                <span>Launch Outbound Call Batch</span>
              </CardTitle>
              <CardDescription>
                Paste destination phone numbers (one per line) or upload a CSV file.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleStartCalls} className="space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Destination Phone Numbers
                    </label>
                    <label className="cursor-pointer text-xs font-semibold text-slate-700 dark:text-zinc-300 hover:underline flex items-center gap-1">
                      <UploadCloud className="w-3.5 h-3.5" />
                      <span>Upload CSV</span>
                      <input type="file" accept=".csv" onChange={handleCsvUpload} className="hidden" />
                    </label>
                  </div>
                  <textarea
                    rows={4}
                    value={phoneText}
                    onChange={(e) => setPhoneText(e.target.value)}
                    placeholder="+919876543210&#10;+919876543211&#10;+919876543212"
                    className="w-full p-3 text-xs font-mono rounded-xl bg-white dark:bg-white/[0.04] border border-slate-300 dark:border-white/[0.08] text-slate-900 dark:text-white placeholder:text-neutral-500 focus:outline-none focus:border-orange-500 focus:ring-2 focus:ring-orange-500/20"
                  />
                  <p className="text-[11px] text-slate-400 dark:text-neutral-500 mt-1">
                    Enter numbers in international E.164 format (e.g. +91 for India).
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <Select
                    label="Telephony Provider"
                    value={provider}
                    onChange={(e) => setProvider(e.target.value as ProviderType)}
                  >
                    <option value="vobiz">VoBiz (+918065354620)</option>
                    <option value="twilio">Twilio (+13344895368)</option>
                  </Select>

                  <Select
                    label="Spoken Language"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    <option value="Marathi">Marathi (मराठी)</option>
                    <option value="Hindi">Hindi (हिंदी)</option>
                    <option value="English">English</option>
                    <option value="Hinglish">Hinglish</option>
                  </Select>

                  <div>
                    <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-neutral-300 mb-1.5">
                      <span>Concurrency:</span>
                      <span className="font-mono text-orange-400 font-bold">{concurrency}x</span>
                    </div>
                    <input
                      type="range"
                      min="1"
                      max="10"
                      value={concurrency}
                      onChange={(e) => setConcurrency(parseInt(e.target.value))}
                      className="w-full h-1.5 bg-slate-200 dark:bg-white/[0.08] rounded-lg appearance-none cursor-pointer accent-orange-500 focus:outline-none mt-2"
                    />
                  </div>
                </div>

                <div className="flex justify-end pt-2">
                  <Button
                    type="submit"
                    variant="primary"
                    size="md"
                    isLoading={isStartingCalls}
                    leftIcon={<PhoneForwarded className="w-4 h-4" />}
                  >
                    Start Outbound Batch
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {/* Recent Calls by this agent */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Recent Calls for this Agent</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable
                columns={callColumns}
                data={recentCalls}
                keyExtractor={(c) => c.call_id}
                emptyTitle="No recent calls"
                emptyDescription="This agent has not completed any calls yet."
                pageSize={5}
              />
            </CardContent>
          </Card>
        </div>

        {/* Right Col: Scripting & Interest Breakdown */}
        <div className="space-y-6">
          {/* Questionnaire Linker Card */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-1.5">
                <FileText className="w-4 h-4 text-orange-400" />
                <span>Script Assignment</span>
              </CardTitle>
              <CardDescription>Link structured question scripts to this agent</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select
                value={selectedQuestionnaireId}
                onChange={(e) => setSelectedQuestionnaireId(e.target.value)}
              >
                <option value="">No Questionnaire Attached</option>
                {questionnaires.map((q) => (
                  <option key={q.questionnaire_id} value={q.questionnaire_id}>
                    {q.title} ({q.questions?.length || 0} questions)
                  </option>
                ))}
              </Select>
              <Button
                variant="secondary"
                size="xs"
                onClick={handleAssignQuestionnaire}
                isLoading={isAssigning}
                className="w-full"
              >
                Save Assignment
              </Button>
            </CardContent>
          </Card>

          {/* Interest Breakdown Donut */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Interest Classifier Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-36 w-full flex items-center justify-center">
                {interestData.length === 0 ? (
                  <span className="text-xs text-slate-400 dark:text-neutral-500">No interest telemetry yet</span>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={interestData} innerRadius={35} outerRadius={50} paddingAngle={4} dataKey="value">
                        {interestData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: 'rgba(18, 18, 21, 0.95)',
                          backdropFilter: 'blur(12px)',
                          borderColor: 'rgba(255,255,255,0.08)',
                          borderRadius: '0.75rem',
                          fontSize: '11px',
                          color: '#fff',
                          boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5)',
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </div>
              <div className="grid grid-cols-3 gap-1 mt-2 text-center text-xs">
                <div>
                  <span className="text-[10px] text-slate-400">Interested</span>
                  <p className="font-bold text-emerald-600 dark:text-emerald-400">{dashboard?.interested_count || 0}</p>
                </div>
                <div>
                  <span className="text-[10px] text-slate-400">Not Int.</span>
                  <p className="font-bold text-rose-600 dark:text-rose-400">{dashboard?.not_interested_count || 0}</p>
                </div>
                <div>
                  <span className="text-[10px] text-slate-400">Uncertain</span>
                  <p className="font-bold text-amber-600 dark:text-amber-400">{dashboard?.uncertain_count || 0}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <CallDetailDrawer callId={selectedCallId} onClose={() => setSelectedCallId(null)} />
    </div>
  );
};
