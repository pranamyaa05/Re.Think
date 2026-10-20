/**
 * Loads everything the landing page shows from the Re.Think backend.
 *
 * The page is public, so the hook stays idle until there is a signed-in
 * identity to fetch for. Every number rendered on the page comes from these
 * responses; nothing is defaulted to zero when a request fails.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AnalyticsSummary,
  type CoachSession,
  type CoachSessionListItem,
  type ContestMetrics,
  type PlatformLink,
  type Submission,
} from "@/lib/api";

export type LandingData = {
  submissions: Submission[];
  platforms: PlatformLink[];
  sessions: CoachSessionListItem[];
  latestSession: CoachSession | null;
  summary: AnalyticsSummary | null;
  contests: ContestMetrics | null;
};

export type LandingState = {
  data: LandingData | null;
  loading: boolean;
  error: string | null;
};

const EMPTY: LandingData = {
  submissions: [],
  platforms: [],
  sessions: [],
  latestSession: null,
  summary: null,
  contests: null,
};

export function useLandingData(userId: number | null): LandingState {
  const [state, setState] = useState<LandingState>({
    data: null,
    loading: false,
    error: null,
  });

  const load = useCallback(async () => {
    if (userId === null) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const [submissions, platforms, sessions, summary, contests] = await Promise.all([
        api.submissions(userId, 500),
        api.platforms(userId),
        api.coachSessions(userId),
        api.analyticsSummary(userId),
        api.contestMetrics(userId),
      ]);

      let latestSession: CoachSession | null = null;
      const mostRecent = sessions[0];
      if (mostRecent) {
        try {
          latestSession = await api.coachSession(mostRecent.id);
        } catch {
          // A session that cannot be opened must not hide the rest of the page.
          latestSession = null;
        }
      }

      setState({
        data: { submissions, platforms, sessions, latestSession, summary, contests },
        loading: false,
        error: null,
      });
    } catch (error) {
      setState({
        data: null,
        loading: false,
        error:
          error instanceof Error
            ? error.message
            : "Could not load your progress from the backend.",
      });
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  return state;
}

export { EMPTY as EMPTY_LANDING_DATA };
