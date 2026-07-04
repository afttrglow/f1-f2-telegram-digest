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
    "Practice",
    "Qualifying",
    "Sprint Race",
    "Feature Race",
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
    "Grand Prix": 8,
    "Race": 8,
}


def fetch_lines(url):
    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0 F1-F2-Telegram-Digest"
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    lines = [
        line.strip()
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]

    return lines


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


def clean_event_name(raw_name):
    raw_name = raw_name.replace("NEXT", "")
    raw_name = raw_name.replace("Races, Qualifying & Practice Sessions", "")
    raw_name = raw_name.replace("Support us, buy us a coffee.", "")
    raw_name = raw_name.replace("Add race dates & times to your Calendar", "")
    raw_name = raw_name.replace("Receive email reminders", "")

    raw_name = re.sub(r"\s+", " ", raw_name).strip()

    return raw_name


def make_datetime(day, month_text, time_text):
    month = MONTHS.get(month_text)

    if not month:
        return None

    hour, minute = map(int, time_text.split(":"))

    return datetime(
        YEAR,
        month,
        int(day),
        hour,
        minute,
        tzinfo=TZ,
    )


def parse_line_event(series, line):
    """
    Handles format like:
    British Grand Prix Free Practice 1 3 Jul 12:30
    """

    session = find_session(line)

    if not session:
        return None

    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2}:\d{2})",
        line,
    )

    if not match:
        return None

    day, month_text, time_text = match.groups()
    start = make_datetime(day, month_text, time_text)

    if not start:
        return None

    before_date = line[:match.start()].strip()

    session_index = before_date.lower().find(session.lower())

    if session_index == -1:
        return None

    event_name = before_date[:session_index].strip()
    event_name = clean_event_name(event_name)

    if not event_name:
        return None

    session = normalize_session(series, session)

    return {
        "series": series,
        "event": event_name,
        "session": session,
        "start": start,
    }


def parse_split_event(series, lines, index):
    """
    Handles format like:
    British Grand Prix Free Practice 1 3 Jul
    12:30
    """

    line = lines[index]

    if index + 1 >= len(lines):
        return None

    next_line = lines[index + 1]

    if not re.match(r"^\d{2}:\d{2}$", next_line):
        return None

    session = find_session(line)

    if not session:
        return None

    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})$",
        line,
    )

    if not match:
        return None

    day, month_text = match.groups()
    start = make_datetime(day, month_text, next_line)

    if not start:
        return None

    before_date = line[:match.start()].strip()

    session_index = before_date.lower().find(session.lower())

    if session_index == -1:
        return None

    event_name = before_date[:session_index].strip()
    event_name = clean_event_name(event_name)

    if not event_name:
        return None

    session = normalize_session(series, session)

    return {
        "series": series,
        "event": event_name,
        "session": session,
        "start": start,
    }


def parse_time_context_event(series, lines, index):
    """
    Handles cases where the time is on its own line and the event/session/date
    are somewhere in the previous few text lines.
    """

    time_line = lines[index]

    if not re.match(r"^\d{2}:\d{2}$", time_line):
        return None

    context = " ".join(lines[max(0, index - 5):index])
    context = re.sub(r"\s+", " ", context).strip()

    session = find_session(context)

    if not session:
        return None

    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})",
        context,
    )

    if not match:
        return None

    day, month_text = match.groups()
    start = make_datetime(day, month_text, time_line)

    if not start:
        return None

    before_date = context[:match.start()].strip()
    session_index = before_date.lower().find(session.lower())

    if session_index == -1:
        return None

    event_name = before_date[:session_index].strip()
    event_name = clean_event_name(event_name)

    if not event_name:
        return None

    session = normalize_session(series, session)

    return {
        "series": series,
        "event": event_name,
        "session": session,
        "start": start,
    }


def parse_events(series, lines):
    events = []

    for i, line in enumerate(lines):
        ignored = [
            "buy us a coffee",
            "support us",
            "email reminders",
            "add race dates",
            "calendar",
        ]

        if any(x in line.lower() for x in ignored):
            continue

        candidates = [
            parse_line_event(series, line),
            parse_split_event(series, lines, i),
            parse_time_context_event(series, lines, i),
        ]

        for event in candidates:
            if event:
                events.append(event)

    # Deduplicate
    unique = {}

    for event in events:
        key = (
            event["series"],
            event["event"],
            event["session"],
            event["start"].isoformat(),
        )
        unique[key] = event

    return list(unique.values())


def get_next_race_window(events):
    now = datetime.now(TZ)

    # Include sessions that started recently, useful if script runs during a race weekend.
    upcoming = [
        event
        for event in events
        if event["start"] >= now - timedelta(hours=6)
    ]

    if not upcoming:
        return []

    upcoming = sorted(upcoming, key=lambda e: e["start"])

    first = upcoming[0]
    window_start = first["start"].date()
    window_end = window_start + timedelta(days=4)

    weekend_events = [
        event
        for event in upcoming
        if window_start <= event["start"].date() <= window_end
    ]

    return sorted(weekend_events, key=lambda e: e["start"])


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


def find_main_title(events):
    f1_events = [event for event in events if event["series"] == "Formula 1"]

    if f1_events:
        return f1_events[0]["event"]

    return events[0]["event"]


def format_message(events):
    now_text = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    if not events:
        return (
            "🏁 <b>F1 / F2 програма</b>\n\n"
            "Не намерих предстоящ уикенд.\n\n"
            "Причината най-вероятно е промяна във формата на календара."
        )

    title = find_main_title(events)

    msg = f"🏁 <b>{html.escape(title)}</b>\n"
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
                key=lambda e: (
                    e["start"],
                    SESSION_ORDER.get(e["session"], 99),
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
        timeout=20,
    )

    response.raise_for_status()


def main():
    all_events = []

    for series, url in SOURCES.items():
        lines = fetch_lines(url)
        parsed = parse_events(series, lines)
        all_events.extend(parsed)

    all_events = sorted(all_events, key=lambda e: e["start"])
    weekend_events = get_next_race_window(all_events)

    message = format_message(weekend_events)
    send_telegram(message)


if __name__ == "__main__":
    main()
