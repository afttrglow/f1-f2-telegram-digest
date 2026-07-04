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
            "User-Agent": "Mozilla/5.0 (compatible; F1-F2-Telegram-Digest/2.0)"
        },
    )
    response.raise_for_status()
    return response.text


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def is_time(value):
    return bool(re.match(r"^\d{1,2}:\d{2}$", value.strip()))


def is_date(value):
    return bool(re.match(r"^\d{1,2}\s+[A-Za-z]{3}$", value.strip()))


def parse_date_time(date_text, time_text):
    date_match = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})$", date_text.strip())

    if not date_match:
        return None

    day = int(date_match.group(1))
    month_text = date_match.group(2)
    month = MONTHS.get(month_text)

    if not month:
        return None

    hour, minute = map(int, time_text.strip().split(":"))

    return datetime(
        YEAR,
        month,
        day,
        hour,
        minute,
        tzinfo=TZ,
    )


def find_session(text):
    lowered = text.lower()

    for session in SESSION_NAMES:
        if session.lower() in lowered:
            return session

    return None


def normalize_session(series, session):
    if series == "Formula 1" and session == "Grand Prix":
        return "Race"

    if series == "Formula 2":
        if session == "Sprint":
            return "Sprint Race"
        if session == "Feature":
            return "Feature Race"

    return session


def clean_event_name(value):
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

    result = value

    for phrase in remove_phrases:
        result = result.replace(phrase, "")

    result = clean_text(result)

    return result


def event_name_from_session_text(text, session):
    """
    Example:
    British Grand Prix Free Practice 1 -> British Grand Prix
    Free Practice 1 -> None, because event name comes from current_event
    """

    index = text.lower().find(session.lower())

    if index <= 0:
        return None

    return clean_event_name(text[:index])


def make_event(series, event_name, session, start):
    event_name = clean_event_name(event_name)

    if not event_name or not session or not start:
        return None

    return {
        "series": series,
        "event": event_name,
        "session": normalize_session(series, session),
        "start": start,
    }


def parse_table_rows(series, soup):
    """
    Preferred parser.
    It handles table-like HTML where rows can be:
    British Grand Prix | NEXT
    Free Practice 1    | 3 Jul | 12:30
    """

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
        session = find_session(row_text)

        first_cell = cells[0]

        if "Grand Prix" in first_cell and not session:
            current_event = clean_event_name(first_cell)
            continue

        date_text = next((cell for cell in cells if is_date(cell)), None)
        time_text = next((cell for cell in cells if is_time(cell)), None)

        if not session or not date_text or not time_text:
            continue

        start = parse_date_time(date_text, time_text)

        if not start:
            continue

        event_name = event_name_from_session_text(row_text, session) or current_event

        event = make_event(series, event_name, session, start)

        if event:
            events.append(event)

    return events


def parse_text_lines(series, soup):
    """
    Fallback parser.
    Handles text extraction where content appears as separate lines:
    British Grand Prix
    NEXT
    Free Practice 1
    3 Jul
    12:30
    """

    lines = [
        clean_text(line)
        for line in soup.get_text("\n").splitlines()
        if clean_text(line)
    ]

    events = []
    current_event = None

    for i, line in enumerate(lines):
        ignored = [
            "support us",
            "buy us a coffee",
            "email reminders",
            "add race dates",
            "get calendar",
            "timezones",
        ]

        if any(item in line.lower() for item in ignored):
            continue

        session = find_session(line)

        # Case 1:
        # British Grand Prix
        # NEXT
        if "Grand Prix" in line and not session:
            current_event = clean_event_name(line)
            continue

        # Case 2:
        # Free Practice 1
        # 3 Jul
        # 12:30
        if session and i + 2 < len(lines) and is_date(lines[i + 1]) and is_time(lines[i + 2]):
            start = parse_date_time(lines[i + 1], lines[i + 2])
            event_name = event_name_from_session_text(line, session) or current_event
            event = make_event(series, event_name, session, start)

            if event:
                events.append(event)

            continue

        # Case 3:
        # British Grand Prix Free Practice 1
        # 3 Jul
        # 12:30
        if session and i + 2 < len(lines) and is_date(lines[i + 1]) and is_time(lines[i + 2]):
            start = parse_date_time(lines[i + 1], lines[i + 2])
            event_name = event_name_from_session_text(line, session) or current_event
            event = make_event(series, event_name, session, start)

            if event:
                events.append(event)

            continue

        # Case 4:
        # British Grand Prix Free Practice 1 3 Jul
        # 12:30
        if session and i + 1 < len(lines) and is_time(lines[i + 1]):
            date_match = re.search(r"(\d{1,2}\s+[A-Za-z]{3})$", line)

            if date_match:
                date_text = date_match.group(1)
                text_before_date = clean_text(line[:date_match.start()])
                start = parse_date_time(date_text, lines[i + 1])
                event_name = event_name_from_session_text(text_before_date, session) or current_event
                event = make_event(series, event_name, session, start)

                if event:
                    events.append(event)

                continue

        # Case 5:
        # British Grand Prix Free Practice 1 3 Jul 12:30
        if session:
            full_match = re.search(r"(\d{1,2}\s+[A-Za-z]{3})\s+(\d{1,2}:\d{2})", line)

            if full_match:
                date_text = full_match.group(1)
                time_text = full_match.group(2)
                text_before_date = clean_text(line[:full_match.start()])
                start = parse_date_time(date_text, time_text)
                event_name = event_name_from_session_text(text_before_date, session) or current_event
                event = make_event(series, event_name, session, start)

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
    """
    Choose next/current F1 weekend.
    Then we use its date window to include F2 sessions too.
    """

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

        # Current or future weekend.
        if last_start >= now - timedelta(hours=12):
            candidates.append({
                "event": event_name,
                "first": first_start,
                "last": last_start,
                "events": events,
            })

    if not candidates:
        return None

    candidates = sorted(
        candidates,
        key=lambda item: (
            item["last"] < now,
            abs((item["first"] - now).total_seconds()),
            item["first"],
        ),
    )

    chosen = candidates[0]

    return {
        "title": chosen["event"],
        "start_date": chosen["first"].date(),
        "end_date": chosen["last"].date(),
    }


def select_weekend_events(all_events, weekend):
    if not weekend:
        return []

    # Add one day buffer because F2 can sometimes start earlier.
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


def format_message(events, weekend, debug_info=None):
    now_text = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    if not events or not weekend:
        msg = "🏁 <b>F1 / F2 програма</b>\n\n"
        msg += "Не намерих предстоящ уикенд.\n\n"

        if debug_info:
            msg += "<b>Debug:</b>\n"
            msg += html.escape(debug_info[:3000])

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
                msg += f"• {event['start'].strftime('%H:%M')} - {html.escape(event['session'])}\n"

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

        all_events.extend(events)

        debug_parts.append(f"{series}: parsed {len(events)} events")

        for event in events[:10]:
            debug_parts.append(
                f"- {event['series']} | {event['event']} | "
                f"{event['session']} | {event['start'].strftime('%d.%m %H:%M')}"
            )

    all_events = deduplicate(all_events)

    weekend = choose_f1_weekend(all_events)
    weekend_events = select_weekend_events(all_events, weekend)

    debug_info = "\n".join(debug_parts)

    message = format_message(weekend_events, weekend, debug_info)
    send_telegram(message)


if __name__ == "__main__":
    main()
