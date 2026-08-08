# Tre Cime Authenticated Telegram Watcher

مشکل نسخه قبلی این بود که endpoint بدون login به صفحه عمومی Auronzo redirect می‌شد.

این نسخه با Playwright وارد حساب کاربری پورتال می‌شود و سپس endpoint scheduler
را داخل همان session لاگین‌شده با `fetch(... credentials: "include")` صدا می‌زند.

## Railway Variables

سه Secret/Variable لازم است:

```text
TELEGRAM_BOT_TOKEN=...
AURONZO_EMAIL=ایمیل حساب پورتال Auronzo
AURONZO_PASSWORD=پسورد حساب پورتال Auronzo
```

اطلاعات login را داخل کد نگذار. فقط در Railway Variables/Secrets قرار بده.

## Deploy

پروژه را به GitHub بفرست و Railway را به repo وصل کن.
Dockerfile آماده است.

بعد از Deploy در Telegram:

```text
/start
/check
```

نسخه تست عمداً `01:00` تا `07:00` را مانیتور می‌کند.

چون 01:00 را الان به‌عنوان یک ساعت موجود می‌شناسیم، `/check` باید چیزی شبیه:

```text
Authenticated check completed.
HTTP: 200

✅ 01:00 — 12 available
```

برگرداند.

اگر 01:00 پیدا نشد:

```text
/raw
```

را بزن. این بار RAW باید از خود `GetDurateScheduler` باشد، نه صفحه WordPress عمومی.

## بعد از تایید

وقتی 01:00 درست دیده شد، کافی است این خط:

```python
TARGET_HOURS = {1, 2, 3, 4, 5, 6, 7}
```

به این تبدیل شود:

```python
TARGET_HOURS = {2, 3, 4, 5, 6, 7}
```

تا فقط ساعت‌های موردنظر نهایی مانیتور شوند.
