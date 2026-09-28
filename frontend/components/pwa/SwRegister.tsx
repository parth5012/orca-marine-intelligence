'use client';

/**
 * Service Worker Registration and Update Rollout Engine.
 * Handles lifecycle registration with module support, visibility-based update polling,
 * and an SSE chat-idle reload gate preventing mid-advisory reloads.
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/pwa/SwRegister.tsx
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { UpdateToast } from './UpdateToast';

export function isChatStreamActive(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.__orcaChatStreamActive === true
  );
}

export function SwRegister() {
  const [showToast, setShowToast] = useState<boolean>(false);
  const [isWaitingForIdle, setIsWaitingForIdle] = useState<boolean>(false);

  const registrationRef = useRef<ServiceWorkerRegistration | null>(null);
  const dismissedRef = useRef<boolean>(false);
  const refreshRequestedRef = useRef<boolean>(false);
  const retryTimerRef = useRef<NodeJS.Timeout | null>(null);

  const performReload = useCallback(() => {
    if (dismissedRef.current) return;

    if (isChatStreamActive()) {
      setIsWaitingForIdle(true);
      if (retryTimerRef.current) clearInterval(retryTimerRef.current);
      retryTimerRef.current = setInterval(() => {
        if (!isChatStreamActive()) {
          if (retryTimerRef.current) {
            clearInterval(retryTimerRef.current);
            retryTimerRef.current = null;
          }
          setIsWaitingForIdle(false);
          if (!dismissedRef.current) {
            window.location.reload();
          }
        }
      }, 2000);
      return;
    }

    const reg = registrationRef.current;
    const waitingWorker = reg?.waiting;

    if (waitingWorker) {
      waitingWorker.postMessage({ type: 'SKIP_WAITING' });
    } else {
      window.location.reload();
    }
  }, []);

  const handleRefresh = useCallback(() => {
    refreshRequestedRef.current = true;
    performReload();
  }, [performReload]);

  const handleDismiss = useCallback(() => {
    dismissedRef.current = true;
    refreshRequestedRef.current = false;
    setShowToast(false);
    setIsWaitingForIdle(false);
    if (retryTimerRef.current) {
      clearInterval(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  // Listen for controllerchange
  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) {
      return;
    }

    const handleControllerChange = () => {
      if (dismissedRef.current || !refreshRequestedRef.current) {
        return;
      }

      if (isChatStreamActive()) {
        setIsWaitingForIdle(true);
        if (retryTimerRef.current) clearInterval(retryTimerRef.current);
        retryTimerRef.current = setInterval(() => {
          if (!isChatStreamActive()) {
            if (retryTimerRef.current) {
              clearInterval(retryTimerRef.current);
              retryTimerRef.current = null;
            }
            if (!dismissedRef.current) {
              window.location.reload();
            }
          }
        }, 2000);
        return;
      }

      window.location.reload();
    };

    navigator.serviceWorker.addEventListener('controllerchange', handleControllerChange);
    return () => {
      navigator.serviceWorker.removeEventListener('controllerchange', handleControllerChange);
    };
  }, []);

  // Main registration and lifecycle management
  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) {
      return;
    }

    const isProduction = process.env.NODE_ENV === 'production';
    let swAllowed = isProduction;
    try {
      if (localStorage.getItem('orca_sw') === 'on') {
        swAllowed = true;
      }
    } catch {
      // Restrictive storage ignore
    }

    if (!swAllowed) {
      return;
    }

    let unmounted = false;
    let pollInterval: NodeJS.Timeout | null = null;

    const onStateChange = (worker: ServiceWorker) => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) {
        if (!unmounted && !dismissedRef.current) {
          setShowToast(true);
        }
      }
    };

    const attachRegistration = (reg: ServiceWorkerRegistration) => {
      registrationRef.current = reg;

      if (reg.waiting && navigator.serviceWorker.controller) {
        if (!unmounted && !dismissedRef.current) {
          setShowToast(true);
        }
      }

      const onUpdateFound = () => {
        const newWorker = reg.installing;
        if (!newWorker) return;
        newWorker.addEventListener('statechange', () => onStateChange(newWorker));
      };

      reg.addEventListener('updatefound', onUpdateFound);

      const onVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
          reg.update().catch(() => {});
        }
      };
      document.addEventListener('visibilitychange', onVisibilityChange);

      pollInterval = setInterval(() => {
        reg.update().catch(() => {});
      }, 60 * 60 * 1000);

      return () => {
        reg.removeEventListener('updatefound', onUpdateFound);
        document.removeEventListener('visibilitychange', onVisibilityChange);
        if (pollInterval) clearInterval(pollInterval);
      };
    };

    let cleanupListeners: (() => void) | null = null;

    const registerSW = () => {
      navigator.serviceWorker
        .register('/sw.js', { type: 'module' })
        .then((reg) => {
          if (unmounted) return;
          cleanupListeners = attachRegistration(reg);
        })
        .catch(() => {});
    };

    if (document.readyState === 'complete') {
      registerSW();
    } else {
      window.addEventListener('load', registerSW, { once: true });
    }

    return () => {
      unmounted = true;
      window.removeEventListener('load', registerSW);
      if (cleanupListeners) cleanupListeners();
      if (retryTimerRef.current) {
        clearInterval(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, []);

  return (
    <UpdateToast
      show={showToast}
      onRefresh={handleRefresh}
      onDismiss={handleDismiss}
      isWaitingForIdle={isWaitingForIdle}
    />
  );
}

export default SwRegister;
