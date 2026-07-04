import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TZ = pytz.timezone("Europe/Sofia")

SOURCES = {
    "Formula 1": "https://f1calendar.com/",
    "Formula 2": "https://f2calendar.com/",
}

KEYWORDS = [
    "practice",
    "free practice",
    "qualifying",
    "sprint",
    "grand prix",
    "feature",
]

def fetch_text(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]

def extract_events(lines):
    events = []
    for i, line in enumerate(lines):
        if any(k in line.lower() for k in KEYWORDS):
            events.append(" ".join(lines[i:i+4]))
    return events[:40]

def send_telegram(message):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()

now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

msg = "🏁 <b>F1 / F2 програма</b>\n"
msg += "🇧🇬 Българско време\n"
msg += f"🕘 Обновено: {now}\n\n"

for name, url in SOURCES.items():
    msg += f"<b>{name}</b>\n"
    events = extract_events(fetch_text(url))

    if not events:
        msg += "Няма намерени събития.\n\n"
    else:
        for event in events:
            msg += f"• {event}\n"
        msg += "\n"

msg += "Източници: f1calendar.com / f2calendar.com"

send_telegram(msg)
