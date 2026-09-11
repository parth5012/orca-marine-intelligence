/**
 * AuthOnboardingOverlay — forced-authenticated stub (UI-MIG-T2)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/auth/AuthOnboardingOverlay.tsx
 *
 * Per ticket: "Mount AuthOnboardingOverlay forced authenticated."
 * AppContext.authStep defaults to 'authenticated' and every auth action is
 * a passthrough back to 'authenticated', so this overlay always renders
 * null. The full splash/role-select flow lands in a later ticket; keeping
 * the component path stable avoids import churn.
 */

'use client';

import React from 'react';

export const AuthOnboardingOverlay: React.FC = () => null;

export default AuthOnboardingOverlay;
