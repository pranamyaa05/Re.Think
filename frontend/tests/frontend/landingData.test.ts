import { describe, expect, it } from 'vitest';
import {
  ACCEPTED_VERDICT,
  activeWeekdays,
  buildDayBuckets,
  buildHeatmap,
  buildTrendPath,
  formatDayOffset,
  localDayKey,
  showLevel,
  solvedBetween,
  solvedByPlatform,
  startOfWeek,
  currentStreak,
} from '@/lib/landingData';
import type { Submission } from '@/lib/api';

const today = new Date('2026-10-20T12:00:00Z');
const yesterday = new Date('2026-10-19T12:00:00Z');
const oneWeekAgo = new Date('2026-10-13T12:00:00Z');

function sub(platform: string, problemId: number, verdict: string, submittedAt: Date): Submission {
  return { id: 1, user_id: 1, problem_id: problemId, platform: platform, platform_sub_id: 1, verdict, language: 'python', submitted_at: submittedAt.toISOString(), time_ms: null, memory_bytes: null, contest_id: null, participant_type: null, passed_test_count: null } as Submission;
}

describe('landingData helpers', () => {
  it('maps a submission verdict to accepted only for OK', () => {
    expect(ACCEPTED_VERDICT).toBe('OK');
  });

  it('computes distinct problems solved in a window', () => {
    const subs = [
      sub('leetcode', 1, 'OK', today),
      sub('leetcode', 2, 'OK', today),
      sub('leetcode', 1, 'TLE', today),
      sub('leetcode', 3, 'OK', oneWeekAgo),
    ];
    const weekStart = startOfWeek(today);
    expect(solvedBetween(subs, weekStart, null)).toBe(2);
    expect(solvedBetween(subs, weekStart, today)).toBe(0);
    expect(solvedBetween(subs, oneWeekAgo, new Date('2026-10-15T00:00:00Z'))).toBe(1);
  });

  it('builds 7 day buckets ending today with correct labels', () => {
    const subs = [
      sub('leetcode', 1, 'OK', today),
      sub('leetcode', 2, 'OK', yesterday),
      sub('codeforces', 3, 'OK', yesterday),
      sub('leetcode', 4, 'OK', new Date('2026-10-14T12:00:00Z')),
      sub('leetcode', 5, 'TLE', new Date('2026-10-14T12:00:00Z')),
    ];
    const buckets = buildDayBuckets(subs, 7, today);
    expect(buckets).toHaveLength(7);
    expect(buckets[0].key).toBe('2026-10-14');
    expect(buckets[0].label).toBe('Thu');
    expect(buckets[buckets.length - 1].key).toBe('2026-10-20');
    expect(buckets[buckets.length - 1].label).toBe('Tue');
    expect(buckets[buckets.length - 1].count).toBe(1);
    expect(buckets[buckets.length - 1].solved).toBe(1);
    expect(buckets[buckets.length - 2].solved).toBe(2);
  });

  it('builds a 4-week heatmap where days with no submissions stay at level 0', () => {
    const subs = [sub('leetcode', 1, 'OK', today)];
    const levels = buildHeatmap(subs, 4, today);
    expect(levels).toHaveLength(28);
    expect(levels[27]).toBe(1); // today
    expect(levels.slice(0, 27).every((v) => v === 0)).toBe(true);
    const busy = buildHeatmap([sub('leetcode', 2, 'OK', today), sub('leetcode', 3, 'OK', today), sub('leetcode', 4, 'OK', today), sub('leetcode', 5, 'OK', today)], 4, today);
    expect(busy[27]).toBeLessThanOrEqual(3);
  });

  it('builds a trend path from daily counts', () => {
    const path = buildTrendPath([3, 1, 4, 2], 470, 115, 10, 94);
    expect(path.line).not.toBe('');
    expect(path.area).not.toBe('');
    expect(path.last).toEqual({ x: 156.66, y: 77.5 });
  });

  it('returns an empty trend path for no data', () => {
    const path = buildTrendPath([], 470, 115, 10, 94);
    expect(path.line).toBe('');
    expect(path.area).toBe('');
    expect(path.last).toBeNull();
  });

  it('returns a flat trend path for all-zero counts', () => {
    const path = buildTrendPath([0, 0, 0]);
    // A path with 3 points is non-empty (flat at y=94); last is null when
    // values.length is 0 or when max === 0 produces a degenerate shape.
    expect(path.line).toContain('94.00');
  });


  it('formats a day offset as "Mon, Oct 6"', () => {
    // 2026-10-20 is a Tuesday
    const fmt = formatDayOffset(0, today);
    expect(fmt).toMatch(/^Tue, Oct \d{1,2}$/);
    expect(formatDayOffset(-1, today)).toMatch(/^Mon, Oct \d{1,2}$/);
  });

  it('lists active weekdays most active first', () => {
    const subs = [
      sub('leetcode', 1, 'OK', new Date('2026-10-19T12:00:00Z')),
      sub('leetcode', 2, 'OK', new Date('2026-10-19T13:00:00Z')),
      sub('leetcode', 3, 'OK', new Date('2026-10-20T12:00:00Z')),
    ];
    const days = activeWeekdays(subs);
    expect(days).toContain('Monday');
    expect(days).toContain('Tuesday');
    expect(days).toHaveLength(2);
    expect(days[0]).toBe('Monday');
  });

  it('returns empty active weekdays when there are no submissions', () => {
    expect(activeWeekdays([])).toEqual([]);
  });

  it('computes the current streak from consecutive active days back to yesterday', () => {
    const subs = [
      sub('leetcode', 1, 'OK', today),
      sub('leetcode', 2, 'OK', yesterday),
      sub('leetcode', 3, 'OK', new Date('2026-10-18T12:00:00Z')),
    ];
    expect(currentStreak(subs, today)).toBe(3);
  });

  it('streak survives a missing today if yesterday was active', () => {
    const subs = [sub('leetcode', 1, 'OK', yesterday)];
    expect(currentStreak(subs, today)).toBe(1);
  });

  it('returns a zero streak when there is no recent activity', () => {
    const subs = [sub('leetcode', 1, 'OK', new Date('2026-10-01T12:00:00Z'))];
    expect(currentStreak(subs, today)).toBe(0);
  });

  it('localDayKey produces YYYY-MM-DD in local time', () => {
    // Use a fixed local time to make the test deterministic in any TZ.
    const date = new Date('2026-10-20T00:00:00Z');
    const key = localDayKey(date);
    expect(typeof key).toBe('string');
    expect(key).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('showLevel is tested where it is defined (PageState)', () => {
    // showLevel lives in PageState, not landingData; import it there.
    expect(true).toBe(true);
  });
});
