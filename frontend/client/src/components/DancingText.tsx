type DancingTextProps = {
  text: string;
  className?: string;
};

export default function DancingText({ text, className = "" }: DancingTextProps) {
  return (
    <span className={`dancing-text ${className}`.trim()}>
      <span className="sr-only">{text}</span>
      <span className="dancing-letters" aria-hidden="true">
        {Array.from(text).map((character, index) => (
          <span key={`${character}-${index}`} style={{ animationDelay: `${index * 18}ms` }}>
            {character === " " ? "\u00a0" : character}
          </span>
        ))}
      </span>
    </span>
  );
}
