# Tre Cime Telegram Watcher — ready version

این نسخه برای این کار ساخته شده:

- تاریخ: 2026-09-02
- نوع خودرو: permitTypeId=1
- پارکینگ/sector: sectorId=10
- ساعت‌ها: 02:00، 03:00، 04:00، 05:00، 06:00، 07:00
- بررسی: هر 1 ساعت
- اعلان: فقط وقتی ساعتی که قبلاً بسته بوده باز شود

## چیزی که لازم داری

فقط Telegram Bot Token.

### ساخت Bot Token

1. در Telegram برو به `@BotFather`
2. `/newbot`
3. یک اسم و username بده
4. Token را کپی کن

## اجرای ساده روی کامپیوتر

```bash
pip install -r requirements.txt
```

macOS/Linux:
```bash
export TELEGRAM_BOT_TOKEN="توکن"
python tre_cime_bot.py
```

Windows PowerShell:
```powershell
$env:TELEGRAM_BOT_TOKEN="توکن"
python tre_cime_bot.py
```

بعد در Telegram بات خودت را باز کن و:

```text
/start
```

بزن.

دیگر CHAT_ID لازم نیست؛ بات خودش chat id را از /start ثبت می‌کند.

## تست

در Telegram بزن:

```text
/check
```

اگر این را دیدی:

```text
Check completed successfully.
No available slots detected between 02:00 and 07:00.
HTTP 200
```

یعنی endpoint رسمی درست جواب داده و مانیتور کار می‌کند.

بعد:

```text
/status
```

آخرین زمان چک و HTTP status را می‌بینی.

## اجرای 24/7

برای اینکه با خاموش شدن لپ‌تاپ متوقف نشود باید روی سرور باشد.

این پروژه Dockerfile دارد و مستقیم روی Railway/VPS قابل اجرا است.

روی Railway فقط این Environment Variable را وارد کن:

```text
TELEGRAM_BOT_TOKEN=...
```

بعد Deploy و در تلگرام `/start`.

## Endpoint رسمی مورد استفاده

```text
https://pass.auronzo.info/Frontoffice/Abbonamenti/GetDurateScheduler
```

پارامترها:

```text
permitTypeId=1
sectorId=10
selectedDate=2026-09-02
```
