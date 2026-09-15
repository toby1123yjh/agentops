'use client';

import { useEffect } from 'react';
import { usePostHog } from 'posthog-js/react';
import { useUser } from '@/hooks/queries/useUser';

export function PostHogUserIdentifier() {
  const { data: user } = useUser();
  const posthog = usePostHog();

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_AGENTOPS_LOCAL_MODE === 'true') return;
    if (posthog && user?.id) {
      posthog.identify(user.id, {
        email: user.email || undefined,
        name: user.full_name || undefined,
      });
    } else if (posthog && !user) {
      posthog.reset();
    }
  }, [posthog, user]);

  return null;
}
