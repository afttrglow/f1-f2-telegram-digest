import os
import re
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from collections import defaultdict
import pytz

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TZ = pytz.timezone("Europe/Sofia")
YEAR = datetime.now(TZ).year

SOURCES = {
    "Formula 1": "https://f1calendar.com/timezone/Europe-Sofia",
    "Formula 2": "https://f2calendar.com/timezone/Europe-Sofia",
}

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

SESSION_ORDER = {
    "Free Practice 1": 1,
    "Free Practice 2": 2,
    "Free Practice 3": 3,
    "Practice": 1,
    "Sprint Qualifying": 2,
    "Qualifying": 3,
    "Sprint": 4,
    "Grand Prix": 5,
    "Feature": 5,
}

def fetch_lines(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]

def parse_date(date_text, time_text):
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", date_text)
    if not match:
        return None

    day = int(match.group(1))
    month = MONTHS.get(match.group(2))
    if not month:
        return None

    hour, minute = map(int, time_text.split(":"))
    return TZ.localize(datetime(YEAR, month, day, hour, minute))

def detect_session(title):
    session_names = [
        "Sprint Qualifying",
        "Free Practice 1",
        "Free Practice 2",
        "Free Practice 3",
        "Qualifying",
        "Practice",
        "Sprint",
        "Feature",
        "Grand Prix",
    ]

    for session in session_names:
        if session in title:
            return session

    return None

def clean_event_name(title, session):
    event = title.replace(session, "").strip()
    event = re.sub(r"\s+", " ", event)
    return event

def parse_events(series, lines):
    events = []

    for i, line in enumerate(lines[:-1]):
        session = detect_session(line)
        if not session:
            continue

        date_match = re.search(r"(\d{1,2}\s+[A-Za-z]{3})$", line)
        if not date_match:
            continue

        if not re.match(r"^\d{2}:\d{2}$", lines[i + 1]):
            continue

        date_text = date_match.group(1)
        title = line[:date_match.start()].strip()
        start = parse_date(date_text, lines[i + 1])

        if not start:
            continue

        event_name = clean_event_name(title, session)

        if series == "Formula 2":
            if session == "Sprint":
                session = "Sprint Race"
            elif session == "Feature":
                session = "Feature Race"

        if series == "Formula 1" and session == "Grand Prix":
            session = "Race"

        events.append({
            "series": series,
            "event": event_name,
            "session": session,
            "start": start,
        })

    return events

def find_next_weekend(all_events):
    now = datetime.now(TZ)
    upcoming = [e for e in all_events if e["start"] >= now - timedelta(hours=2)]

    if not upcoming:
        return []

    first_event_date = min(e["start"].date() for e in upcoming)
    weekend_end = first_event_date + timedelta(days=4)

    return [
        e for e in upcoming
        if first_event_date <= e["start"].date() <= weekend_end
    ]

def format_day(date_obj):
    days = {
        "Monday": "Понеделник",
        "Tuesday": "Вторник",
        "Wednesday": "Сряда",
        "Thursday": "Четвъртък",
        "Friday": "Петък",
        "Saturday": "Събота",
        "Sunday": "Неделя",
    }
    return days[date_obj.strftime("%A")]

def format_message(events):
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    if not events:
        return (
            "🏁 <b>F1 / F2 програма</b>\n\n"
            "Няма намерен предстоящ състезателен уикенд."
        )

    main_event = events[0]["event"]

    msg = f"🏁 <b>{html.escape(main_event)}</b>\n"
    msg += "🇧🇬 <b>Всички часове са българско време</b>\n"
    msg += f"🕘 Обновено: {now}\n\n"

    by_series = defaultdict(list)
    for event in events:
        by_series[event["series"]].append(event)

    for series in ["Formula 1", "Formula 2"]:
        if series not in by_series:
            continue

        msg += f"━━━━━━━━━━━━━━\n"
        msg += f"🏎 <b>{series}</b>\n\n"

        by_day = defaultdict(list)
        for event in by_series[series]:
            by_day[event["start"].date()].append(event)

        for day in sorted(by_day):
            msg += f"📅 <b>{format_day(by_day[day][0]['start'])} - {day.strftime('%d.%m')}</b>\n"

            day_events = sorted(
                by_day[day],
                key=lambda e: (
                    e["start"],
                    SESSION_ORDER.get(e["session"], 99)
                )
            )

            for event in day_events:
                time = event["start"].strftime("%H:%M")
                msg += f"• {time} - {html.escape(event['session'])}\n"

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
        all_events.extend(parse_events(series, lines))

    all_events = sorted(all_events, key=lambda e: e["start"])
    next_weekend = find_next_weekend(all_events)
    message = format_message(next_weekend)
    send_telegram(message)

if __name__ == "__main__":
    main()
