import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import {
  api,
  ApiError,
  type AnalyticsSummary,
  type ContestMetrics,
  type DifficultyBucket,
  type TopicAnalytics,
} from "@/lib/api";
import { ErrorState, LoadingBlock, EmptyState, showDateTime, showLevel, showNumber } from "@/components/PageState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type DashboardData = {
  summary: AnalyticsSummary;
  topics: TopicAnalytics[];
  buckets: DifficultyBucket[];
  contests: ContestMetrics;
};

export default function Dashboard() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (userId === null) return;
    setLoading(true);
    setError(null);
    try {
      const [summary, topics, difficulty, contests] = await Promise.all([
        api.analyticsSummary(userId),
        api.topics(userId, 0),
        api.difficulty(userId),
        api.contestMetrics(userId),
      ]);
      setData({ summary, topics, buckets: difficulty.buckets, contests });
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load the dashboard.");
    } finally {
      setLoading(false);
    }
  }, [userId, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-6">
        <LoadingBlock rows={4} />
      </div>
    );
  }

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!data) return <EmptyState title="No analytics yet" description="Run a sync from Platforms & Sync to build your dashboard." />;

  const { summary, topics, buckets, contests } = data;
  const hasAttempts = summary.total_problems_attempted > 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Last updated {showDateTime(summary.computed_at)}
          </p>
        </div>
        <Badge variant={hasAttempts ? "default" : "secondary"}>
          {hasAttempts ? "Live data" : "No attempts recorded"}
        </Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric title="Problems solved" value={summary.total_problems_solved} />
        <Metric title="Problems attempted" value={summary.total_problems_attempted} />
        <Metric title="Submissions" value={summary.total_submissions} />
        <Metric title="Contests" value={contests.contest_count} />
      </div>

      {!hasAttempts ? (
        <EmptyState
          title="No attempts recorded yet"
          description="Link a platform and sync it to populate the dashboard."
        />
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Completion</CardTitle>
            <CardDescription>Derived from the current analytics snapshot.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row label="Completion rate" value={formatRate(summary.overall_completion_rate)} />
            <Row label="Submission efficiency" value={formatRate(summary.overall_efficiency)} />
            <Row label="Current rating" value={showNumber(contests.current_rating)} />
            <Row label="Max rating" value={showNumber(contests.max_rating)} />
            <Row label="Best rank" value={showNumber(contests.best_rank)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Difficulty distribution</CardTitle>
            <CardDescription>Problem counts by rating range.</CardDescription>
          </CardHeader>
          <CardContent>
            {buckets.length === 0 ? (
              <EmptyState title="No rated problems yet" />
            ) : (
              <div className="space-y-2">
                {buckets.map((bucket) => (
                  <div key={bucket.rating_range} className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{bucket.rating_range}</span>
                    <span className="font-medium">{bucket.count}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Topic mastery</CardTitle>
          <CardDescription>
            A level is shown only when the sample supports it; otherwise the cell says
            “insufficient data”.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {topics.length === 0 ? (
            <EmptyState title="No topic data yet" description="Sync a platform to analyse your topics." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Topic</TableHead>
                  <TableHead>Demonstrated level</TableHead>
                  <TableHead>Samples</TableHead>
                  <TableHead>Attempted</TableHead>
                  <TableHead>Completion</TableHead>
                  <TableHead>Last solved</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {topics.slice(0, 12).map((topic) => (
                  <TableRow key={topic.tag}>
                    <TableCell className="font-medium">{topic.tag}</TableCell>
                    <TableCell>{showLevel(topic.demonstrated_level)}</TableCell>
                    <TableCell>{topic.sample_size}</TableCell>
                    <TableCell>{topic.attempted_count}</TableCell>
                    <TableCell>{formatRate(topic.solve_completion_rate)}</TableCell>
                    <TableCell>{showDateTime(topic.last_solved_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ title, value }: { title: string; value: number | null }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl">{showNumber(value)}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 pb-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 1000) / 10}%`;
}
