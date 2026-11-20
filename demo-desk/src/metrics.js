import { compareNullableDescending, finiteNumber } from "./utils.js";

const YES_NO_RESULTS = new Set(["yes", "no"]);

export function isActiveMarket(market) {
  return market?.status === "active";
}

export function activeMarketsForEvent(event) {
  return Array.isArray(event?.markets) ? event.markets.filter(isActiveMarket) : [];
}

export function sumMarketField(markets, field) {
  if (!Array.isArray(markets) || markets.length === 0) return null;
  let sum = 0;
  for (const market of markets) {
    const value = finiteNumber(market?.[field]);
    // A partial sum would understate the event total. Keep it blank unless
    // every active child-market value needed for the aggregate is confirmed.
    if (value === null) return null;
    sum += value;
  }
  return sum;
}

export function aggregateEvent(event, marketFilter = isActiveMarket) {
  const markets = Array.isArray(event?.markets) ? event.markets.filter(marketFilter) : [];
  return {
    event,
    markets,
    marketCount: markets.length,
    volume24hContracts: sumMarketField(markets, "volume_24h_fp"),
    openInterestContracts: sumMarketField(markets, "open_interest_fp"),
    totalVolumeContracts: sumMarketField(markets, "volume_fp"),
  };
}

export function sortEventAggregates(rows, sortMode = "volume") {
  const field = sortMode === "openInterest" ? "openInterestContracts" : "volume24hContracts";
  return [...rows].sort((a, b) => {
    const metricOrder = compareNullableDescending(a[field], b[field]);
    if (metricOrder !== 0) return metricOrder;
    return String(a.event?.title ?? "").localeCompare(String(b.event?.title ?? ""));
  });
}

export function resolutionDetails(market) {
  const status = String(market?.status ?? "").toLowerCase();
  const result = String(market?.result ?? "").toLowerCase();
  const hasYesNoResult = YES_NO_RESULTS.has(result);

  if (status === "finalized") {
    if (hasYesNoResult) {
      return {
        key: "resolved",
        label: `Finalized · ${result.toUpperCase()}`,
        isYesNoResolved: true,
        result,
      };
    }
    if (result === "scalar") {
      return { key: "scalar", label: "Finalized · scalar", isYesNoResolved: false, result };
    }
    return { key: "finalized-unverified", label: "Finalized · result unavailable", isYesNoResolved: false, result: null };
  }

  if (status === "determined") {
    if (result === "scalar") {
      return { key: "determined-scalar", label: "Determined · scalar; settlement pending", isYesNoResolved: false, result };
    }
    return {
      key: "determined",
      label: `Determined${hasYesNoResult ? ` · ${result.toUpperCase()}` : ""} · settlement pending`,
      isYesNoResolved: false,
      result: hasYesNoResult ? result : null,
    };
  }

  if (status === "disputed") {
    return { key: "disputed", label: "Disputed · review pending", isYesNoResolved: false, result: hasYesNoResult ? result : null };
  }
  if (status === "amended") {
    return { key: "amended", label: "Amended · settlement pending", isYesNoResolved: false, result: hasYesNoResult ? result : null };
  }
  if (status === "closed") {
    return { key: "closed", label: "Closed · awaiting determination", isYesNoResolved: false, result: null };
  }
  if (status === "inactive") {
    return { key: "paused", label: "Paused", isYesNoResolved: false, result: null };
  }
  if (status === "active") {
    return { key: "active", label: "Active", isYesNoResolved: false, result: null };
  }
  if (status === "initialized") {
    return { key: "initialized", label: "Not open yet", isYesNoResolved: false, result: null };
  }

  return { key: "unknown", label: status || "Status unavailable", isYesNoResolved: false, result: null };
}

export function isInResolutionQueue(market) {
  return ["closed", "determined", "disputed", "amended", "finalized"].includes(String(market?.status ?? "").toLowerCase());
}
