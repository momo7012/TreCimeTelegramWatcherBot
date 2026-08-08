import html
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AURONZO_EMAIL = os.environ["AURONZO_EMAIL"]
AURONZO_PASSWORD = os.environ["AURONZO_PASSWORD"]

PORTAL = "https://pass.auronzo.info/Frontoffice"
LOGIN_URL = PORTAL + "/Account/Login"
TICKET_TYPES_URL = PORTAL + "/Abbonamenti/TicketTypes"
ENDPOINT = PORTAL + "/Abbonamenti/GetDurateScheduler"

TARGET_DATE = os.getenv("TARGET_DATE", "2026-09-02")
TARGET_HOURS = {1, 2, 3, 4, 5, 6, 7}  # 01:00 kept temporarily as a known-open test
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))

SUBSCRIBERS_FILE = Path("subscribers.json")
STATE_FILE = Path("state.json")

last_status = {
    "time": None,
    "http": None,
    "final_url": None,
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def subscribers():
    return set(load_json(SUBSCRIBERS_FILE, []))


def add_subscriber(chat_id):
    s = subscribers()
    s.add(str(chat_id))
    save_json(SUBSCRIBERS_FILE, sorted(s))


def remove_subscriber(chat_id):
    s = subscribers()
    s.discard(str(chat_id))
    save_json(SUBSCRIBERS_FILE, sorted(s))


def tg(method, **data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, data=data, timeout=35)
    r.raise_for_status()
    return r.json()


def send(chat_id, text):
    try:
        tg("sendMessage", chat_id=str(chat_id), text=text, disable_web_page_preview=False)
    except Exception as e:
        print("Telegram send failed:", repr(e))


def broadcast(text):
    for chat_id in subscribers():
        send(chat_id, text)


def flatten_html(payload):
    payload = html.unescape(payload)
    payload = re.sub(r"<script\b[^>]*>.*?</script>", " ", payload, flags=re.I | re.S)
    payload = re.sub(r"<style\b[^>]*>.*?</style>", " ", payload, flags=re.I | re.S)
    payload = re.sub(r"<[^>]+>", " ", payload)
    return re.sub(r"\s+", " ", payload).strip()


def parse_slots(payload):
    text = flatten_html(payload)
    found = {}

    # Handles the format you already saw in the booking UI:
    # "From 1:00 AM - 12 SEATS AVAILABLE"
    patterns = [
        re.compile(
            r"(?:From|Dalle|Da)\s+"
            r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?"
            r"\s*[-–—]\s*"
            r"(\d+)\s*(?:SEATS?|PLACES?|POSTI)"
            r"(?:\s+AVAILABLE|\s+DISPONIBILI)?",
            re.I,
        ),
        re.compile(
            r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?"
            r".{0,100}?"
            r"(\d+)\s*(?:SEATS?\s+AVAILABLE|PLACES?\s+AVAILABLE|POSTI\s+DISPONIBILI)",
            re.I,
        ),
    ]

    for pat in patterns:
        for m in pat.finditer(text):
            hour = int(m.group(1))
            ampm = (m.group(3) or "").upper()
            if ampm == "AM" and hour == 12:
                hour = 0
            elif ampm == "PM" and hour != 12:
                hour += 12

            seats = int(m.group(4))
            if hour in TARGET_HOURS and seats > 0:
                found[hour] = max(found.get(hour, 0), seats)

    return sorted(found.items())


def build_scheduler_url():
    params = {
        "customerId": "",
        "permitTypeId": "1",
        "sectorId": "10",
        "selectedDate": TARGET_DATE,
        "ctrlDurataId": "Validita_Durata_Id",
        "ctrlDataSelectionId": "schedulerDataSelection",
        "_": str(int(time.time() * 1000)),
    }
    return ENDPOINT + "?" + urlencode(params)


def first_visible(page, selectors):
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None


def login(page):
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)

    # If already authenticated, the login form may not exist.
    password = first_visible(page, ['input[type="password"]'])
    if password is None:
        page.goto(TICKET_TYPES_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
        if "auronzo.info/parcheggio-tre-cime" not in page.url.lower():
            return

        # Retry explicit login page once.
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
        password = first_visible(page, ['input[type="password"]'])

    if password is None:
        raise RuntimeError(
            "Login form was not reachable. Final URL: " + page.url
        )

    username = first_visible(page, [
        'input[type="email"]',
        'input[name*="email" i]',
        'input[id*="email" i]',
        'input[name*="username" i]',
        'input[id*="username" i]',
        'input[name*="user" i]',
        'input[type="text"]',
    ])

    if username is None:
        raise RuntimeError("Could not find username/email field on login page.")

    username.fill(AURONZO_EMAIL)
    password.fill(AURONZO_PASSWORD)

    submit = first_visible(page, [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Accedi")',
        'button:has-text("Login")',
        'button:has-text("Entra")',
    ])
    if submit is None:
        raise RuntimeError("Could not find login submit button.")

    submit.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1500)

    # Validate by opening the ticket type page.
    page.goto(TICKET_TYPES_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1000)

    if "auronzo.info/parcheggio-tre-cime" in page.url.lower():
        raise RuntimeError(
            "Login did not create an authenticated portal session; redirected to public Auronzo page."
        )


def authenticated_scheduler_fetch():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="it-IT",
            timezone_id="Europe/Rome",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            login(page)
            scheduler_url = build_scheduler_url()

            result = page.evaluate(
                """async (url) => {
                    const response = await fetch(url, {
                        method: "GET",
                        credentials: "include",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "text/html, */*; q=0.01"
                        },
                        cache: "no-store"
                    });
                    return {
                        status: response.status,
                        url: response.url,
                        text: await response.text()
                    };
                }""",
                scheduler_url,
            )

            final_url = result["url"]
            body = result["text"]

            # Fail loudly if the endpoint silently redirects to the public WordPress page.
            if (
                "auronzo.info/parcheggio-tre-cime-di-lavaredo" in final_url.lower()
                or "Parcheggio Tre Cime di Lavaredo: informazioni, come prenotare" in body
            ):
                raise RuntimeError(
                    "Scheduler request was redirected to the public Auronzo page even after login."
                )

            return result["status"], final_url, body

        finally:
            context.close()
            browser.close()


def get_state():
    return load_json(STATE_FILE, {"open_hours": []})


def set_state(hours):
    save_json(STATE_FILE, {"open_hours": sorted(hours)})


def perform_check(force_chat_id=None, include_raw=False):
    global last_status
    now = datetime.now().astimezone()

    try:
        status, final_url, body = authenticated_scheduler_fetch()
        slots = parse_slots(body)

        current = {h for h, _ in slots}
        previous = set(get_state().get("open_hours", []))
        newly_open = current - previous

        last_status = {
            "time": now.isoformat(timespec="seconds"),
            "http": status,
            "final_url": final_url,
            "slots": slots,
            "error": None,
        }

        if newly_open:
            lines = [
                f"✅ {hour:02d}:00 — {seats} place(s) available"
                for hour, seats in slots if hour in newly_open
            ]
            broadcast(
                "🚨 Tre Cime parking availability!\n\n"
                f"📅 {TARGET_DATE}\n"
                + "\n".join(lines)
                + "\n\nOfficial booking:\n"
                + TICKET_TYPES_URL
            )

        set_state(current)

        if force_chat_id is not None:
            if slots:
                lines = "\n".join(
                    f"✅ {h:02d}:00 — {n} available" for h, n in slots
                )
                send(
                    force_chat_id,
                    "🔎 Authenticated check completed.\n"
                    f"HTTP: {status}\n\n"
                    + lines
                )
            else:
                send(
                    force_chat_id,
                    "⚠️ Authenticated endpoint returned successfully, "
                    "but no watched open slots were parsed.\n"
                    f"HTTP: {status}\n"
                    f"Final URL: {final_url}\n"
                    "Use /raw so we can inspect the actual scheduler response."
                )

            if include_raw:
                preview = re.sub(r"\s+", " ", body)[:3500]
                send(
                    force_chat_id,
                    "🧪 AUTHENTICATED RAW RESPONSE\n"
                    f"HTTP: {status}\n"
                    f"Final URL: {final_url}\n\n"
                    + preview
                )

    except Exception as e:
        last_status = {
            "time": now.isoformat(timespec="seconds"),
            "http": None,
            "final_url": None,
            "slots": [],
            "error": repr(e),
        }
        if force_chat_id is not None:
            send(
                force_chat_id,
                "❌ Authenticated check failed:\n"
                f"{type(e).__name__}: {e}"
            )


def scheduler_loop():
    while True:
        perform_check()
        time.sleep(CHECK_INTERVAL)


def command_loop():
    offset = 0

    while True:
        try:
            response = tg(
                "getUpdates",
                offset=offset,
                timeout=25,
                allowed_updates=json.dumps(["message"]),
            )

            for update in response.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")
                text = (message.get("text") or "").strip().lower()

                if not chat_id:
                    continue

                if text == "/start":
                    add_subscriber(chat_id)
                    send(
                        chat_id,
                        "✅ Tre Cime authenticated watcher activated.\n\n"
                        "Temporary test range: 01:00–07:00.\n"
                        "01:00 is intentionally included so we can prove detection works.\n\n"
                        "/check — test now\n"
                        "/raw — authenticated raw scheduler response\n"
                        "/status — last check status\n"
                        "/stop — stop notifications"
                    )

                elif text == "/check":
                    add_subscriber(chat_id)
                    send(chat_id, "🔐 Logging in and checking scheduler…")
                    perform_check(force_chat_id=chat_id)

                elif text == "/raw":
                    add_subscriber(chat_id)
                    send(chat_id, "🔐 Logging in and fetching raw scheduler response…")
                    perform_check(force_chat_id=chat_id, include_raw=True)

                elif text == "/status":
                    slots = last_status.get("slots") or []
                    slots_text = (
                        ", ".join(f"{h:02d}:00 ({n})" for h, n in slots)
                        if slots else "none"
                    )
                    send(
                        chat_id,
                        "📡 Tre Cime Watcher\n"
                        f"Last check: {last_status.get('time')}\n"
                        f"HTTP: {last_status.get('http')}\n"
                        f"Final URL: {last_status.get('final_url')}\n"
                        f"Open slots: {slots_text}\n"
                        f"Error: {last_status.get('error')}"
                    )

                elif text == "/stop":
                    remove_subscriber(chat_id)
                    send(chat_id, "🔕 Notifications stopped.")

        except Exception as e:
            print("Telegram polling error:", repr(e))
            time.sleep(10)


if __name__ == "__main__":
    print("Starting authenticated Tre Cime watcher...")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    command_loop()
