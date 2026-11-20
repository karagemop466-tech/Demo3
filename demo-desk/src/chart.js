import { escapeHTML, finiteNumber, formatPrice } from "./utils.js";

const histories = new Map();
const MAX_HISTORY_PER_MARKET = 8000;

export function recordPriceSample(ticker, price, timestamp = Date.now()) {
  const numericPrice = finiteNumber(price);
  const numericTimestamp = finiteNumber(timestamp);
  if (!ticker || numericPrice === null || numericTimestamp === null) return;

  const samples = histories.get(ticker) ?? [];
  const last = samples.at(-1);
  if (last && last.timestamp === numericTimestamp) {
    last.price = numericPrice;
  } else {
    samples.push({ timestamp: numericTimestamp, price: numericPrice, origin: "REST observation" });
  }

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const kept = samples.filter((sample) => sample.timestamp >= cutoff).slice(-MAX_HISTORY_PER_MARKET);
  histories.set(ticker, kept);
}

export function localPriceSamples(ticker, windowMs, now = Date.now()) {
  const cutoff = now - windowMs;
  return (histories.get(ticker) ?? []).filter((sample) => sample.timestamp >= cutoff && sample.timestamp <= now);
}

export function mergePriceSeries(candles, samples, windowMs, now = Date.now()) {
  const cutoff = now - windowMs;
  const points = [];
  for (const candle of candles ?? []) {
    const time = finiteNumber(candle?.end_period_ts);
    const price = finiteNumber(candle?.price?.close_dollars ?? candle?.price?.close);
    if (time === null || price === null) continue;
    const timestamp = time < 1e12 ? time * 1000 : time;
    if (timestamp >= cutoff && timestamp <= now) {
      points.push({ timestamp, price, origin: "Kalshi candle" });
    }
  }
  for (const sample of samples ?? []) {
    if (sample.timestamp >= cutoff && sample.timestamp <= now) points.push(sample);
  }
  const byTime = new Map();
  for (const point of points) byTime.set(point.timestamp, point);
  return [...byTime.values()].sort((a, b) => a.timestamp - b.timestamp);
}

function displayTime(timestamp, windowMs) {
  const date = new Date(timestamp);
  const options = windowMs >= 6 * 60 * 60 * 1000
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : windowMs <= 5 * 60 * 1000
      ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" };
  return new Intl.DateTimeFormat("en-US", options).format(date);
}

function decimate(points, maxPoints = 180) {
  if (points.length <= maxPoints) return points;
  const selected = [];
  const stride = (points.length - 1) / (maxPoints - 1);
  for (let i = 0; i < maxPoints; i += 1) selected.push(points[Math.round(i * stride)]);
  return selected;
}

export function renderPriceChart(container, points, windowMs, now = Date.now()) {
  if (!container) return;
  if (!Array.isArray(points) || points.length === 0) {
    container.innerHTML = '<div class="empty-state chart-empty"><strong>No price observations yet</strong><span>Wait for the public demo quote, or select another market. No sample values are shown.</span></div>';
    return;
  }

  const width = 920;
  const height = 340;
  const padding = { top: 20, right: 26, bottom: 50, left: 86 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const visible = decimate(points);
  const values = visible.map((point) => point.price);
  const minTime = now - windowMs;
  const maxTime = now;
  let minPrice = Math.min(...values);
  let maxPrice = Math.max(...values);
  const rawRange = maxPrice - minPrice;
  const paddingY = rawRange === 0 ? Math.max(Math.abs(maxPrice) * 0.02, 0.01) : rawRange * 0.16;
  minPrice -= paddingY;
  maxPrice += paddingY;

  const xAt = (timestamp) => padding.left + ((timestamp - minTime) / (maxTime - minTime || 1)) * plotWidth;
  const yAt = (price) => padding.top + ((maxPrice - price) / (maxPrice - minPrice || 1)) * plotHeight;
  const path = visible.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(point.timestamp).toFixed(2)},${yAt(point.price).toFixed(2)}`).join(" ");
  const gridCount = 4;
  const grid = Array.from({ length: gridCount + 1 }, (_, index) => {
    const fraction = index / gridCount;
    const y = padding.top + fraction * plotHeight;
    const price = maxPrice - fraction * (maxPrice - minPrice);
    return `<g class="chart-grid"><line class="chart-grid-line" x1="${padding.left}" y1="${y.toFixed(2)}" x2="${(width - padding.right).toFixed(2)}" y2="${y.toFixed(2)}"/><text class="chart-y-tick" x="${(padding.left - 12).toFixed(2)}" y="${(y + 4).toFixed(2)}" text-anchor="end">${escapeHTML(formatPrice(price))}</text></g>`;
  }).join("");

  const last = visible.at(-1);
  const xLabels = `<text class="chart-x-tick" x="${padding.left}" y="${height - 14}" text-anchor="start">${escapeHTML(displayTime(minTime, windowMs))}</text><text class="chart-x-tick" x="${width - padding.right}" y="${height - 14}" text-anchor="end">${escapeHTML(displayTime(maxTime, windowMs))}</text>`;
  const markers = visible.length <= 64
    ? visible.map((point) => `<circle class="chart-point" cx="${xAt(point.timestamp).toFixed(2)}" cy="${yAt(point.price).toFixed(2)}" r="3"><title>${escapeHTML(displayTime(point.timestamp, windowMs))} · ${escapeHTML(formatPrice(point.price))} · ${escapeHTML(point.origin)}</title></circle>`).join("")
    : "";
  const lastX = xAt(last.timestamp);
  const lastY = yAt(last.price);

  container.innerHTML = `
    <svg class="price-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="YES last price versus observation time">
      <text class="chart-y-label" transform="translate(18 ${height / 2}) rotate(-90)" text-anchor="middle">YES last price · USD</text>
      ${grid}
      <path class="chart-line" d="${path}"/>
      ${markers}
      <circle class="chart-latest" cx="${lastX.toFixed(2)}" cy="${lastY.toFixed(2)}" r="5"><title>Latest ${escapeHTML(formatPrice(last.price))}</title></circle>
      <text class="chart-axis-label" x="${width / 2}" y="${height - 2}" text-anchor="middle">Observation time · local</text>
      ${xLabels}
    </svg>
  `;
}
