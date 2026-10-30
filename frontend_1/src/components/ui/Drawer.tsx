import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { clsx } from 'clsx';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  width?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  width = 'lg',
}) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen || !mounted) return null;

  const widthClasses = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-3xl',
    '2xl': 'max-w-4xl',
  };

  const drawerElement = (
    <div className="fixed inset-0 z-[9999] overflow-hidden" role="dialog" aria-modal="true">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-md transition-opacity anim-fade cursor-pointer"
        onClick={onClose}
        aria-label="Close drawer backdrop"
      />

      {/* Slide-over panel container */}
      <div className="fixed inset-y-0 right-0 pl-6 sm:pl-10 max-w-full flex pointer-events-none">
        <div
          className={clsx(
            'pointer-events-auto app-overlay-panel anim-drawer-in w-screen bg-white/95 dark:bg-[#12141a]/95 backdrop-blur-[24px] saturate-[140%] border-l border-slate-200/80 dark:border-white/[0.10] shadow-[0_24px_48px_rgba(0,0,0,0.5)] flex flex-col h-full',
            widthClasses[width]
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200/80 dark:border-white/[0.08] shrink-0 bg-white/90 dark:bg-[#12141a]/95 backdrop-blur-md sticky top-0 z-20">
            <div className="min-w-0 pr-4">
              {title && (
                typeof title === 'string' ? (
                  <h2 className="text-base font-bold text-slate-900 dark:text-white truncate">{title}</h2>
                ) : (
                  title
                )
              )}
              {subtitle && (
                typeof subtitle === 'string' ? (
                  <p className="text-xs text-slate-500 dark:text-neutral-400 mt-0.5 font-mono truncate">{subtitle}</p>
                ) : (
                  subtitle
                )
              )}
            </div>
            <button
              onClick={onClose}
              type="button"
              aria-label="Close drawer"
              title="Close drawer (Esc)"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-700 dark:text-neutral-200 hover:text-slate-900 dark:hover:text-white bg-slate-100 hover:bg-slate-200 dark:bg-white/[0.08] dark:hover:bg-white/[0.14] border border-slate-300 dark:border-white/[0.12] transition-all cursor-pointer shadow-sm active:scale-95 shrink-0"
            >
              <X className="w-4 h-4" />
              <span>Close</span>
              <kbd className="hidden sm:inline-block text-[10px] px-1 py-0.2 rounded bg-white dark:bg-black/40 border border-slate-300 dark:border-white/20 text-slate-400 dark:text-neutral-400 font-mono">
                Esc
              </kbd>
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-6">{children}</div>
        </div>
      </div>
    </div>
  );

  return createPortal(drawerElement, document.body);
};
