import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import DancingText from "./DancingText";

type Quote = {
  text: string;
  note: string;
};

const quotes: Quote[] = [
  { text: "You can read a line a dozen ways before it becomes your own.", note: "An original Re.think() margin note" },
  { text: "A good question is a door, not a confession.", note: "A note for the curious" },
  { text: "You do not have to finish the chapter to have learned something.", note: "For the in-between moments" },
  { text: "A second look is still progress.", note: "An original Re.think() margin note" },
  { text: "Your pace is not a problem to solve.", note: "For today, and the next page" },
  { text: "The answer can wait. Let the idea catch up.", note: "A note for the curious" },
  { text: "Curiosity is a gentle kind of courage.", note: "An original Re.think() margin note" },
  { text: "A small question can open a very large door.", note: "For the in-between moments" },
  { text: "You can be new at something and already be good at returning.", note: "For today, and the next page" },
  { text: "When a page looks unfamiliar, begin with one line.", note: "An original Re.think() margin note" },
  { text: "Progress is not only what you solve. It is what you understand.", note: "A note for the curious" },
  { text: "Rest is part of every good reading.", note: "For the in-between moments" },
  { text: "You do not need the whole path—just the next thing you wonder about.", note: "For today, and the next page" },
  { text: "Every clear explanation leaves room for another good question.", note: "An original Re.think() margin note" },
  { text: "A problem is a page, not a verdict.", note: "A note for the curious" },
  { text: "A little practice is still a promise kept.", note: "For the in-between moments" },
  { text: "The hard chapter is still part of the story.", note: "An original Re.think() margin note" },
  { text: "Let understanding arrive in its own handwriting.", note: "For today, and the next page" },
  { text: "There is more than one way into a good idea.", note: "A note for the curious" },
  { text: "Small steps make spacious futures.", note: "For the in-between moments" },
  { text: "You are allowed to learn something slowly.", note: "An original Re.think() margin note" },
  { text: "The page does not ask you to be finished—only to stay curious.", note: "For today, and the next page" },
  { text: "Knowing what to ask is part of knowing more.", note: "A note for the curious" },
  { text: "Close the book for a while. The thought can come with you.", note: "For the in-between moments" },
];

function quoteIndexForDate(date: Date): number {
  const utcDay = Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000);
  return ((utcDay % quotes.length) + quotes.length) % quotes.length;
}

function dateLabel(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(date);
}

export default function DailyQuote() {
  const [quoteIndex, setQuoteIndex] = useState(() => quoteIndexForDate(new Date()));
  const [today, setToday] = useState(() => new Date());
  const quote = quotes[quoteIndex];

  useEffect(() => {
    let timer = 0;
    const scheduleMidnightRefresh = () => {
      const now = new Date();
      const nextMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      timer = window.setTimeout(() => {
        const newDay = new Date();
        setToday(newDay);
        setQuoteIndex(quoteIndexForDate(newDay));
        scheduleMidnightRefresh();
      }, Math.max(1_000, nextMidnight.getTime() - now.getTime() + 50));
    };
    scheduleMidnightRefresh();
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <section className="quote-section" aria-label="Daily quote">
      <div className="quote-page-lines" aria-hidden="true" />
      <div className="quote-content quote-card motion-spotlight tilt-card" id="daily-note">
        <div className="quote-topline">
          <span className="quote-eyebrow"><DancingText text="YOUR DAILY READING MOMENT" /></span>
          <span className="quote-date">{dateLabel(today)}</span>
        </div>
        <span className="big-quote-mark" aria-hidden="true">“</span>
        <blockquote className="daily-quote-line" key={quoteIndex} aria-live="polite">{quote.text}</blockquote>
        <span className="quote-byline">{quote.note}</span>
        <div className="quote-footer-row">
          <span className="quote-progress" aria-hidden="true"><span /><span /><span /><span /><span /></span>
          <button className="quote-refresh" type="button" onClick={() => setQuoteIndex((current) => (current + 1) % quotes.length)} aria-label="Show another original Re.think() quote">
            <RefreshCw size={14} /> Another line <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
