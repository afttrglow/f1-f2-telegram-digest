import os
import re
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TZ = ZoneInfo("Europe/Sofia")
YEAR = datetime.now(TZ).year

SOURCES = {
    "Formula 1": "https://f1calendar.com/timezone/Europe-Sofia",
    "Formula 2": "https://f2calendar.com/timezone/Europe-Sofia",
}

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

SESSION_NAMES = [
    "Sprint Qualifying",
    "Free Practice 1",
    "Free Practice 2",
    "Free Practice 3",
    "Sprint Race",
    "Feature Race",
    "Qualifying",
    "Practice",
    "Sprint",
    "Feature",
    "Grand Prix",
]

SESSION_ORDER = {
    "Practice": 1,
    "Free Practice 1": 1,
    "Free Practice 2": 2,
    "Free Practice 3": 3,
    "Sprint Qualifying": 4,
    "Qualifying": 5,
    "Sprint": 6,
    "Sprint Race": 6,
    "Feature": 7,
    "Feature Race": 7,
    "Race": 8,
    "Grand Prix": 8,
}


def fetch_html(url):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; F1-F2-Telegram-Digest/3.0)"
        },
    )
    response.raise_for_status()
    return response.text


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_event_name(value):
    if not value:
        return ""

    result = str(value)

    remove_phrases = [
        "NEXT",
        "Races, Qualifying & Practice Sessions",
        "Support us, buy us a coffee.",
        "Add race dates & times to your Calendar",
        "Receive email reminders",
        "Toggle F1 Calendar",
        "Toggle F2 Calendar",
        "Date",
        "Time",
    ]

    for phrase in remove_phrases:
        result = result.replace(phrase, "")

    return clean_text(result)


def is_time(value):
    return bool(re.match(r"^\d{1,2}:\d{2}$", clean_text(value)))


def is_date(value):
    return bool(re.match(r"^\d{1,2}\s+[A-Za-z]{3}$", clean_text(value)))


def has_date_time(value):
    return bool(re.search(r"\d{1,2}\s+[A-Za-z]{3}\s+\d{1,2}:\d{2}", value))


def has_date_only_at_end(value):
    return bool(re.search(r"\d{1,2}\s+[A-Za-z]{3}$", value))


def parse_date_time(date_text, time_text):
    date_match = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})$", clean_text(date_text))

    if not date_match:
        return None

    day = int(date_match.group(1))
    month_text = date_match.group(2)
    month = MONTHS.get(month_text)

    if not month:
        return None

    hour, minute = map(int, clean_text(time_text).split(":"))

    return datetime(
        YEAR,
        month,
        day,
        hour,
        minute,
        tzinfo=TZ,
    )


def find_session(text):
    lowered = clean_text(text).lower()

    for session in SESSION_NAMES:
        if session.lower() in lowered:
            return session

    return None


def is_standalone_event_name(line):
    line = clean_event_name(line)

    if not line:
        return False

    lower = line.lower()

    if has_date_time(line) or has_date_only_at_end(line) or is_time(line):
        return False

    technical_words = [
        "practice",
        "qualifying",
        "sprint",
        "feature",
        "race",
        "calendar",
        "reminders",
        "support",
        "coffee",
    ]

    if any(word in lower for word in technical_words):
        return False

    return "grand prix" in lower


def normalize_session(series, session):
    if series == "Formula 1" and session == "Grand Prix":
        return "Race"

    if series == "Formula 2":
        if session == "Sprint":
            return "Sprint Race"
        if session == "Feature":
            return "Feature Race"

    return session


def event_name_from_text(text, session, current_event=None):
    text = clean_text(text)
    session = clean_text(session)

    if not text or not session:
        return current_event or ""

    lower_text = text.lower()
    lower_session = session.lower()

    # Important: use rfind, not find.
    # Example: "British Grand Prix Grand Prix"
    # The last "Grand Prix" is the session, the first one is part of the race name.
    index = lower_text.rfind(lower_session)

    if index > 0:
        return clean_event_name(text[:index])

    if current_event:
        return clean_event_name(current_event)

    return ""


def make_event(series, event_name, session, start):
    if not event_name or not session or not start:
        return None

    event_name = clean_event_name(event_name)

    if not event_name:
        return None

    return {
        "series": series,
        "event": event_name,
        "session": normalize_session(series, session),
        "start": start,
    }


def parse_compact_line(series, line, current_event=None):
    """
    Handles:
    British Grand Prix Free Practice 1 3 Jul 12:30
    British Grand Prix Grand Prix 5 Jul 17:00
    Free Practice 1 3 Jul 12:30
    """

    line = clean_text(line)
    session = find_session(line)

    if not session:
        return None

    match = re.search(r"(\d{1,2}\s+[A-Za-z]{3})\s+(\d{1,2}:\d{2})", line)

    if not match:
        return None

    date_text = match.group(1)
    time_text = match.group(2)
    text_before_date = clean_text(line[:match.start()])

    start = parse_date_time(date_text, time_text)

    if not start:
        return None

    event_name = event_name_from_text(text_before_date, session, current_event)

    # Special case:
    # "British Grand Prix 5 Jul 17:00"
    # The only "Grand Prix" is the race name, but also session name.
    if not event_name and session == "Grand Prix":
        event_name = current_event or text_before_date

    return make_event(series, event_name, session, start)


def parse_split_line(series, lines, index, current_event=None):
    """
    Handles:
    British Grand Prix Free Practice 1 3 Jul
    12:30
    """

    line = clean_text(lines[index])

    if index + 1 >= len(lines):
        return None

    next_line = clean_text(lines[index + 1])

    if not is_time(next_line):
        return None

    session = find_session(line)

    if not session:
        return None

    match = re.search(r"(\d{1,2}\s+[A-Za-z]{3})$", line)

    if not match:
        return None

    date_text = match.group(1)
    text_before_date = clean_text(line[:match.start()])

    start = parse_date_time(date_text, next_line)

    if not start:
        return None

    event_name = event_name_from_text(text_before_date, session, current_event)

    if not event_name and session == "Grand Prix":
        event_name = current_event or text_before_date

    return make_event(series, event_name, session, start)


def parse_three_line_block(series, lines, index, current_event=None):
    """
    Handles:
    Free Practice 1
    3 Jul
    12:30

    Or:
    British Grand Prix Free Practice 1
    3 Jul
    12:30
    """

    line = clean_text(lines[index])

    if index + 2 >= len(lines):
        return None

    date_line = clean_text(lines[index + 1])
    time_line = clean_text(lines[index + 2])

    if not is_date(date_line) or not is_time(time_line):
        return None

    session = find_session(line)

    if not session:
        return None

    start = parse_date_time(date_line, time_line)

    if not start:
        return None

    event_name = event_name_from_text(line, session, current_event)

    if not event_name:
        event_name = current_event or ""

    return make_event(series, event_name, session, start)


def parse_table_rows(series, soup):
    events = []
    current_event = None

    rows = soup.find_all("tr")

    for row in rows:
        cells = [
            clean_text(cell.get_text(" "))
            for cell in row.find_all(["td", "th"])
        ]
        cells = [cell for cell in cells if cell]

        if not cells:
            continue

        row_text = clean_text(" ".join(cells))

        if is_standalone_event_name(row_text):
            current_event = clean_event_name(row_text)
            continue

        session = find_session(row_text)

        if not session:
            continue

        date_text = next((cell for cell in cells if is_date(cell)), None)
        time_text = next((cell for cell in cells if is_time(cell)), None)

        if not date_text or not time_text:
            event = parse_compact_line(series, row_text, current_event)

            if event:
                events.append(event)

            continue

        start = parse_date_time(date_text, time_text)

        if not start:
            continue

        event_name = event_name_from_text(row_text, session, current_event)

        if not event_name:
            event_name = current_event or ""

        event = make_event(series, event_name, session, start)

        if event:
            events.append(event)

    return events


def parse_text_lines(series, soup):
    lines = [
        clean_text(line)
        for line in soup.get_text("\n").splitlines()
        if clean_text(line)
    ]

    events = []
    current_event = None

    ignored_phrases = [
        "support us",
        "buy us a coffee",
        "email reminders",
        "add race dates",
        "get calendar",
        "timezones",
        "your calendar",
        "cookies",
        "privacy",
    ]

    for i, line in enumerate(lines):
        lower = line.lower()

        if any(phrase in lower for phrase in ignored_phrases):
            continue

        if is_standalone_event_name(line):
            current_event = clean_event_name(line)
            continue

        parsers = [
            parse_compact_line(series, line, current_event),
            parse_split_line(series, lines, i, current_event),
            parse_three_line_block(series, lines, i, current_event),
        ]

        for event in parsers:
            if event:
                events.append(event)

    return events


def deduplicate(events):
    unique = {}

    for event in events:
        key = (
            event["series"],
            event["event"],
            event["session"],
            event["start"].isoformat(),
        )
        unique[key] = event

    return sorted(unique.values(), key=lambda item: item["start"])


def parse_events(series, html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    table_events = parse_table_rows(series, soup)
    text_events = parse_text_lines(series, soup)

    return deduplicate(table_events + text_events)


def choose_f1_weekend(all_events):
    now = datetime.now(TZ)

    f1_events = [
        event for event in all_events
        if event["series"] == "Formula 1"
    ]

    grouped = defaultdict(list)

    for event in f1_events:
        grouped[event["event"]].append(event)

    candidates = []

    for event_name, events in grouped.items():
        events = sorted(events, key=lambda item: item["start"])

        first_start = events[0]["start"]
        last_start = events[-1]["start"]

        if last_start >= now - timedelta(hours=12):
            candidates.append({
                "event": event_name,
                "first": first_start,
                "last": last_start,
            })

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda item: item["first"])

    chosen = candidates[0]

    return {
        "title": chosen["event"],
        "start_date": chosen["first"].date(),
        "end_date": chosen["last"].date(),
    }


def select_weekend_events(all_events, weekend):
    if not weekend:
        return []

    start_date = weekend["start_date"] - timedelta(days=1)
    end_date = weekend["end_date"] + timedelta(days=1)

    selected = [
        event for event in all_events
        if start_date <= event["start"].date() <= end_date
    ]

    return sorted(selected, key=lambda item: item["start"])


def bg_day(dt):
    days = {
        "Monday": "Понеделник",
        "Tuesday": "Вторник",
        "Wednesday": "Сряда",
        "Thursday": "Четвъртък",
        "Friday": "Петък",
        "Saturday": "Събота",
        "Sunday": "Неделя",
    }

    return days.get(dt.strftime("%A"), dt.strftime("%A"))


def format_debug(debug_parts):
    debug_text = "\n".join(debug_parts)
    return html.escape(debug_text[:3000])


def format_message(events, weekend, debug_parts=None):
    now_text = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    if not events or not weekend:
        msg = "🏁 <b>F1 / F2 програма</b>\n\n"
        msg += "Не намерих предстоящ уикенд.\n\n"

        if debug_parts:
            msg += "<b>Debug:</b>\n"
            msg += format_debug(debug_parts)

        return msg

    msg = f"🏁 <b>{html.escape(weekend['title'])}</b>\n"
    msg += "🇧🇬 <b>Българско време</b>\n"
    msg += f"🕘 Обновено: {now_text}\n\n"

    by_series = defaultdict(list)

    for event in events:
        by_series[event["series"]].append(event)

    for series in ["Formula 1", "Formula 2"]:
        if series not in by_series:
            continue

        msg += "━━━━━━━━━━━━━━\n"
        msg += f"🏎 <b>{series}</b>\n\n"

        by_day = defaultdict(list)

        for event in by_series[series]:
            by_day[event["start"].date()].append(event)

        for day in sorted(by_day):
            day_events = sorted(
                by_day[day],
                key=lambda item: (
                    item["start"],
                    SESSION_ORDER.get(item["session"], 99),
                ),
            )

            msg += f"📅 <b>{bg_day(day_events[0]['start'])} - {day.strftime('%d.%m')}</b>\n"

            for event in day_events:
                time_text = event["start"].strftime("%H:%M")
                session_text = html.escape(event["session"])
                msg += f"• {time_text} - {session_text}\n"

            msg += "\n"

    msg += "Източници: f1calendar.com / f2calendar.com"

    return msg


def send_telegram(message):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


def main():
    all_events = []
    debug_parts = []

    for series, url in SOURCES.items():
        html_text = fetch_html(url)
        events = parse_events(series, html_text)

        debug_parts.append(f"{series}: parsed {len(events)} events")

        for event in events[:20]:
            debug_parts.append(
                f"- {event['series']} | {event['event']} | "
                f"{event['session']} | {event['start'].strftime('%d.%m %H:%M')}"
            )

        all_events.extend(events)

    all_events = deduplicate(all_events)

    weekend = choose_f1_weekend(all_events)
    weekend_events = select_weekend_events(all_events, weekend)

    if weekend:
        debug_parts.append(
            f"Chosen weekend: {weekend['title']} "
            f"{weekend['start_date']} - {weekend['end_date']}"
        )
    else:
        debug_parts.append("Chosen weekend: NONE")

    message = format_message(weekend_events, weekend, debug_parts)
    send_telegram(message)


if __name__ == "__main__":
    main()
