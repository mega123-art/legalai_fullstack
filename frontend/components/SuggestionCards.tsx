"use client";

const SUGGESTIONS = [
  {
    title: "SARFAESI Auction",
    text: "Bank auctioned my property under SARFAESI Act without following proper procedure",
  },
  {
    title: "Wrongful Dismissal",
    text: "Employee dismissed without disciplinary inquiry or opportunity to be heard",
  },
  {
    title: "Tenant Eviction",
    text: "Landlord evicted tenant without notice or court order — rights and remedies",
  },
];

interface SuggestionCardsProps {
  onSelect: (text: string) => void;
}

export default function SuggestionCards({ onSelect }: SuggestionCardsProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-2xl">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.title}
          onClick={() => onSelect(s.text)}
          className="text-left p-4 rounded-2xl bg-surface-raised border border-border-subtle hover:bg-surface-card-hover hover:border-border-default transition-all duration-150 cursor-pointer group"
        >
          <p className="text-[13px] font-medium text-fg-default mb-1">
            {s.title}
          </p>
          <p className="text-[12px] text-fg-muted leading-relaxed line-clamp-3">
            {s.text}
          </p>
        </button>
      ))}
    </div>
  );
}
