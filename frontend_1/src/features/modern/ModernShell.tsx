import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  CalendarDays,
  Building2,
  Bot,
  PhoneCall,
  Users,
  Target,
  CalendarClock,
  BarChart3,
  Receipt,
  Settings,
  Search,
} from 'lucide-react';
import { clsx } from 'clsx';
import { BrandMark } from '../../components/ui/BrandMark';
import { LookToggle } from '../../components/layout/LookToggle';
import { BusinessSelector } from '../../components/ui/BusinessSelector';
import { useActiveCalls } from '../../hooks/useActiveCalls';

interface NavItem {
  name: string;
  href: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
  live?: boolean;
}

const NAV: NavItem[] = [
  { name: 'Overview', href: '/', icon: LayoutDashboard, end: true },
  { name: 'Businesses', href: '/businesses', icon: Building2 },
  { name: 'Agents', href: '/agents', icon: Bot },
  { name: 'Calls', href: '/calls', icon: PhoneCall, live: true },
  { name: 'Contacts', href: '/contacts', icon: Users },
  { name: 'Leads', href: '/leads', icon: Target },
  { name: 'Follow-ups', href: '/followups', icon: CalendarClock },
  { name: 'Calendar', href: '/calendar', icon: CalendarDays },
  { name: 'Reports', href: '/reports', icon: BarChart3 },
  { name: 'Billing', href: '/invoices', icon: Receipt },
  { name: 'Settings', href: '/settings', icon: Settings },
];

/**
 * Modern shell: a slim icon rail + clean top bar, completely different
 * structure from the classic sidebar layout. Rendered by AppShell when
 * the look is 'modern'; classic pages that have no modern counterpart
 * still render inside this shell via the same <Outlet />.
 */
export const ModernShell: React.FC = () => {
  const location = useLocation();
  const { activeCount } = useActiveCalls();

  const railLink = (item: NavItem) => (
    <NavLink
      key={item.href}
      to={item.href}
      end={item.end}
      title={item.name}
      className={({ isActive }) =>
        clsx(
          'relative w-[60px] py-2.5 rounded-2xl flex flex-col items-center gap-1 transition-all duration-200',
          isActive
            ? 'bg-[#101828] text-white shadow-[0_6px_16px_-6px_rgba(16,24,40,0.5)]'
            : 'text-[#667085] hover:text-[#101828] hover:bg-[#EFF1F4]'
        )
      }
    >
      <item.icon className="w-5 h-5" strokeWidth={1.9} />
      <span className="text-[9.5px] font-semibold leading-none tracking-wide">{item.name}</span>
      {item.live && activeCount > 0 && (
        <span className="absolute top-1.5 right-2 w-2 h-2 rounded-full bg-emerald-500 ring-2 ring-white" />
      )}
    </NavLink>
  );

  return (
    <div className="min-h-screen bg-[#F4F5F7] text-[#101828] flex">
      {/* Icon rail (desktop) */}
      <aside className="hidden md:flex w-[84px] shrink-0 flex-col items-center bg-white border-r border-[#E8EAED] sticky top-0 h-screen py-4 z-40">
        <NavLink to="/" className="mb-4" title="ARB SoftTech">
          <BrandMark className="w-10 h-10" />
        </NavLink>
        <nav className="flex-1 flex flex-col items-center gap-1.5 overflow-y-auto px-2 pb-2">
          {NAV.slice(0, 10).map(railLink)}
        </nav>
        <div className="pt-3 border-t border-[#EEF0F2] flex flex-col items-center gap-2">
          {railLink(NAV[10])}
          <div
            className="w-9 h-9 rounded-full bg-[#101828] text-white flex items-center justify-center text-[11px] font-bold"
            title="ARB SoftTech workspace"
          >
            AR
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-30 bg-[#F4F5F7]/90 backdrop-blur-sm px-4 sm:px-6 lg:px-8 py-3.5 flex items-center gap-3">
          <NavLink to="/" className="md:hidden shrink-0">
            <BrandMark className="w-9 h-9" />
          </NavLink>
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-[#98A2B3] absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              placeholder="Search anything here…"
              className="w-full h-10 pl-11 pr-4 rounded-full bg-white border border-[#E8EAED] text-[13px] text-[#101828] placeholder-[#98A2B3] shadow-[0_1px_2px_rgba(16,24,40,0.04)] focus:outline-none focus:border-orange-400 focus:ring-2 focus:ring-orange-500/15 transition-all"
            />
          </div>
          <div className="ml-auto flex items-center gap-2.5 shrink-0">
            <div className="hidden xl:block">
              <BusinessSelector />
            </div>
            <LookToggle />
          </div>
        </header>

        {/* Mobile nav strip */}
        <nav className="md:hidden flex gap-1.5 overflow-x-auto px-4 pb-2">
          {NAV.map((item) => (
            <NavLink
              key={item.href}
              to={item.href}
              end={item.end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-semibold whitespace-nowrap transition-all',
                  isActive ? 'bg-[#101828] text-white' : 'bg-white border border-[#E8EAED] text-[#667085]'
                )
              }
            >
              <item.icon className="w-3.5 h-3.5" />
              {item.name}
            </NavLink>
          ))}
        </nav>

        <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8 pb-10 pt-2">
          <div key={location.pathname} className="anim-page">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};
