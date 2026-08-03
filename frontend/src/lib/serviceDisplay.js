export function resolveDeliveryValue(service) {
  if (!service || typeof service !== "object") return null;
  const candidates = [
    service.delivery_minutes,
    service.delivery_time,
    service.average_time,
    service.average,
    service.speed,
    service.delivery,
    service.expected_time,
    service.start_time,
    service.start,
    service.time,
  ];
  for (const value of candidates) {
    if (value === null || value === undefined || value === "") continue;
    return value;
  }
  return null;
}

export function formatDeliveryLabel(value) {
  if (value === null || value === undefined || value === "") return "—";

  if (typeof value === "number") {
    const minutes = Number(value);
    if (!Number.isFinite(minutes) || minutes < 0) return "—";
    return formatMinutes(minutes);
  }

  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return "—";
    const lowered = text.toLowerCase();
    if (lowered === "instant" || lowered === "now" || lowered === "immediate") return "Instant";

    const hourMinute = text.match(/(\d+)\s*(?:h|hr|hrs|hour|hours)\s*(?:and\s*)?(\d+)\s*(?:m|min|mins|minute|minutes)/i);
    if (hourMinute) {
      return formatMinutes(Number(hourMinute[1]) * 60 + Number(hourMinute[2]));
    }

    const hoursOnly = text.match(/(\d+)\s*(?:h|hr|hrs|hour|hours)/i);
    if (hoursOnly) {
      return formatMinutes(Number(hoursOnly[1]) * 60);
    }

    const minutesOnly = text.match(/(\d+)\s*(?:m|min|mins|minute|minutes)/i);
    if (minutesOnly) {
      return formatMinutes(Number(minutesOnly[1]));
    }

    const dayOnly = text.match(/(\d+)\s*(?:d|day|days)/i);
    if (dayOnly) {
      return formatMinutes(Number(dayOnly[1]) * 60 * 24);
    }

    const range = text.match(/(\d+)\s*-\s*(\d+)\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)/i);
    if (range) {
      const high = Number(range[2]);
      const unit = text.match(/(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)$/i);
      const minutes = unit ? parseUnitMinutes(high, unit[0]) : null;
      return minutes == null ? "—" : formatMinutes(minutes);
    }
  }

  return "—";
}

function formatMinutes(minutes) {
  const total = Number(minutes);
  if (!Number.isFinite(total) || total < 0) return "—";
  if (total === 0) return "Instant";
  if (total < 60) return `${total} min`;
  const hrs = Math.floor(total / 60);
  const mins = total % 60;
  if (mins === 0) return hrs === 1 ? "1 hr" : `${hrs} hrs`;
  return `${hrs}h ${mins}m`;
}

function parseUnitMinutes(value, unit) {
  const lower = unit.toLowerCase();
  if (lower.startsWith("h")) return value * 60;
  if (lower.startsWith("d")) return value * 60 * 24;
  return value;
}
