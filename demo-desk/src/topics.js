import { TOPICS } from "./content.js";

const TOPIC_RULES = {
  gas: {
    categoryTerms: ["gas prices", "gas price", "gasoline", "natural gas"],
    textTerms: ["gas prices", "gas price", "gasoline", "natural gas"],
  },
  elections: {
    categoryTerms: ["elections"],
    textTerms: ["election", "elections", "primary", "primaries", "ballot", "ballots", "vote", "votes"],
  },
  culture: {
    categoryTerms: ["culture"],
    textTerms: ["culture", "film", "films", "movie", "movies", "music", "award", "awards", "grammy", "grammys", "oscar", "oscars", "emmy", "emmys", "television"],
  },
  crypto: {
    categoryTerms: ["crypto", "cryptocurrency"],
    textTerms: ["crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth", "solana", "xrp", "dogecoin", "doge"],
  },
  golf: {
    categoryTerms: ["golf"],
    textTerms: ["golf", "pga", "lpga", "liv golf"],
  },
};

function normalized(value) {
  return String(value ?? "").toLowerCase().replaceAll(/[^a-z0-9]+/g, " ").trim();
}

function containsPhrase(text, phrase) {
  const normalizedText = ` ${normalized(text)} `;
  const normalizedPhrase = ` ${normalized(phrase)} `;
  return normalizedPhrase !== "  " && normalizedText.includes(normalizedPhrase);
}

export function topicMatchesEvent(event, topicId) {
  const rule = TOPIC_RULES[topicId];
  if (!rule || !event) return false;

  const category = normalized(event.category);
  if (rule.categoryTerms.some((term) => category === normalized(term))) return true;

  const fields = [
    event.title,
    event.sub_title,
    event.subtitle,
    event.event_ticker,
    event.series_ticker,
    ...(Array.isArray(event.markets)
      ? event.markets.flatMap((market) => [market?.title, market?.subtitle, market?.yes_sub_title, market?.no_sub_title, market?.ticker])
      : []),
  ];
  const text = fields.filter(Boolean).join(" ");
  return rule.textTerms.some((term) => containsPhrase(text, term));
}

export function matchingTopics(event) {
  return Object.keys(TOPICS).filter((topicId) => topicMatchesEvent(event, topicId));
}

export function topicDefinition(topicId) {
  return TOPICS[topicId] ?? null;
}

export function topicRuleIds() {
  return Object.keys(TOPIC_RULES);
}
