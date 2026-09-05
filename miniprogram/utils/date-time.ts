const DATE_TIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})([T ])(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$/;
const SHANGHAI_OFFSET_MINUTES = 8 * 60;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function validDateTime(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
): boolean {
  if (year < 1000 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return false;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return day >= 1 && day <= daysInMonth;
}

/**
 * API datetimes without an offset are UTC because the server stores naive UTC.
 * Legacy preview values with a space separator already represent Shanghai time.
 */
export function formatShanghaiDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const match = DATE_TIME_PATTERN.exec(value.trim());
  if (!match) return "—";

  const [, yearText, monthText, dayText, separator, hourText, minuteText, secondText = "0", fraction = "", zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (!validDateTime(year, month, day, hour, minute, second)) return "—";

  let sourceOffsetMinutes = 0;
  if (zone && zone !== "Z") {
    const sign = zone[0] === "+" ? 1 : -1;
    const offsetHour = Number(zone.slice(1, 3));
    const offsetMinute = Number(zone.slice(4, 6));
    if (offsetHour > 14 || offsetMinute > 59 || (offsetHour === 14 && offsetMinute > 0)) return "—";
    sourceOffsetMinutes = sign * (offsetHour * 60 + offsetMinute);
  } else if (!zone && separator === " ") {
    sourceOffsetMinutes = SHANGHAI_OFFSET_MINUTES;
  }

  const milliseconds = Number(fraction.slice(0, 3).padEnd(3, "0"));
  const timestamp = Date.UTC(year, month - 1, day, hour, minute, second, milliseconds)
    - sourceOffsetMinutes * 60 * 1000;
  const shanghai = new Date(timestamp + SHANGHAI_OFFSET_MINUTES * 60 * 1000);

  return `${shanghai.getUTCFullYear()}-${pad(shanghai.getUTCMonth() + 1)}-${pad(shanghai.getUTCDate())} ${pad(shanghai.getUTCHours())}:${pad(shanghai.getUTCMinutes())}`;
}
