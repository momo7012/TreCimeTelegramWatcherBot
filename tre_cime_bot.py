import json
import os
import re
import time
import threading
from pathlib import Path
from datetime import datetime

import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

BASE = "https://pass.auronzo.info/Frontoffice"
ENDPOINT = BASE + "/Abbonamenti/GetDurateScheduler"

TARGET_DATE = os.getenv("TARGET_DATE", "2026-09-02")
TARGET_HOURS = {1, 2, 3, 4, 5, 6, 7}
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))

SUBSCRIBERS_FILE = Path("subscribers.json")
STATE_FILE = Path("state.json")

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/138 Safari/537.36"
    ),
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "/",
})

last_status = {
    "time": None,
    "http": None,
    "slots": [],
    "error": None,
}


def load_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_subscribers():
    return set(load_json(SUBSCRIBERS_FILE, []))


def add_subscriber(chat_id):
    users = get_subscribers()
    users.add(str(chat_id))
    save_json(SUBSCRIBERS_FILE, sorted(users))


def telegram(method, **data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, data=data, timeout=35)
    r.raise_for_status()
    return r.json()


def send(chat_id, text):
    try:
        telegram(
            "sendMessage",
            chat_id=str(chat_id),
            text=text,
            disable_web_page_preview=False,
        )
    except Exception as e:
        print("Telegram send failed:", repr(e))


def broadcast(text):
    for chat_id in get_subscribers():
        send(chat_id, text)


def init_session():
    try:
        session.get(BASE + "/", timeout=30)
    except Exception:
        pass


def fetch_scheduler():
    params = {
        "customerId": "",
        "permitTypeId": "1",
        "sectorId": "10",
        "selectedDate": TARGET_DATE,
        "ctrlDurataId": "Validita_Durata_Id",
        "ctrlDataSelectionId": "schedulerDataSelection",
        "_": str(int(time.time() * 1000)),
    }

    r = session.get(ENDPOINT, params=params, timeout=30)

    if r.status_code in (401, 403):
        init_session()
        r = session.get(ENDPOINT, params=params, timeout=30)

    r.raise_for_status()
    return r


def normalize_hour(raw):
    raw = raw.strip().upper()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", raw)
    if not m:
        return None

    hour = int(m.group(1))
    ampm = m.group(3)

    if ampm == "AM" and hour == 12:
        hour = 0
    elif ampm == "PM" and hour != 12:
        hour += 12

    return hour


def html_to_text(html):
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&#39;": "'",
        "&quot;": '"',
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def parse_slots(html):
    text = html_to_text(html)

    patterns = [
        re.compile(
            r"(?:From|Dalle|Da)\s+"
            r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)"
            r"\s*[-–—]\s*"
            r"(\d+)\s*"
            r"(?:SEATS?\s+AVAILABLE|POSTI\s+DISPONIBILI)",
            re.I,
        ),
        re.compile(
            r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)"
            r".{0,60}?"
            r"(\d+)\s*"
            r"(?:SEATS?\s+AVAILABLE|POSTI\s+DISPONIBILI)",
            re.I,
        ),
    ]

    found = {}
    for pattern in patterns:
        for m in pattern.finditer(text):
            hour = normalize_hour(m.group(1))
            seats = int(m.group(2))
            if hour in TARGET_HOURS and seats > 0:
                found[hour] = max(found.get(hour, 0), seats)

    return sorted(found.items())


def state():
    return load_json(STATE_FILE, {"open_hours": []})


def save_state(open_hours):
    save_json(STATE_FILE, {"open_hours": sorted(open_hours)})


def perform_check(force_chat_id=None):
    global last_status

    now = datetime.now().astimezone()

    try:
        r = fetch_scheduler()
        slots = parse_slots(r.text)
        current = {h for h, _ in slots}
        previous = set(state().get("open_hours", []))
        newly_open = current - previous

        last_status = {
            "time": now.isoformat(timespec="seconds"),
            "http": r.status_code,
            "slots": slots,
            "error": None,
        }

        if newly_open:
            lines = []
            for hour, seats in slots:
                if hour in newly_open:
                    lines.append(
                        f"✅ {hour:02d}:00 — {seats} place(s) available"
                    )

            broadcast(
                "🚨 Tre Cime parking became available!\n\n"
                "📅 2 September 2026\n"
                + "\n".join(lines)
                + "\n\nرزرو رسمی:\n"
                + BASE
            )

        save_state(current)

        if force_chat_id is not None:
            if slots:
                lines = "\n".join(
                    f"✅ {h:02d}:00 — {n} available"
                    for h, n in slots
                )
                send(
                    force_chat_id,
                    "🔎 Check completed.\n\n"
                    + lines
                    + f"\n\nHTTP {r.status_code}"
                )
            else:
                send(
                    force_chat_id,
                    "🔎 Check completed successfully.\n"
                    "No available slots detected between 02:00 and 07:00.\n"
                    f"HTTP {r.status_code}"
                )

    except Exception as e:
        last_status = {
            "time": now.isoformat(timespec="seconds"),
            "http": None,
            "slots": [],
            "error": repr(e),
        }

        if force_chat_id is not None:
            send(
                force_chat_id,
                f"❌ Check failed:\n{type(e).__name__}: {e}"
            )


def scheduler_loop():
    init_session()

    while True:
        perform_check()
        time.sleep(CHECK_INTERVAL)


def command_loop():
    offset = 0

    while True:
        try:
            response = telegram(
                "getUpdates",
                offset=offset,
                timeout=25,
                allowed_updates=json.dumps(["message"]),
            )

            for update in response.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                text = (msg.get("text") or "").strip().lower()

                if not chat_id:
                    continue

                if text == "/start":
                    add_subscriber(chat_id)
                    send(
                        chat_id,
                        "✅ Tre Cime watcher activated.\n\n"
                        "من هر ساعت تاریخ 2 Sep 2026 را برای "
                        "ساعت‌های 02:00 تا 07:00 چک می‌کنم.\n"
                        "اگر یکی از ساعت‌ها باز شود، همین‌جا پیام می‌دهم.\n\n"
                        "/check — بررسی فوری\n"
                        "/status — وضعیت آخرین بررسی\n"
                        "/stop — توقف اعلان برای این چت"
                    )

                elif text == "/check":
                    add_subscriber(chat_id)
                    send(chat_id, "🔎 Checking now…")
                    perform_check(force_chat_id=chat_id)

                elif text == "/status":
                    slots = last_status.get("slots") or []
                    slots_txt = (
                        ", ".join(f"{h:02d}:00 ({n})" for h, n in slots)
                        if slots else "none"
                    )
                    send(
                        chat_id,
                        "📡 Tre Cime Watcher\n"
                        f"Last check: {last_status.get('time')}\n"
                        f"HTTP: {last_status.get('http')}\n"
                        f"Open slots: {slots_txt}\n"
                        f"Error: {last_status.get('error')}"
                    )

                elif text == "/stop":
                    users = get_subscribers()
                    users.discard(str(chat_id))
                    save_json(SUBSCRIBERS_FILE, sorted(users))
                    send(chat_id, "🔕 Notifications stopped.")

        except Exception as e:
            print("Telegram polling error:", repr(e))
            time.sleep(10)


if __name__ == "__main__":
    print("Starting Tre Cime Telegram watcher...")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    command_loop()
