import os, re, html, requests
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
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

SESSIONS = [
    "Sprint Qualifying",
    "Free Practice 1",
    "Free Practice 2",
    "Free Practice 3",
    "Qualifying",
    "Practice",
    "Sprint Race",
    "Feature Race",
    "Sprint",
    "Feature",
    "Grand Prix",
]

def fetch_lines(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]

def find_session(text):
    for s in SESSIONS:
        if s.lower() in text.lower():
            return s
    return None

def parse_events(series, lines):
    events = []

    for line in lines:
        if "buy us a coffee" in line.lower() or "support us" in line.lower():
            continue

        session = find_session(line)
        if not session:
            continue

        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2}:\d{2})", line)
        if not m:
            continue

        day = int(m.group(1))
        month = MONTHS.get(m.group(2))
        hour, minute = map(int, m.group(3).split(":"))

        if not month:
            continue

        start = datetime(YEAR, month, day, hour, minute, tzinfo=TZ)

        title_before_date = line[:m.start()].strip()
        event_name = title_before_date.replace(session, "").strip()

        if not event_name:
            continue

        if series == "Formula 1" and session == "Grand Prix":
            session = "Race"

        if series == "Formula 2":
            if session == "Sprint":
                session = "Sprint Race"
            if session == "Feature":
                session = "Feature Race"

        events.append({
            "series": series,
            "event": event_name,
            "session": session,
            "start": start,
        })

    return events

def next_weekend(events):
    now = datetime.now(TZ)
    upcoming = [e for e in events if e["start"] >= now - timedelta(hours=3)]

    if not upcoming:
        return []

    first = min(upcoming, key=lambda e: e["start"])
    event_name = first["event"]

    return [
        e for e in upcoming
        if e["event"] == event_name
        and e["start"] <= first["start"] + timedelta(days=4)
    ]

def bg_day(dt):
    return {
        "Monday": "Понеделник",
        "Tuesday": "Вторник",
        "Wednesday": "Сряда",
        "Thursday": "Четвъртък",
        "Friday": "Петък",
        "Saturday": "Събота",
        "Sunday": "Неделя",
    }[dt.strftime("%A")]

def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()

def format_message(events):
    if not events:
        return "🏁 <b>F1 / F2 програма</b>\n\nНе намерих предстоящ уикенд. Parser-ът има нужда от преглед."

    title = events[0]["event"]
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    msg = f"🏁 <b>{html.escape(title)}</b>\n"
    msg += "🇧🇬 <b>Българско време</b>\n"
    msg += f"🕘 Обновено: {now}\n\n"

    by_series = defaultdict(list)
    for e in events:
        by_series[e["series"]].append(e)

    for series in ["Formula 1", "Formula 2"]:
        if series not in by_series:
            continue

        msg += "━━━━━━━━━━━━━━\n"
        msg += f"🏎 <b>{series}</b>\n\n"

        by_day = defaultdict(list)
        for e in by_series[series]:
            by_day[e["start"].date()].append(e)

        for day in sorted(by_day):
            msg += f"📅 <b>{bg_day(by_day[day][0]['start'])} - {day.strftime('%d.%m')}</b>\n"

            for e in sorted(by_day[day], key=lambda x: x["start"]):
                msg += f"• {e['start'].strftime('%H:%M')} - {html.escape(e['session'])}\n"

            msg += "\n"

    msg += "Източници: f1calendar.com / f2calendar.com"
    return msg

all_events = []

for series, url in SOURCES.items():
    all_events.extend(parse_events(series, fetch_lines(url)))

all_events = sorted(all_events, key=lambda e: e["start"])
events = next_weekend(all_events)

send_telegram(format_message(events))
