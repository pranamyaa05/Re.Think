/**
 * The Re.Think landing page.
 *
 * The markup and class names come from the original UI so the styling stays
 * exactly as it was. Everything that used to be a made-up number (the sample
 * learner, the fixed chart, the fictional leaderboard) is now either derived
 * from the signed-in learner's own data or shown as an honest placeholder.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  Code2,
  Flame,
  Menu,
  MessageCircle,
  Sparkles,
  X,
} from "lucide-react";
import DailyQuote from "../components/DailyQuote";
import DancingText from "../components/DancingText";
import { useAuth } from "@/contexts/AuthContext";
import { useLandingData } from "@/hooks/useLandingData";
import {
  activeWeekdays,
  buildDayBuckets,
  buildHeatmap,
  buildTrendPath,
  currentStreak,
  solvedByPlatform,
  solvedBetween,
  startOfWeek,
  type DayBucket,
  type TrendPath,
} from "@/lib/landingData";
import type { CoachSession, Submission } from "@/lib/api";

const logoSrc = "/manus-storage/async-images/bbayoqbWyThrgAeme5JHkU/image-1.webp";

function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <a className={`brand${inverse ? " brand-inverse" : ""}`} href="#top" aria-label="Re.think() home">
      <img className="brand-icon" src={logoSrc} alt="" onError={(event) => { event.currentTarget.src = "/rethink-icon.png"; }} />
      <span className="brand-wordmark"><DancingText text="Re.think" /><span className="brand-parens"><DancingText text="()" /></span></span>
    </a>
  );
}

function BookHeroArtwork() {
  return (
    <div className="book-hero-art">
      <div className="book-art-frame motion-spotlight tilt-card">
        <img src="/images/book-wheel.png" alt="A sculptural wheel of open book pages, turning one idea into another" />
        <div className="book-image-wash" />
        <div className="book-image-caption"><span>AN OPEN BOOK, AN OPEN MIND</span><strong>There is always<br />another way in.</strong></div>
        <span className="book-image-tab">A NOTE TO KEEP</span>
      </div>
      <div className="book-margin-note"><span className="margin-spark">✳</span><span><strong>Read. Pause. Rethink.</strong><small>A thought can take its time.</small></span></div>
      <span className="book-art-side-note">A LITTLE ROOM FOR YOUR NEXT IDEA</span>
    </div>
  );
}

/** Neutral placeholder for a number that does not exist yet. Never a zero. */
function orDash(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return String(value);
}

function dayMonth(key: string): string {
  const date = new Date(`${key}T00:00:00`);
  if (Number.isNaN(date.getTime())) return key;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function TrendChart({ trend }: { trend: TrendPath }) {
  return (
    <svg className="trend-chart" viewBox="0 0 470 115" role="img" aria-label="Your submissions over the last seven days">
      <defs>
        <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#71a18b" stopOpacity=".25" />
          <stop offset="100%" stopColor="#71a18b" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[22, 54, 86].map((y) => <line key={y} x1="0" x2="470" y1={y} y2={y} className="chart-grid" />)}
      {trend.area ? <path d={trend.area} fill="url(#areaFill)" /> : null}
      {trend.line ? <path d={trend.line} className="chart-line" /> : null}
      {trend.last ? <circle cx={trend.last.x} cy={trend.last.y} r="5" className="chart-point" /> : null}
    </svg>
  );
}

type PlatformSummary = {
  key: string;
  label: string;
  mark: string;
  solved: number;
  tone: string;
  markTone: string;
};

const PLATFORM_PRESENTATION: Record<string, { label: string; mark: string; tone: string; markTone: string }> = {
  leetcode: { label: "LeetCode", mark: "L", tone: "lc-mini", markTone: "lc-mark" },
  codeforces: { label: "Codeforces", mark: "⌘", tone: "cf-mini", markTone: "cf-mark" },
};

function platformSummaries(submissions: Submission[]): PlatformSummary[] {
  const solved = solvedByPlatform(submissions);
  return Object.entries(solved).map(([key, count]) => {
    const presentation = PLATFORM_PRESENTATION[key.toLowerCase()] ?? {
      label: key,
      mark: key.slice(0, 1).toUpperCase(),
      tone: "",
      markTone: "",
    };
    return {
      key,
      label: presentation.label,
      mark: presentation.mark,
      solved: count,
      tone: presentation.tone,
      markTone: presentation.markTone,
    };
  });
}

function DashboardPreview({
  displayName,
  submissions,
  solvedThisWeek,
  solvedLastWeek,
  streak,
  buckets,
  heatmap,
  trend,
  platforms,
  signedIn,
  loading,
}: {
  displayName: string;
  submissions: Submission[];
  solvedThisWeek: number | null;
  solvedLastWeek: number | null;
  streak: number | null;
  buckets: DayBucket[];
  heatmap: number[];
  trend: TrendPath;
  platforms: PlatformSummary[];
  signedIn: boolean;
  loading: boolean;
}) {
  const weekStart = buckets[0]?.key;
  const weekEnd = buckets[buckets.length - 1]?.key;
  const weekLabel = weekStart && weekEnd ? `${dayMonth(weekStart)} — ${dayMonth(weekEnd)}` : "—";
  const delta = solvedThisWeek !== null && solvedLastWeek !== null ? solvedThisWeek - solvedLastWeek : null;

  return (
    <div className="dashboard-wrap" id="dashboard" aria-label="Your progress dashboard">
      <div className="dashboard-orbit orbit-one" />
      <div className="dashboard-orbit orbit-two" />
      <div className="float-note note-top"><span className="float-note-icon"><Sparkles size={15} /></span><span><strong>Little by little</strong><small>it really adds up</small></span></div>
      <div className="dashboard-card motion-spotlight tilt-card">
        <div className="dash-topline">
          <div className="dash-hello"><span className="avatar">{(displayName || "?").charAt(0).toUpperCase()}</span><span><small>A little progress goes a long way</small><strong>Hey, {displayName || "there"} <span className="wave">✳</span></strong></span></div>
          {signedIn ? <span className="demo-mini"><span /> LIVE</span> : null}
        </div>
        <div className="dash-intro"><div><span className="eyebrow">YOUR WEEK, AT A GLANCE</span><h3>You're finding<br />your rhythm.</h3></div><div className="week-pill">{weekLabel} <ChevronRight size={14} /></div></div>
        <div className="dash-stats">
          <div className="dash-stat"><span className="stat-icon mint"><Code2 size={16} /></span><span className="stat-label">Solved this week</span><strong>{orDash(solvedThisWeek)} <small>problems</small></strong><span className={delta === null ? "stat-change stat-neutral" : "stat-change"}>{delta === null ? "No comparison yet." : delta >= 0 ? <><ArrowUpRight size={13} /> {delta === 0 ? "same as last week" : `${delta} from last week`}</> : <><ArrowDownRight size={13} /> {Math.abs(delta)} fewer than last week</>}</span></div>
          <div className="dash-stat"><span className="stat-icon apricot"><Flame size={16} /></span><span className="stat-label">Current streak</span><strong>{orDash(streak)} <small>days</small></strong><span className="stat-change stat-neutral">{streak ? "You're showing up." : "Start a streak with one submission."}</span></div>
        </div>
        <div className="chart-block"><div className="chart-heading"><span>Practice momentum</span><span className="chart-period">LAST 7 DAYS</span></div><TrendChart trend={trend} /><div className="chart-days">{buckets.map((bucket) => <span key={bucket.key}>{bucket.label}</span>)}</div></div>
        {platforms.length > 0 ? (
          <div className="platform-row">{platforms.map((platform) => <div className={`platform-mini ${platform.tone}`} key={platform.key}><span className={`platform-mark ${platform.markTone}`}>{platform.mark}</span><span><small>{platform.label}</small><strong>{platform.solved} solved</strong></span><span className="platform-arrow"><ArrowUpRight size={14} /></span></div>)}</div>
        ) : (
          <div className="platform-row"><div className="platform-mini"><span className="platform-mark">·</span><span><small>Platforms</small><strong>{signedIn ? "none linked yet" : "sign in to see yours"}</strong></span></div></div>
        )}
        <span className="dashboard-disclaimer">{signedIn ? `Live data from your Re.Think account · ${submissions.length} submissions in view` : "Sign in to replace this preview with your own numbers"}</span>
      </div>
      <div className="float-note note-bottom"><span className="streak-spark">✦</span><span><strong>{streak ? `${streak} day${streak === 1 ? "" : "s"} in a row` : "One page at a time"}</strong><small>{streak ? "that's a lovely habit" : "your streak starts with a single submission"}</small></span></div>
    </div>
  );
}

const features = [
  { icon: BookOpen, label: "Take the long way, if you like", title: "Explanations worth sitting with.", copy: "Find a fresh way into the idea, read a hint, then let the pattern settle before you move on.", tone: "feature-mint" },
  { icon: MessageCircle, label: "Ask without the awkward", title: "A question is a good place to start.", copy: "Stuck on a tricky edge case? Ask for a nudge, a clearer example, or one more gentle explanation.", tone: "feature-lilac" },
  { icon: Code2, label: "Keep your bookmark", title: "See the chapters adding up.", copy: "Bring LeetCode and Codeforces practice together, then notice the small habits that are becoming yours.", tone: "feature-peach" },
];

function CoachPreview({ session }: { session: CoachSession | null }) {
  const [showAnswer, setShowAnswer] = useState(false);
  const messages = session?.messages ?? [];
  const learnerMessage = [...messages].reverse().find((message) => message.role === "user");
  const coachMessage = [...messages].reverse().find((message) => message.role !== "user");

  return (
    <div className="coach-demo motion-spotlight tilt-card" id="coach-demo">
      <div className="coach-demo-top"><div className="coach-identity"><span className="coach-avatar"><BookOpen size={16} /></span><span><strong>Notes in the margin</strong><small>{session ? "your latest coaching moment" : "no session yet"}</small></span></div><span className="demo-badge"><span className="demo-dot" />{session ? "Your session" : "Nothing yet"}</span></div>
      {session ? (
        <>
          {learnerMessage ? <div className="chat-message learner-message"><span className="chat-avatar learner-avatar">Y</span><p>{learnerMessage.content}</p></div> : null}
          {coachMessage ? <div className="chat-message coach-message"><span className="chat-avatar coach-chat-avatar"><Sparkles size={13} /></span><div><span className="coach-label">A LITTLE NUDGE <i>· from your coach</i></span><p>{coachMessage.content}</p></div></div> : null}
          <button type="button" className="hint-button" onClick={() => setShowAnswer((shown) => !shown)} aria-expanded={showAnswer}>{showAnswer ? "Close this margin note" : "Turn to one more hint"}<ArrowRight size={15} /></button>
          {showAnswer ? <div className="reveal-answer" role="status"><span className="reveal-check"><Check size={14} /></span><span><strong>Keep reading</strong><small>Open the Coach page to continue this session with the live coach.</small></span></div> : null}
          <div className="coach-demo-foot"><span>✳</span> Your own coaching history</div>
        </>
      ) : (
        <>
          <div className="chat-message learner-message"><span className="chat-avatar learner-avatar">?</span><p>No coaching session yet.</p></div>
          <div className="chat-message coach-message"><span className="chat-avatar coach-chat-avatar"><Sparkles size={13} /></span><div><span className="coach-label">A LITTLE NUDGE <i>· waiting for you</i></span><p>Open the Coach page, pick a problem, and the first question will be waiting for you there.</p></div></div>
          <div className="coach-demo-foot"><span>✳</span> Sessions appear here once you start one</div>
        </>
      )}
    </div>
  );
}

function LeaderboardPreview({
  displayName,
  solved,
  streak,
  signedIn,
}: {
  displayName: string;
  solved: number | null;
  streak: number | null;
  signedIn: boolean;
}) {
  return (
    <div className="leaderboard-card motion-spotlight tilt-card">
      <div className="leaderboard-head"><div><span className="eyebrow">A FRIENDLY LITTLE SNAPSHOT</span><h3>Progress, not pressure.</h3></div><span className="leaderboard-icon"><ArrowDownRight size={19} /></span></div>
      <div className="leaderboard-labels"><span>LEARNER</span><span>PROBLEMS</span><span>RHYTHM</span></div>
      {signedIn ? (
        <div className="leaderboard-row your-row"><span className="rank-number rank-gold">01</span><span className="learner-info"><strong>{displayName}</strong><small>your pace, your path</small></span><strong className="solved-count">{orDash(solved)}</strong><span className="streak-pill"><Flame size={12} />{streak ? `${streak} days` : "no streak yet"}</span></div>
      ) : (
        <div className="leaderboard-row"><span className="rank-number rank-silver">—</span><span className="learner-info"><strong>Your row is waiting</strong><small>sign in to fill it in</small></span><strong className="solved-count">—</strong><span className="streak-pill"><Flame size={12} />—</span></div>
      )}
      <div className="board-foot"><span className="demo-badge"><span className="demo-dot" />{signedIn ? "Your own numbers" : "Nothing is invented here"}</span><span className="board-platforms">LeetCode <i>+</i> Codeforces</span></div>
    </div>
  );
}

export default function Home() {
  const { user } = useAuth();
  const userId = user?.backendUserId ?? null;
  const { data, loading: dataLoading } = useLandingData(userId);
  const [menuOpen, setMenuOpen] = useState(false);

  const submissions = data?.submissions ?? [];

  const derived = useMemo(() => {
    const buckets = buildDayBuckets(submissions, 7);
    const weekStart = startOfWeek();
    const previousWeekStart = new Date(
      weekStart.getFullYear(),
      weekStart.getMonth(),
      weekStart.getDate() - 7
    );
    return {
      buckets,
      heatmap: buildHeatmap(submissions, 4),
      trend: buildTrendPath(buckets.map((bucket) => bucket.count)),
      streak: currentStreak(submissions),
      solvedThisWeek: solvedBetween(submissions, weekStart, null),
      solvedLastWeek: solvedBetween(submissions, previousWeekStart, weekStart),
      platforms: platformSummaries(submissions),
      weekdays: activeWeekdays(submissions),
    };
  }, [submissions]);

  const displayName = user?.name?.trim() || user?.username || "there";
  const signedIn = Boolean(user);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const revealTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".hero-copy, .book-art-frame, .book-margin-note, .intro-grid, .coach-heading, .coach-demo, .feature-item, .quote-content, .progress-heading, .dashboard-card, .progress-insight-card, .leaderboard-card, .step-card, .closing-card",
    ));
    const pointerTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".hero-section, .motion-spotlight, .tilt-card",
    ));
    let observer: IntersectionObserver | undefined;

    if (!reducedMotion && "IntersectionObserver" in window) {
      document.documentElement.classList.add("motion-ready");
      revealTargets.forEach((target) => target.classList.add("motion-reveal"));
      observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer?.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -24px 0px" });
      revealTargets.forEach((target) => observer?.observe(target));
    }

    const trackPointer = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || reducedMotion) return;
      const target = event.currentTarget;
      if (!(target instanceof HTMLElement)) return;
      const bounds = target.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const x = event.clientX - bounds.left;
      const y = event.clientY - bounds.top;
      target.style.setProperty("--spot-x", `${x}px`);
      target.style.setProperty("--spot-y", `${y}px`);
      if (target.classList.contains("hero-section")) {
        target.classList.add("cursor-active");
        target.style.setProperty("--grid-x", `${Math.round(x * 0.035)}px`);
        target.style.setProperty("--grid-y", `${Math.round(y * 0.035)}px`);
      }
      if (target.classList.contains("tilt-card")) {
        const fromCenterX = (x / bounds.width - 0.5) * 2;
        const fromCenterY = (y / bounds.height - 0.5) * 2;
        const maxTilt = target.classList.contains("book-art-frame") ? 4 : 3;
        target.classList.add("is-pointer-active");
        target.style.setProperty("--tilt-x", `${-fromCenterY * maxTilt}deg`);
        target.style.setProperty("--tilt-y", `${fromCenterX * maxTilt}deg`);
        target.style.setProperty("--pull-x", `${fromCenterX * 2.6}px`);
        target.style.setProperty("--pull-y", `${fromCenterY * 2.2}px`);
      }
    };
    const clearPointer = (event: PointerEvent) => {
      if (!(event.currentTarget instanceof HTMLElement)) return;
      const target = event.currentTarget;
      target.classList.remove("cursor-active", "is-pointer-active");
      ["--spot-x", "--spot-y", "--grid-x", "--grid-y", "--tilt-x", "--tilt-y", "--pull-x", "--pull-y"].forEach((property) => target.style.removeProperty(property));
    };
    pointerTargets.forEach((target) => {
      target.addEventListener("pointermove", trackPointer);
      target.addEventListener("pointerleave", clearPointer);
    });

    return () => {
      observer?.disconnect();
      document.documentElement.classList.remove("motion-ready");
      pointerTargets.forEach((target) => {
        target.removeEventListener("pointermove", trackPointer);
        target.removeEventListener("pointerleave", clearPointer);
      });
    };
  }, []);
  const closeMenu = () => setMenuOpen(false);

  const activitySentence = derived.weekdays.length > 0
    ? `You've been showing up on ${derived.weekdays.slice(0, 2).join(" and ").toLowerCase()}.`
    : "Your rhythm starts with the first submission.";

  return (
    <div className="site-shell" id="top">
      <header className="site-header">
        <div className="nav-shell">
          <Brand />
          <button className="mobile-menu-button" type="button" aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? <X size={21} /> : <Menu size={21} />}</button>
          <nav className={menuOpen ? "main-nav nav-open" : "main-nav"} aria-label="Main navigation">
            <a href="#how-it-works" onClick={closeMenu}>The reading room</a>
            <a href="#your-progress" onClick={closeMenu}>Your progress</a>
            <a href="#a-little-help" onClick={closeMenu}>A little help</a>
            <a href={signedIn ? "/dashboard" : "/login"} onClick={closeMenu}>{signedIn ? "Open your dashboard" : "Sign in"}</a>
            <a className="nav-cta" href="#explore" onClick={closeMenu}>Turn the page <ArrowRight size={15} /></a>
          </nav>
        </div>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-container">
            <div className="hero-copy">
              <div className="hero-kicker"><span className="kicker-star">✳</span> A bookish take on your coding coach</div>
              <h1>Read your way<br />to the <em>aha.</em></h1>
              <p className="hero-lede">Some ideas need a second read, a helpful hint, or the right question. Re.think() gives your learning room to unfold — one thoughtful page at a time.</p>
              <p className="hero-support">A calmer coding companion, with your LeetCode and Codeforces progress waiting in the wings.</p>
              <div className="hero-actions">
                <a className="button button-primary" href="#how-it-works">Step inside <ArrowRight size={17} /></a>
                <a className="button button-quiet" href="#your-progress">See your progress <ChevronRight size={16} /></a>
              </div>
              <div className="hero-note"><span className="note-check"><Check size={12} /></span><span>Good ideas deserve a second read.</span></div>
            </div>
            <BookHeroArtwork />
          </div>
          <div className="hero-bottom"><span className="hero-bottom-line" /><span>Turn a page. Find another way in.</span><span className="hero-bottom-line" /></div>
        </section>

        <section className="intro-section section-pad" id="how-it-works">
          <div className="section-container intro-grid">
            <div className="section-index">01 <span>— A PAGE AT A TIME</span></div>
            <div className="intro-main">
              <p className="eyebrow">LESS PRESSURE. MORE ROOM TO UNDERSTAND.</p>
              <h2>Some ideas are<br /><em>better read twice.</em></h2>
              <p className="intro-copy">Competitive programming is the subject. Reading, reflection, and the small click of understanding are the experience. Ask what you like, follow a hint, or return to the explanation when you're ready.</p>
              <a className="text-link" href="#a-little-help">Read a sample margin note <ArrowRight size={16} /></a>
            </div>
            <div className="intro-aside motion-spotlight tilt-card"><span className="aside-quote-mark">“</span><p>You don't need a whole new brain. Just another way into the idea.</p><span className="aside-attribution">A little reminder from Re.think()</span><div className="aside-doodle">✳ <span>· · · · ·</span> ✳</div></div>
          </div>
        </section>

        <section className="coach-section section-pad" id="a-little-help">
          <div className="section-container">
            <div className="coach-heading">
              <div><div className="section-index">02 <span>— NOTES IN THE MARGIN</span></div><p className="eyebrow">A GOOD EXPLANATION DOESN'T SHOUT</p><h2>Ask the question.<br /><em>Keep the confidence.</em></h2></div>
              <p className="coach-heading-note">No silly questions. No need to be halfway through the book before you begin.</p>
            </div>
            <div className="coach-grid">
              <CoachPreview session={data?.latestSession ?? null} />
              <div className="feature-list">{features.map(({ icon: Icon, label, title, copy, tone }, index) => <article className={`feature-item motion-spotlight tilt-card ${tone}`} key={label}><div className="feature-number">0{index + 1}</div><div className="feature-icon"><Icon size={18} strokeWidth={1.8} /></div><div><span className="feature-label">{label}</span><h3>{title}</h3><p>{copy}</p></div><ArrowUpRight className="feature-arrow" size={17} /></article>)}</div>
            </div>
          </div>
        </section>

        <DailyQuote />

        <section className="progress-section section-pad" id="your-progress">
          <div className="section-container">
            <div className="progress-heading">
              <div><div className="section-index">03 <span>— KEEP YOUR BOOKMARK</span></div><p className="eyebrow">THE WIDER VIEW, WHEN YOU'RE READY</p><h2>Remember where<br /><em>you left off.</em></h2></div>
              <div className="progress-blurb"><p>Your week isn't a score; it's a story. When you want the bigger picture, see your LeetCode and Codeforces practice in one gentle, live view.</p><span className="demo-badge"><span className="demo-dot" />{signedIn ? "Live data" : "Sign in for live data"}</span></div>
            </div>
            <DashboardPreview
              displayName={displayName}
              submissions={submissions}
              solvedThisWeek={signedIn ? derived.solvedThisWeek : null}
              solvedLastWeek={signedIn ? derived.solvedLastWeek : null}
              streak={signedIn ? derived.streak : null}
              buckets={derived.buckets}
              heatmap={derived.heatmap}
              trend={derived.trend}
              platforms={signedIn ? derived.platforms : []}
              signedIn={signedIn}
              loading={dataLoading}
            />
            <div className="progress-cards">
              <div className="progress-insight-card motion-spotlight tilt-card"><div className="insight-top"><span className="insight-symbol"><Sparkles size={16} /></span><span className="insight-label">A PATTERN WORTH NOTICING</span><span className="insight-demo">{signedIn ? "LIVE" : "—"}</span></div><h3>{activitySentence.split(" ").slice(0, -1).join(" ")}<br /><em>{activitySentence.split(" ").slice(-1)}</em></h3><p>That kind of consistency? It really does count.</p><div className="week-dots" aria-label="Your weekly activity heatmap">{derived.heatmap.map((value, index) => <span key={index} className={`heat-level-${value}`} />)}</div><div className="weekday-labels"><span>WEEK 1</span><span>WEEK 2</span><span>WEEK 3</span><span>WEEK 4</span></div><span className="insight-foot">{signedIn ? "Activity from your synced platforms" : "Sign in to see your own activity"}</span></div>
              <LeaderboardPreview displayName={displayName} solved={signedIn ? data?.summary?.total_problems_solved ?? null : null} streak={signedIn ? derived.streak : null} signedIn={signedIn} />
            </div>
            <div className="platform-note"><span className="platform-note-icon"><Code2 size={15} /></span><span><strong>A quiet shelf for two practice spaces.</strong> LeetCode + Codeforces, together when you choose to connect them.</span><span className="platform-note-tail">Made for your momentum <span>↗</span></span></div>
          </div>
        </section>

        <section className="steps-section section-pad" id="explore">
          <div className="section-container">
            <div className="steps-top"><div><div className="section-index">04 <span>— YOUR PACE, YOUR PATH</span></div><p className="eyebrow">THERE'S NO RUSH TO THE LAST PAGE</p><h2>Every good story<br />starts somewhere.</h2></div><p className="steps-intro">A question. A new angle. A little more confidence.</p></div>
            <div className="steps-grid">
              <article className="step-card motion-spotlight tilt-card"><span className="step-no">01</span><span className="step-illustration step-bubble"><MessageCircle size={22} /></span><h3>Bring a question</h3><p>The one you're curious about, or the line you've read twice and still want to understand.</p></article><span className="step-connector">· · · · · →</span>
              <article className="step-card motion-spotlight tilt-card"><span className="step-no">02</span><span className="step-illustration step-book"><BookOpen size={22} /></span><h3>Find another way in</h3><p>Try a hint, read a clear explanation, and let the pattern find its place.</p></article><span className="step-connector">· · · · · →</span>
              <article className="step-card motion-spotlight tilt-card"><span className="step-no">03</span><span className="step-illustration step-sun">✳</span><h3>Keep your bookmark</h3><p>See the small bits of practice adding up, across the places you code.</p></article>
            </div>
            <div className="closing-card motion-spotlight tilt-card"><div className="closing-decoration" aria-hidden="true">✳</div><div><span className="closing-eyebrow">WHENEVER YOU'RE READY</span><h3>There's always<br /><em>another page.</em></h3><p>Take a breath, turn the page, and find a little more room to grow.</p></div><a className="button button-dark" href="#top">Back to the beginning <ArrowRight size={17} /></a><span className="closing-squiggle" aria-hidden="true">〰</span></div>
          </div>
        </section>
      </main>

      <footer className="site-footer"><div className="footer-main"><Brand inverse /><p>A little more clarity.<br />A lot more room to grow.</p><a href="#top" className="footer-top-link">Back to top <ArrowUpRight size={14} /></a></div><div className="footer-bottom"><span>© {new Date().getFullYear()} Re.think(). Made for the in-between moments.</span><span className="footer-disclaimer">{signedIn ? "Live data from your Re.Think account" : "Sign in to connect your own practice data"}</span><span className="footer-thought">Read gently. Keep going. <span>✳</span></span></div></footer>
    </div>
  );
}
