const LONDON_TIME_ZONE = "Europe/London";
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

interface DateTimeParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const londonFormatter = new Intl.DateTimeFormat("en-GB-u-ca-iso8601", {
  timeZone: LONDON_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function parseLocalDateTime(value: string): DateTimeParts {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new RangeError("Choose a valid London date and time.");
  const [, year, month, day, hour, minute] = match;
  const parts = {
    year: Number(year),
    month: Number(month),
    day: Number(day),
    hour: Number(hour),
    minute: Number(minute),
  };
  const normalized = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute));
  if (
    normalized.getUTCFullYear() !== parts.year
    || normalized.getUTCMonth() + 1 !== parts.month
    || normalized.getUTCDate() !== parts.day
    || normalized.getUTCHours() !== parts.hour
    || normalized.getUTCMinutes() !== parts.minute
  ) {
    throw new RangeError("Choose a valid London date and time.");
  }
  return parts;
}

function londonPartsAt(timestamp: number): DateTimeParts & { second: number } {
  const values = new Map(
    londonFormatter
      .formatToParts(new Date(timestamp))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  return {
    year: values.get("year") ?? 0,
    month: values.get("month") ?? 0,
    day: values.get("day") ?? 0,
    hour: values.get("hour") ?? 0,
    minute: values.get("minute") ?? 0,
    second: values.get("second") ?? 0,
  };
}

function offsetAt(timestamp: number): number {
  const parts = londonPartsAt(timestamp);
  const representedAsUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return representedAsUtc - Math.floor(timestamp / 1_000) * 1_000;
}

function sameMinute(left: DateTimeParts, right: DateTimeParts): boolean {
  return left.year === right.year
    && left.month === right.month
    && left.day === right.day
    && left.hour === right.hour
    && left.minute === right.minute;
}

/** Convert a wall-clock value entered for Europe/London into an explicit UTC instant. */
export function londonLocalDateTimeToUtcIso(value: string): string {
  const requested = parseLocalDateTime(value);
  const wallClock = Date.UTC(
    requested.year,
    requested.month - 1,
    requested.day,
    requested.hour,
    requested.minute,
  );
  const offsets = new Set([
    offsetAt(wallClock - DAY),
    offsetAt(wallClock),
    offsetAt(wallClock + DAY),
  ]);
  const candidates = [...offsets]
    .map((offset) => wallClock - offset)
    .filter((candidate) => sameMinute(londonPartsAt(candidate), requested))
    .sort((left, right) => left - right);

  if (!candidates.length) {
    throw new RangeError("That London time does not exist because the clocks change then.");
  }

  // A repeated autumn hour has two valid instants; use its first occurrence deterministically.
  return new Date(candidates[0]).toISOString();
}
