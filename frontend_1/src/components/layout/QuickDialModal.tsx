import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Select } from '../ui/Select';
import { agentsApi } from '../../services/api/agents';
import { useToast } from '../../app/providers/ToastProvider';
import { ProviderType } from '../../types/api';
import {
  PhoneCall,
  Phone,
  Volume2,
  Bot,
  AlertCircle,
  ArrowUpRight,
} from 'lucide-react';
import { getErrorMessage } from '../../services/api/client';
import { Link } from 'react-router-dom';

export interface QuickDialModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialAgentId?: string;
}

export const QuickDialModal: React.FC<QuickDialModalProps> = ({
  isOpen,
  onClose,
  initialAgentId,
}) => {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [provider, setProvider] = useState<ProviderType>('vobiz');
  const [language, setLanguage] = useState('English');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const toast = useToast();

  const {
    data: agents = [],
    refetch,
    isLoading,
  } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.getAgents(100),
    staleTime: 0,
    refetchOnMount: 'always',
  });

  // Listen to global quick dial events
  useEffect(() => {
    const handleQuickDial = (e: Event) => {
      const customEvent = e as CustomEvent<{ agentId?: string }>;
      if (customEvent.detail?.agentId) {
        setSelectedAgentId(customEvent.detail.agentId);
      }
    };
    window.addEventListener('voxora-quick-dial', handleQuickDial);
    return () => window.removeEventListener('voxora-quick-dial', handleQuickDial);
  }, []);

  // Refetch when modal opens
  useEffect(() => {
    if (isOpen) {
      refetch();
    }
  }, [isOpen, refetch]);

  // Handle agent selection synchronization
  useEffect(() => {
    if (!isOpen || agents.length === 0) return;

    if (initialAgentId && agents.some((a) => (a.agent_id || a.id) === initialAgentId)) {
      setSelectedAgentId(initialAgentId);
      const ag = agents.find((a) => (a.agent_id || a.id) === initialAgentId);
      if (ag?.default_language) setLanguage(ag.default_language);
      return;
    }

    const lastSelected = sessionStorage.getItem('last_selected_agent_id');
    if (lastSelected && agents.some((a) => (a.agent_id || a.id) === lastSelected)) {
      setSelectedAgentId(lastSelected);
      const ag = agents.find((a) => (a.agent_id || a.id) === lastSelected);
      if (ag?.default_language) setLanguage(ag.default_language);
      return;
    }

    const currentExists = agents.some((a) => (a.agent_id || a.id) === selectedAgentId);
    if (!selectedAgentId || !currentExists) {
      const topAgent = agents[0];
      const topId = topAgent.agent_id || topAgent.id || '';
      setSelectedAgentId(topId);
      if (topAgent.default_language) {
        setLanguage(topAgent.default_language);
      }
    }
  }, [isOpen, agents, initialAgentId, selectedAgentId]);

  const selectedAgent = agents.find((ag) => (ag.agent_id || ag.id) === selectedAgentId);

  // Phone Call Outbound Submit
  const handlePhoneSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phoneNumber.trim()) {
      toast.error('Phone number is required');
      return;
    }
    if (!selectedAgentId) {
      toast.error('Please select an agent');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await agentsApi.startCalls(selectedAgentId, {
        phone_numbers: [phoneNumber.trim()],
        concurrency: 1,
        provider,
        language,
      });
      toast.success('Call Initiated', `Dispatched call to ${phoneNumber} (${res.status})`);
      setPhoneNumber('');
      onClose();
    } catch (err: any) {
      toast.error('Failed to initiate call', getErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Quick Call"
      description="Place an outbound phone call with an AI voice agent."
      size="md"
    >
      {agents.length === 0 && !isLoading ? (
        <div className="py-6 text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-amber-500/10 dark:bg-amber-400/10 text-amber-500 flex items-center justify-center mx-auto">
            <AlertCircle className="w-6 h-6" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-800 dark:text-zinc-100">
              No Voice Agents Available
            </h4>
            <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1 max-w-xs mx-auto">
              You need at least one configured AI voice agent before placing outbound test calls.
            </p>
          </div>
          <Link
            to="/agents"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-xl bg-orange-500 text-white hover:bg-orange-600 shadow-md shadow-orange-500/20 transition-all"
          >
            Create Agent in Agents Tab
            <ArrowUpRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Mode Option */}
          <div className="flex p-1 bg-slate-100 dark:bg-white/[0.04] rounded-xl border border-slate-200/80 dark:border-white/[0.08]">
            <div className="flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 text-orange-600 dark:text-orange-400 shadow-sm border border-slate-200/60 dark:border-white/[0.08]">
              <Phone className="w-3.5 h-3.5" />
              <span>Phone Call</span>
            </div>
          </div>

          <form onSubmit={handlePhoneSubmit} className="flex flex-col gap-4">
            <Input
              label="Phone Number"
              placeholder="+919876543210"
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
              required
              helperText="Include full country code (e.g. +91 for India)"
              leftIcon={<PhoneCall className="w-4 h-4 text-slate-400" />}
            />

            <div className="space-y-1.5">
              <Select
                label="Select AI Agent"
                value={selectedAgentId}
                onChange={(e) => {
                  const newId = e.target.value;
                  setSelectedAgentId(newId);
                  sessionStorage.setItem('last_selected_agent_id', newId);
                  const found = agents.find((ag) => (ag.agent_id || ag.id) === newId);
                  if (found?.default_language) {
                    setLanguage(found.default_language);
                  }
                }}
                required
              >
                {agents.map((ag) => {
                  const id = ag.agent_id || ag.id;
                  return (
                    <option key={id} value={id}>
                      {ag.name} ({ag.default_language || 'Hindi'})
                    </option>
                  );
                })}
              </Select>

              {selectedAgent && (
                <div className="p-3 rounded-xl bg-slate-50 dark:bg-white/[0.03] border border-slate-200/80 dark:border-white/[0.08] text-[11px] space-y-1.5">
                  <div className="flex items-center justify-between text-slate-600 dark:text-neutral-400">
                    <span className="flex items-center gap-1.5 font-medium text-slate-800 dark:text-neutral-200">
                      <Bot className="w-3.5 h-3.5 text-orange-400" />
                      {selectedAgent.name}
                    </span>
                    <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-neutral-200 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 border border-transparent dark:border-white/[0.06]">
                      {selectedAgent.tts_provider || 'Sarvam'} TTS
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-500 dark:text-neutral-400">
                    <Volume2 className="w-3 h-3 text-slate-400" />
                    <span className="truncate">
                      Voice: <strong>{selectedAgent.voice_name || 'Standard Voice'}</strong>
                      {selectedAgent.speaking_speed && ` (${selectedAgent.speaking_speed}x speed)`}
                    </span>
                  </div>
                  {selectedAgent.purpose && (
                    <p className="text-slate-500 dark:text-neutral-400 line-clamp-1 italic">
                      "{selectedAgent.purpose}"
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Select
                label="Telephony Carrier"
                value={provider}
                onChange={(e) => setProvider(e.target.value as ProviderType)}
              >
                <option value="vobiz">VoBiz</option>
                <option value="twilio">Twilio</option>
                <option value="plivo">Plivo</option>
              </Select>

              <Select
                label="Dialect / Language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="English">English</option>
                <option value="Hindi">Hindi</option>
                <option value="Hinglish">Hinglish</option>
                <option value="Marathi">Marathi</option>
                <option value="Tamil">Tamil</option>
                <option value="Telugu">Telugu</option>
                <option value="Kannada">Kannada</option>
                <option value="Bengali">Bengali</option>
                <option value="Gujarati">Gujarati</option>
              </Select>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-100 dark:border-zinc-800 mt-2">
              <Button variant="ghost" size="sm" onClick={onClose} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                isLoading={isSubmitting}
              >
                Start Call Now
              </Button>
            </div>
          </form>
        </div>
      )}
    </Modal>
  );
};
