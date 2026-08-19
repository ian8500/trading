export const formatMoney = (value: number | null | undefined, currency = "GBP", digits = 2): string => {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
};

export const formatPercent = (value: number | null | undefined, digits = 2, signed = false): string => {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
};

export const formatNumber = (value: number | null | undefined, digits = 2): string => {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);
};

export const formatPrice = (value: number): string => {
  const digits = Math.abs(value) < 2 ? 5 : Math.abs(value) < 200 ? 2 : 1;
  return new Intl.NumberFormat("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
};

export const formatDateTime = (value: string | null | undefined, includeDate = true): string => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    ...(includeDate ? { day: "2-digit", month: "short", year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
    timeZoneName: "short",
  }).format(date);
};

export const compactDate = (value: string): string => new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  timeZone: "Europe/London",
}).format(new Date(value));

export const humanize = (value: string): string => value
  .toLowerCase()
  .replaceAll("_", " ")
  .replace(/(^|\s)\w/g, (letter) => letter.toUpperCase());

export const pnlTone = (value: number): "positive" | "negative" | "neutral" => (
  value > 0 ? "positive" : value < 0 ? "negative" : "neutral"
);
