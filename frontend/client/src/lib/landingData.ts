/**
 * Pure helpers that turn real API rows into the numbers the landing page
 * shows. Everything here is derived from data the backend returned — there
 * are no baked-in values, and an absent value stays absent.
 */

import type { Submission } from "@/lib/api";

/** Verdict both adapters use for an accepted submission. */
export const ACCEPTED_VERDICT = "OK";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

export type DayBucket = {
  /** Local calendar day, YYYY-MM-DD. */
  key: string;
  /** Short weekday label, e.g. "Mon". */
  label: string;
  /** Submissions recorded that day. */
  count: number;
  /** Accepted submissions recorded that day. */
  solved: number;
};

export function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** The last `days` calendar days, oldest first, ending today. */
export function buildDayBuckets(
  submissions: Submission[],
  days = 7,
  now: Date = new Date()
): DayBucket[] {
  const buckets: DayBucket[] = [];
  const today = startOfDay(now);
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
    buckets.push({
      key: localDayKey(date),
      label: WEEKDAY_LABELS[date.getDay()],
      count: 0,
      solved: 0,
    });
  }

  const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]));
  for (const submission of submissions) {
    const submittedAt = new Date(submission.submitted_at);
    if (Number.isNaN(submittedAt.getTime())) continue;
    const bucket = byKey.get(localDayKey(submittedAt));
    if (!bucket) continue;
    bucket.count += 1;
    if (submission.verdict === ACCEPTED_VERDICT) bucket.solved += 1;
  }
  return buckets;
}

/**
 * Four Monday-aligned weeks of activity, oldest first. Each cell is a level
 * 0-3 derived from the number of submissions on that day; days without
 * submissions stay at level 0 rather than being invented.
 */
export function buildHeatmap(
  submissions: Submission[],
  weeks = 4,
  now: Date = new Date()
): number[] {
  const today = startOfDay(now);
  const mondayOffset = (today.getDay() + 6) % 7;
  const firstDay = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - ((weeks - 1) * 7 + mondayOffset)
  );

  const counts = new Map<string, number>();
  for (const submission of submissions) {
    const submittedAt = new Date(submission.submitted_at);
    if (Number.isNaN(submittedAt.getTime())) continue;
    const key = localDayKey(submittedAt);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const levels: number[] = [];
  for (let index = 0; index < weeks * 7; index += 1) {
    const date = new Date(
      firstDay.getFullYear(),
      firstDay.getMonth(),
      firstDay.getDate() + index
    );
    const count = counts.get(localDayKey(date)) ?? 0;
    if (count === 0) levels.push(0);
    else if (count === 1) levels.push(1);
    else if (count <= 3) levels.push(2);
    else levels.push(3);
  }
  return levels;
}

/** Distinct problems accepted per platform. */
export function solvedByPlatform(submissions: Submission[]): Record<string, number> {
  const accepted = new Map<string, Set<number>>();
  for (const submission of submissions) {
    if (submission.verdict !== ACCEPTED_VERDICT) continue;
    const key = submission.platform;
    const problems = accepted.get(key) ?? new Set<number>();
    problems.add(submission.problem_id);
    accepted.set(key, problems);
  }
  const result: Record<string, number> = {};
  for (const [platform, problems] of accepted) {
    result[platform] = problems.size;
  }
  return result;
}

/** Distinct problems accepted since a given instant. */
export function solvedSince(submissions: Submission[], since: Date): number {
  return solvedBetween(submissions, since, null);
}

/** Distinct problems accepted inside a half-open window. */
export function solvedBetween(
  submissions: Submission[],
  from: Date,
  to: Date | null
): number {
  const problems = new Set<number>();
  for (const submission of submissions) {
    if (submission.verdict !== ACCEPTED_VERDICT) continue;
    const submittedAt = new Date(submission.submitted_at);
    if (Number.isNaN(submittedAt.getTime())) continue;
    if (submittedAt < from) continue;
    if (to !== null && submittedAt >= to) continue;
    problems.add(submission.problem_id);
  }
  return problems.size;
}

/** Monday of the current week, local time. */
export function startOfWeek(now: Date = new Date()): Date {
  const day = startOfDay(now);
  const mondayOffset = (day.getDay() + 6) % 7;
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() - mondayOffset);
}

/**
 * Consecutive days with at least one submission, counting back from today.
 * A streak survives a day that is not over yet: if today has no submission
 * yet but yesterday had, the streak is still counted from yesterday.
 */
export function currentStreak(
  submissions: Submission[],
  now: Date = new Date()
): number {
  const activeDays = new Set<string>();
  for (const submission of submissions) {
    const submittedAt = new Date(submission.submitted_at);
    if (Number.isNaN(submittedAt.getTime())) continue;
    activeDays.add(localDayKey(submittedAt));
  }

  const today = startOfDay(now);
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  let cursor = activeDays.has(localDayKey(today))
    ? today
    : activeDays.has(localDayKey(yesterday))
      ? yesterday
      : null;
  if (!cursor) return 0;

  let streak = 0;
  while (activeDays.has(localDayKey(cursor))) {
    streak += 1;
    cursor = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() - 1);
  }
  return streak;
}

/** Weekday names on which the learner submitted anything, most active first. */
export function activeWeekdays(submissions: Submission[]): string[] {
  const counts = new Map<number, number>();
  for (const submission of submissions) {
    const submittedAt = new Date(submission.submitted_at);
    if (Number.isNaN(submittedAt.getTime())) continue;
    const day = submittedAt.getDay();
    counts.set(day, (counts.get(day) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([day]) => WEEKDAY_NAMES[day]);
}

export type TrendPath = {
  /** SVG path for the line. */
  line: string;
  /** SVG path for the filled area under the line. */
  area: string;
  /** Last point of the series, or null when there is nothing to draw. */
  last: { x: number; y: number } | null;
};

/**
 * Builds a smooth SVG path for a series of counts. With no activity the line
 * stays flat at the bottom instead of being drawn as an invented curve.
 */
export function buildTrendPath(
  values: number[],
  width = 470,
  height = 115,
  top = 10,
  bottom = 94
): TrendPath {
  if (values.length === 0) {
    return { line: "", area: "", last: null };
  }

  const max = Math.max(...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const range = bottom - top;
  const points = values.map((value, index) => ({
    x: index * step,
    y: max === 0 ? bottom : bottom - (value / max) * range,
  }));

  if (points.length === 1) {
    const only = points[0];
    return {
      line: `M${only.x} ${only.y}`,
      area: `M${only.x} ${only.y} L${only.x} ${height} L${only.x} ${height} Z`,
      last: only,
    };
  }

  let line = `M${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[index - 1] ?? points[index];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[index + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    line += ` C${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }

  const last = points[points.length - 1];
  const area = `${line} L${width} ${height} L0 ${height} Z`;
  return { line, area, last };
}

/** "Mon 6 Oct" style label for a day offset from today. */
export function formatDayOffset(offset: number, now: Date = new Date()): string {
  const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
  const dayName = date.toLocaleDateString(undefined, { weekday: "short" });
  const day = date.toLocaleDateString(undefined, { day: "numeric" });
  const month = date.toLocaleDateString(undefined, { month: "short" });
  return `${dayName}, ${month} ${day}`;
}
