import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError, type ContestMetrics, type ContestPerformance } from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime, showNumber } from "@/components/PageState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function Contests() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;
  const [contests, setContests] = useState<ContestPerformance[]>([]);
  const [metrics, setMetrics] = useState<ContestMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (userId === null) return;
    setLoading(true);
    try {
      const [rows, summary] = await Promise.all([
        api.contests(userId),
        api.contestMetrics(userId),
      ]);
      setContests(rows);
      setMetrics(summary);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load contest history.");
    } finally {
      setLoading(false);
    }
  }, [userId, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock rows={4} />;
  if (error) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Contests</h1>
        <p className="text-sm text-muted-foreground">
          Contest performances stored for your account.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Contests" value={showNumber(metrics?.contest_count)} />
        <Stat label="Current rating" value={showNumber(metrics?.current_rating)} />
        <Stat label="Max rating" value={showNumber(metrics?.max_rating)} />
        <Stat label="Best rank" value={showNumber(metrics?.best_rank)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
          <CardDescription>Most recent first.</CardDescription>
        </CardHeader>
        <CardContent>
          {contests.length === 0 ? (
            <EmptyState title="No contests recorded" description="Link and sync an account to import contest history." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Contest</TableHead>
                  <TableHead>Platform</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Rank</TableHead>
                  <TableHead>Rating</TableHead>
                  <TableHead>Delta</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {contests.map((contest) => (
                  <TableRow key={contest.id}>
                    <TableCell className="font-medium">{contest.contest_name}</TableCell>
                    <TableCell className="capitalize">{contest.platform}</TableCell>
                    <TableCell>{showDateTime(contest.contest_date)}</TableCell>
                    <TableCell>{showNumber(contest.rank)}</TableCell>
                    <TableCell>
                      {contest.rating_before} → {contest.rating_after}
                    </TableCell>
                    <TableCell>
                      {contest.rating_after - contest.rating_before >= 0 ? "+" : ""}
                      {contest.rating_after - contest.rating_before}
                    </TableCell>
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}
