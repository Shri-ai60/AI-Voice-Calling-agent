import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Drawer } from '../../components/ui/Drawer';
import { AudioPlayer } from '../../components/ui/AudioPlayer';
import { CallStateBadge, ProviderBadge, InterestBadge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Skeleton } from '../../components/ui/Skeleton';
import { callsApi } from '../../services/api/calls';
import { useToast } from '../../app/providers/ToastProvider';
import { getErrorMessage } from '../../services/api/client';
import {
  PhoneCall,
  Clock,
  Calendar,
  Bot,
  User,
  HelpCircle,
  TrendingUp,
  Tag,
  RefreshCw,
  CalendarClock,
  Copy,
  Check,
} from 'lucide-react';
import { CallDocument, TranscriptSegment } from '../../types/api';

export interface CallDetailDrawerProps {
  callId: string | null;
  onClose: () => void;
}

export const CallDetailDrawer: React.FC<CallDetailDrawerProps> = ({ callId, onClose }) => {
  const toast = useToast();
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [copied, setCopied] = useState(false);

  const { data: call, isLoading: callLoading, refetch: refetchCall } = useQuery<CallDocument>({
    queryKey: ['call', callId],
    queryFn: () => callsApi.getCall(callId!),
    enabled: !!callId,
  });

  const { data: transcript, isLoading: transcriptLoading } = useQuery({
    queryKey: ['transcript', callId],
    queryFn: () => callsApi.getTranscript(callId!),
    enabled: !!callId,
  });

  const { data: interest, isLoading: interestLoading, refetch: refetchInterest } = useQuery({
    queryKey: ['interest', callId],
    queryFn: () => callsApi.getInterest(callId!),
    enabled: !!callId,
  });

  const handleCopyId = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopied(true);
    toast.success('Copied', 'Call ID copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleAnalyzeInterest = async () => {
    if (!callId) return;
    setIsAnalyzing(true);
    try {
      await callsApi.analyzeInterest(callId);
      toast.success('Interest Analysis Started', 'Classifier dispatched for call transcript.');
      refetchInterest();
    } catch (err: any) {
      toast.error('Analysis Failed', getErrorMessage(err));
    } finally {
      setIsAnalyzing(false);
    }
  };

  const segments: TranscriptSegment[] = transcript?.segments || call?.transcript?.segments || [];

  return (
    <Drawer
      isOpen={!!callId}
      onClose={onClose}
      title={call ? `Call Telemetry: ${call.phone_number}` : 'Call Details'}
      subtitle={
        call ? (
          <span className="inline-flex items-center gap-1.5 group">
            <span>ID: {call.call_id}</span>
            <button
              type="button"
              onClick={() => handleCopyId(call.call_id)}
              title="Copy Call ID"
              className="p-0.5 rounded hover:bg-slate-200 dark:hover:bg-white/10 text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors cursor-pointer"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </span>
        ) : undefined
      }
      width="xl"
    >
      {callLoading ? (
        <div className="space-y-4">
          <Skeleton height={60} />
          <Skeleton height={100} />
          <Skeleton height={200} />
        </div>
      ) : !call ? (
        <div className="text-center py-8 text-slate-500 text-xs">Call details could not be found.</div>
      ) : (
        <div className="space-y-6">
          {/* Metadata Grid Header */}
          <div className="p-4 rounded-2xl bg-slate-50 dark:bg-white/[0.03] border border-slate-200/80 dark:border-white/[0.08] flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-slate-900/[0.04] dark:bg-white/[0.06] text-orange-500 dark:text-orange-400 border border-slate-900/[0.07] dark:border-white/[0.09] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] flex items-center justify-center font-bold">
                <PhoneCall className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm text-slate-900 dark:text-white">
                    {call.phone_number}
                  </span>
                  <CallStateBadge state={call.state} size="xs" />
                  <ProviderBadge provider={call.provider} size="xs" />
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-neutral-400 mt-1 font-mono">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" /> {call.duration.toFixed(1)}s
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3.5 h-3.5" />
                    {new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </div>
            </div>

            {/* Interest quick tag */}
            <div className="flex items-center gap-2">
              <InterestBadge status={interest?.status || call.last_interest_status as any} />
              <Button
                variant="secondary"
                size="xs"
                onClick={handleAnalyzeInterest}
                isLoading={isAnalyzing}
              >
                Re-Analyze
              </Button>
            </div>
          </div>

          {/* Audio Recording Section */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-slate-700 dark:text-neutral-300 uppercase tracking-wider">
              Audio Recording
            </h4>
            <AudioPlayer src={callsApi.getRecordingUrl(call.call_id)} callId={call.call_id} />
          </div>

          {/* Interest Intelligence Analysis Card */}
          {interest && (
            <div className="p-4 rounded-2xl bg-slate-50/70 dark:bg-white/[0.03] border border-slate-200/80 dark:border-white/[0.08] space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-orange-400" />
                  <span className="text-xs font-bold text-slate-900 dark:text-white">
                    Lead Interest Intelligence
                  </span>
                  <InterestBadge status={interest.status} size="xs" />
                </div>
                <div className="text-xs font-mono font-semibold text-orange-400">
                  Confidence: {Math.round((interest.confidence_score || 0) * 100)}%
                </div>
              </div>

              {/* Progress bar */}
              <div className="w-full h-1.5 bg-slate-200 dark:bg-white/[0.08] rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    interest.status === 'interested'
                      ? 'bg-emerald-500'
                      : interest.status === 'not_interested'
                      ? 'bg-rose-500'
                      : 'bg-orange-500'
                  }`}
                  style={{ width: `${Math.max(5, Math.min(100, Math.round((interest.confidence_score || 0) * 100)))}%` }}
                />
              </div>

              {interest.reasoning && (
                <div className="text-xs text-slate-700 dark:text-neutral-300 leading-relaxed bg-white dark:bg-white/[0.03] p-3 rounded-xl border border-slate-200/70 dark:border-white/[0.06] space-y-1.5">
                  <p>
                    <strong className="text-slate-900 dark:text-white font-semibold">Reasoning:</strong> {interest.reasoning}
                  </p>
                  {interest.rule_applied && (
                    <div className="text-[11px] text-slate-500 dark:text-neutral-400 border-t border-slate-100 dark:border-white/[0.06] pt-1.5 flex items-center gap-1.5">
                      <span className="font-semibold text-orange-400">Rule Applied:</span>
                      <span>{interest.rule_applied}</span>
                    </div>
                  )}
                </div>
              )}

              {((interest.languages && interest.languages.length > 0) || (interest.signals && interest.signals.length > 0) || (interest.keywords && interest.keywords.length > 0)) && (
                <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                  {interest.languages && interest.languages.map((lang, i) => (
                    <span
                      key={`lang-${i}`}
                      className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    >
                      🌐 {lang}
                    </span>
                  ))}
                  {interest.signals && interest.signals.map((sig, i) => (
                    <span
                      key={`sig-${i}`}
                      className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-orange-500/10 text-orange-400 border border-orange-500/20"
                    >
                      ⚡ {sig}
                    </span>
                  ))}
                  {(!interest.signals || interest.signals.length === 0) && interest.keywords && interest.keywords.map((kw, i) => (
                    <span
                      key={`kw-${i}`}
                      className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-white/[0.04] text-neutral-300 border border-white/[0.06]"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              )}

              {/* Follow-Up Detection Condition Card */}
              {interest.followup && interest.followup.category_id && (
                <div className="p-3 rounded-xl bg-amber-500/10 dark:bg-amber-950/30 border border-amber-500/30 dark:border-amber-700/40 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs font-bold text-amber-700 dark:text-amber-400">
                      <CalendarClock className="w-4 h-4" />
                      <span>Follow-up Category {interest.followup.category_id}</span>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-200/70 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300">
                      {interest.followup.name}
                    </span>
                  </div>
                  <p className="text-xs text-slate-700 dark:text-slate-300">
                    <strong className="font-semibold text-slate-900 dark:text-slate-100">Recommended Action:</strong> {interest.followup.action}
                  </p>
                  {interest.followup.matched_utterance && (
                    <div className="text-[11px] text-slate-500 dark:text-slate-400 italic">
                      Matched: "{interest.followup.matched_utterance}"
                    </div>
                  )}
                  {interest.followup.suggested_scheduled_at && (
                    <div className="text-[10px] font-mono text-amber-600 dark:text-amber-400">
                      Auto-scheduled target: {new Date(interest.followup.suggested_scheduled_at).toLocaleString()}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ChatGPT-Style Conversation Transcript */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                Live Transcript Feed ({segments.length} turns)
              </h4>
            </div>

            {transcriptLoading ? (
              <div className="space-y-3 py-2">
                <Skeleton height={40} />
                <Skeleton height={40} />
              </div>
            ) : segments.length === 0 ? (
              <div className="p-6 text-center text-slate-400 dark:text-neutral-500 text-xs border border-dashed border-slate-200 dark:border-white/[0.08] rounded-2xl">
                No transcript segments available for this call.
              </div>
            ) : (
              <div className="space-y-3 p-4 rounded-2xl bg-slate-50/70 dark:bg-white/[0.03] border border-slate-200/80 dark:border-white/[0.07] max-h-96 overflow-y-auto">
                {segments.map((turn, i) => {
                  const isAgent = turn.speaker === 'agent';
                  return (
                    <div
                      key={i}
                      className={`flex gap-2.5 ${isAgent ? 'justify-start' : 'justify-end'}`}
                    >
                      {isAgent && (
                        <div className="w-7 h-7 rounded-full bg-orange-500 text-white flex items-center justify-center shrink-0 mt-0.5 text-xs shadow-md shadow-orange-500/20">
                          <Bot className="w-4 h-4" />
                        </div>
                      )}

                      <div
                        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-xs ${
                          isAgent
                            ? 'bg-white dark:bg-white/[0.04] text-slate-900 dark:text-neutral-100 border border-slate-200/70 dark:border-white/[0.07]'
                            : 'bg-orange-500 text-white font-normal'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3 text-[10px] opacity-75 mb-1 font-mono">
                          <span className="font-semibold uppercase">{turn.speaker}</span>
                          {turn.timestamp && (
                            <span>
                              {new Date(turn.timestamp).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit',
                              })}
                            </span>
                          )}
                        </div>
                        <p className="whitespace-pre-wrap">{turn.text}</p>
                      </div>

                      {!isAgent && (
                        <div className="w-7 h-7 rounded-full bg-slate-800 text-white flex items-center justify-center shrink-0 mt-0.5 text-xs shadow-xs">
                          <User className="w-4 h-4" />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Q&A Answers Section (If questionnaire was assigned) */}
          {call.answers && call.answers.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-slate-700 dark:text-neutral-300 uppercase tracking-wider flex items-center gap-1.5">
                <HelpCircle className="w-3.5 h-3.5 text-orange-400" />
                <span>Questionnaire Answers ({call.answers.length})</span>
              </h4>
              <div className="divide-y divide-slate-100 dark:divide-white/[0.06] border border-slate-200/80 dark:border-white/[0.08] rounded-2xl bg-white/75 dark:bg-white/[0.03] overflow-hidden">
                {call.answers.map((ans, i) => (
                  <div key={i} className="p-3.5 text-xs">
                    <p className="font-medium text-slate-800 dark:text-neutral-200 mb-1">{ans.question_text}</p>
                    <div className="p-2 rounded-lg bg-slate-50 dark:bg-white/[0.03] border border-slate-200/60 dark:border-white/[0.06] font-mono text-[11px] text-orange-400">
                      Answer: {String(ans.answer)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bottom Footer Actions */}
          <div className="pt-4 border-t border-slate-200/80 dark:border-white/[0.08] flex items-center justify-between">
            <span className="text-xs text-slate-500 dark:text-neutral-400 font-mono">
              Call State: <span className="uppercase font-semibold text-slate-800 dark:text-white">{call.state}</span>
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={onClose}
            >
              Close Details
            </Button>
          </div>
        </div>
      )}
    </Drawer>
  );
};
