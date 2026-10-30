import React from 'react';
import { NavLink } from 'react-router-dom';
import { BrandMark } from '../ui/BrandMark';
import {
  LayoutDashboard,
  Building2,
  PhoneCall,
  Activity,
  ListOrdered,
  Bot,
  Sliders,
  FileQuestion,
  FlaskConical,
  Users,
  Target,
  BarChart3,
  CalendarClock,
  CalendarDays,
  HeartPulse,
  Settings,
  Receipt,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { clsx } from 'clsx';
import { useRealTimeStats } from '../../hooks/useRealTimeStats';
import { useActiveCalls } from '../../hooks/useActiveCalls';

interface SidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number | string | null;
  pulse?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  isCollapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}) => {
  const { queue } = useRealTimeStats();
  const { activeCount } = useActiveCalls();

  const navigationGroups: NavGroup[] = [
    {
      label: 'Workspace',
      items: [
        { name: 'Overview', href: '/', icon: LayoutDashboard },
        { name: 'Businesses', href: '/businesses', icon: Building2 },
        { name: 'AI Agents', href: '/agents', icon: Bot },
        { name: 'Questionnaires', href: '/questionnaires', icon: FileQuestion },
      ],
    },
    {
      label: 'Operations',
      items: [
        {
          name: 'Calls History',
          href: '/calls',
          icon: PhoneCall,
          badge: activeCount > 0 ? `${activeCount} live` : null,
          pulse: activeCount > 0,
        },
        { name: 'Contacts', href: '/contacts', icon: Users },
        { name: 'Leads Pipeline', href: '/leads', icon: Target },
        { name: 'Follow-ups', href: '/followups', icon: CalendarClock },
        { name: 'Calendar', href: '/calendar', icon: CalendarDays },
        { name: 'Reports & Analytics', href: '/reports', icon: BarChart3 },
      ],
    },
    {
      label: 'Financials',
      items: [
        { name: 'Invoices & Billing', href: '/invoices', icon: Receipt },
      ],
    },
    {
      label: 'Management',
      items: [
        { name: 'Settings', href: '/settings', icon: Settings },
      ],
    },
  ];

  const sidebarContent = (
    <div className="app-sidebar h-full flex flex-col justify-between bg-white/75 dark:bg-[var(--sidebar-glass-bg)] backdrop-blur-[20px] saturate-[140%] border-r border-slate-200/80 dark:border-white/[0.08] transition-all duration-200">
      {/* Brand Header */}
      <div>
        <div className="h-16 flex items-center px-4 border-b border-slate-200/80 dark:border-white/[0.07]">
          <NavLink to="/" className="flex items-center gap-2.5 overflow-hidden w-full group">
            {/* ARB SoftTech brand mark (shared component, same artwork as the favicon) */}
            <div className="flex items-center justify-center shrink-0">
              <BrandMark className="w-8 h-8 drop-shadow-[0_2px_6px_rgba(249,115,22,0.35)]" />
            </div>
            {!isCollapsed && (
              <div className="flex flex-col min-w-0">
                <span className="font-bold text-[13px] tracking-tight text-slate-900 dark:text-white leading-tight whitespace-nowrap">
                  ARB SoftTech
                </span>
                <span className="text-[10px] text-slate-500 dark:text-neutral-400">
                  Agency Platform
                </span>
              </div>
            )}
          </NavLink>
        </div>

        {/* Navigation List */}
        <div className="py-4 px-3 space-y-5 overflow-y-auto max-h-[calc(100vh-7.5rem)]">
          {navigationGroups.map((group) => (
            <div key={group.label} className="space-y-1">
              {!isCollapsed && (
                <div className="px-2.5 text-[11.5px] font-semibold text-[#9D9DA8] uppercase tracking-[0.08em] mb-1.5 select-none">
                  {group.label}
                </div>
              )}
              {group.items.map((item) => (
                <NavLink
                  key={item.href}
                  to={item.href}
                  onClick={onCloseMobile}
                  className={({ isActive }) =>
                    clsx(
                      'app-navlink flex items-center rounded-xl text-[13px] font-medium transition-all duration-200 group relative',
                      isCollapsed ? 'justify-center p-2.5' : 'gap-3 px-3 py-2',
                      isActive
                        ? 'app-navlink-active bg-gradient-to-r from-orange-500/[0.18] to-orange-500/[0.06] border border-orange-500/25 text-white font-semibold shadow-[0_2px_10px_rgba(249,115,22,0.10)]'
                        : 'text-slate-600 dark:text-[#D0D0D8] hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/[0.06] hover:translate-x-[2px]'
                    )
                  }
                  title={isCollapsed ? item.name : undefined}
                >
                  <item.icon className="w-4 h-4 shrink-0 transition-colors stroke-[1.75] text-slate-500 dark:text-[#A8A8B3] group-hover:text-orange-500 dark:group-hover:text-orange-400" />
                  {!isCollapsed && <span className="truncate">{item.name}</span>}
                  {!isCollapsed && item.badge !== null && item.badge !== undefined && (
                    <span
                      className={clsx(
                        'ml-auto px-1.5 py-0.5 rounded text-[11px] font-semibold tabular-nums',
                        item.pulse
                          ? 'bg-emerald-500/15 border border-emerald-500/20 text-emerald-400'
                          : 'bg-slate-100 dark:bg-white/[0.08] text-slate-700 dark:text-neutral-200'
                      )}
                    >
                      {item.badge}
                    </span>
                  )}
                  {isCollapsed && item.badge !== null && item.badge !== undefined && (
                    <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-emerald-500" />
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Collapse Toggle Footer */}
      <div className="p-3 border-t border-slate-200/80 dark:border-white/[0.08] hidden md:block">
        <button
          type="button"
          onClick={onToggleCollapse}
          className={clsx(
            'w-full flex items-center justify-center p-2 rounded-xl text-slate-500 dark:text-[#D0D0D8] hover:text-slate-800 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/[0.06] transition-colors',
            isCollapsed ? 'px-0' : 'gap-2 text-[12.5px] font-medium'
          )}
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {isCollapsed ? (
            <ChevronRight className="w-4 h-4 stroke-[1.75]" />
          ) : (
            <div className="flex items-center gap-2">
              <ChevronLeft className="w-4 h-4 stroke-[1.75]" />
              <span>Collapse Sidebar</span>
            </div>
          )}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        className={clsx(
          'hidden md:block fixed inset-y-0 left-0 z-40 transition-all duration-200',
          isCollapsed ? 'w-16' : 'w-64'
        )}
      >
        {sidebarContent}
      </aside>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div className="fixed inset-0 bg-black/60" onClick={onCloseMobile} />
          <div className="relative w-64 max-w-[80vw] h-full z-10">{sidebarContent}</div>
        </div>
      )}
    </>
  );
};
