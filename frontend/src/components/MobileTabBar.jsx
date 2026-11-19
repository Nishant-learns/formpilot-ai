import React from 'react';
import { Fingerprint, History, LayoutDashboard, Lock } from 'lucide-react';
import { NeuralSparkleIcon } from './CustomIcons';

/**
 * The phone-sized primary navigation.
 *
 * On a 360-430px screen the collapsible sidebar and the docked inspector rail
 * both have to disappear, so this bar is the only way to reach the cockpit's
 * main destinations. It is hidden from `lg` upward, where the real sidebar
 * returns.
 */
const ITEMS = [
  { id: 'portal', label: 'Cockpit', Icon: LayoutDashboard },
  { id: 'vault', label: 'Vault', Icon: Lock },
  { id: 'biometrics', label: 'Studio', Icon: Fingerprint },
  { id: 'runs', label: 'Runs', Icon: History },
];

export default function MobileTabBar({ activeItem, onSelectNav, onOpenCopilot, copilotOpen }) {
  return (
    <nav
      className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-white/[0.08] bg-[#0d1210]/95 px-2 pt-1.5 backdrop-blur-2xl lg:hidden"
      aria-label="Primary"
    >
      <div className="mx-auto flex max-w-md items-stretch justify-between gap-1">
        {ITEMS.map(({ id, label, Icon }) => {
          const active = activeItem === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelectNav(id)}
              aria-current={active ? 'page' : undefined}
              className={`flex min-h-[52px] flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5 text-[10px] font-bold transition-all active:scale-[0.96] ${
                active
                  ? 'bg-gradient-to-b from-indigo-500/20 to-indigo-500/10 text-indigo-200 border border-indigo-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 active:bg-white/[0.06]'
              }`}
            >
              <Icon className="h-[18px] w-[18px]" />
              <span>{label}</span>
            </button>
          );
        })}

        <button
          type="button"
          onClick={onOpenCopilot}
          className={`flex min-h-[52px] flex-1 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5 text-[10px] font-bold transition-all active:scale-[0.96] ${
            copilotOpen
              ? 'bg-gradient-to-b from-indigo-500/20 to-indigo-500/10 text-indigo-200 border border-indigo-500/30 shadow-sm'
              : 'text-slate-400 hover:text-slate-200 active:bg-white/[0.06]'
          }`}
        >
          <span className="relative">
            <NeuralSparkleIcon className="h-[18px] w-[18px]" />
            <span className="absolute -right-1.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          </span>
          <span>Copilot</span>
        </button>
      </div>
    </nav>
  );
}
