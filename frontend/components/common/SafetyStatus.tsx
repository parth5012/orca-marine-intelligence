/**
 * SafetyStatus (UI-MIG-T3)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/common/SafetyStatus.tsx
 *
 * Ported visuals from source design common/SafetyStatus (READ-ONLY).
 * Pure presentational pill used by PFZRecommendationCard.
 */

import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { useApp } from '@/context/AppContext';

export type SafetyStatusType = 'SAFE' | 'CAUTION' | 'AVOID' | 'SUITABLE';

interface SafetyStatusProps {
  status: SafetyStatusType | 'MODERATE' | 'UNSUITABLE';
  size?: 'sm' | 'md' | 'lg';
  showText?: boolean;
}

export const SafetyStatus: React.FC<SafetyStatusProps> = ({
  status,
  size = 'md',
  showText = true,
}) => {
  const { themeMode } = useApp();
  const isLight = themeMode === 'light';

  const isSafe = status === 'SAFE' || status === 'SUITABLE';
  const isCaution = status === 'CAUTION' || status === 'MODERATE';
  const isDanger = status === 'AVOID' || status === 'UNSUITABLE';

  let config = {
    bg: isLight
      ? 'bg-emerald-50 text-emerald-900 border-emerald-300 font-bold shadow-sm'
      : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-emerald-950/30',
    icon: CheckCircle2,
    label: isSafe ? 'SUITABLE FOR FISHING' : status,
    dotColor: 'bg-emerald-500',
  };

  if (isCaution) {
    config = {
      bg: isLight
        ? 'bg-amber-50 text-amber-900 border-amber-300 font-bold shadow-sm'
        : 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-amber-950/30',
      icon: AlertTriangle,
      label: 'EXERCISE CAUTION',
      dotColor: 'bg-amber-500',
    };
  } else if (isDanger) {
    config = {
      bg: isLight
        ? 'bg-rose-50 text-rose-900 border-rose-300 font-bold shadow-sm'
        : 'bg-rose-500/20 text-rose-300 border-rose-500/40 shadow-rose-950/30',
      icon: XCircle,
      label: 'AVOID / DANGER ZONE',
      dotColor: 'bg-rose-500',
    };
  }

  const IconComponent = config.icon;

  const sizeClasses = {
    sm: 'px-2.5 py-1 text-xs gap-1.5 font-medium',
    md: 'px-3.5 py-1.5 text-sm gap-2 font-semibold',
    lg: 'px-5 py-2.5 text-base gap-2.5 font-bold tracking-wide',
  };

  return (
    <div
      data-testid="safety-status"
      className={`inline-flex items-center rounded-full border backdrop-blur-md shadow-md ${config.bg} ${sizeClasses[size]}`}
    >
      <span className={`w-2 h-2 rounded-full ${config.dotColor} animate-pulse`} />
      <IconComponent
        className={size === 'lg' ? 'w-5 h-5' : size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'}
      />
      {showText && <span>{config.label}</span>}
    </div>
  );
};
