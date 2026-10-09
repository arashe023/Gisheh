<div align="center">
  <img src="data/icons/hicolor/scalable/apps/io.github.arashe023.Gisheh.svg" width="128" height="128" alt="آیکن گیشه">
  <h1>گیشه — Gisheh</h1>
  <p>فیلم‌ها و سریال‌هایی را که می‌بینید دنبال کنید</p>
</div>

[English](README.md) · [گزارش مشکل](https://github.com/arashe023/Gisheh/issues) · [مشارکت](CONTRIBUTING.md)

گیشه برنامه‌ای برای لینوکس با GTK 4 و libadwaita است؛ برای پیدا کردن فیلم، سریال
و انیمه و نگهداری سابقهٔ تماشای آن‌ها. می‌توانید کتابخانه‌ای خصوصی روی دستگاه
داشته باشید یا برای همگام‌سازی سابقهٔ تماشا، حساب Simkl را متصل کنید.

![کتابخانهٔ محلی گیشه با عنوان‌های نمونه](data/screenshots/local-library.png)

## امکانات

- جست‌وجوی عنوان‌ها، پوستر، توضیحات و بازیگران با اطلاعات TMDB.
- مرتب‌کردن کتابخانه در فهرست‌های در حال تماشا، تماشاشده، متوقف‌شده، رهاشده و فهرست تماشا.
- ثبت قسمت‌های دیده‌شده، تاریخ تماشا و امتیاز شخصی.
- نمایش فعالیت ماهانه و سالانه، ژانرهای پرتکرار و امتیازها در نمایه.
- خروجی‌گرفتن و بازیابی کتابخانهٔ محلی همراه با نسخهٔ پشتیبان خودکار.
- پیروی از زبان، جهت نوشتار و ظاهر روشن یا تیرهٔ سیستم.
- انتخاب مستقل زبان محتوای TMDB از فهرست قابل‌جست‌وجوی زبان‌های آن.

حالت محلی به حساب کاربری نیاز ندارد. جست‌وجو و دریافت تصویرهای جدید به اینترنت
نیاز دارند؛ رکوردهای ذخیره‌شدهٔ محلی در حالت آفلاین در دسترس هستند.
همگام‌سازی Simkl اختیاری است. جزئیات در [داده‌ها و حریم خصوصی](docs/PRIVACY.md) آمده است.

## نصب

نسخهٔ بعدی **1.5.0-rc1**، نامزد انتشار برای آزمایش است. برنامه هنوز در Flathub
منتشر نشده است. بسته‌ها پس از انتشار در [GitHub Releases](https://github.com/arashe023/Gisheh/releases)
در دسترس قرار می‌گیرند.

برای نصب بستهٔ Flatpak ساخته‌شده یا دریافت‌شده:

```sh
flatpak install --user ./Gisheh-1.5.0-rc1-x86_64.flatpak
flatpak run io.github.arashe023.Gisheh//beta
```

ساخت استاندارد برنامه دسترسی TMDB را همراه دارد؛ کاربر نیازی به ساختن کلید API
ندارد. در اولین اجرا، کتابخانهٔ محلی یا اتصال به Simkl را انتخاب می‌کنید.

## ساخت برنامه

در [GNOME Builder](https://apps.gnome.org/Builder/) مخزن را باز کنید، فایل
`build-aux/flatpak/io.github.arashe023.Gisheh.json` را انتخاب کنید و برنامه را بسازید
و اجرا کنید. این manifest از GNOME 50 استفاده می‌کند.
[راهنمای بسته‌بندی](docs/RELEASING.md) دستورهای ساخت بسته را توضیح می‌دهد.

برای ساخت مستقیم، Python ≥ 3.11، GTK ≥ 4.12، libadwaita ≥ 1.9، libsecret ≥ 0.20،
PyGObject، pycairo، httpx، Meson ≥ 1.3، Ninja، gettext و ابزارهای توسعهٔ GLib لازم‌اند.
تست‌ها به Xvfb، xauth، D-Bus، Ruff، desktop-file-utils و AppStream هم نیاز دارند.

```sh
meson setup build --prefix="$PWD/_install"
meson compile -C build
meson test -C build --print-errorlogs
meson install -C build
./_install/bin/gisheh
```

برای ساخت بدون وابستگی‌های تست، گزینهٔ `-Dtests=false` را به `meson setup` اضافه کنید.

## مشارکت و ترجمه

گزارش اشکال، ترجمه و مشارکت در کد از طریق مخزن پروژه انجام می‌شود.
[راهنمای مشارکت](CONTRIBUTING.md) روش بررسی تغییرات را توضیح می‌دهد.
ترجمه‌های رابط با gettext در `po/` نگهداری می‌شوند. رابط فارسی و انگلیسی موجود
است و زبان آن از سیستم انتخاب می‌شود؛ زبان محتوای TMDB تنظیم جداگانه‌ای دارد.

[معماری](docs/ARCHITECTURE.md) · [اعتبارسنجی](docs/VALIDATION.md) · [تغییرات](CHANGELOG.md)

## منابع و مجوز

گیشه نرم‌افزار آزاد با [مجوز MIT](LICENSE) و برنامه‌ای مستقل بر پایهٔ فناوری‌های
GNOME است. اطلاعات و تصویرها از [TMDB](https://www.themoviedb.org) و همگام‌سازی
اختیاری حساب از [Simkl](https://simkl.com) تأمین می‌شوند.

This product uses the TMDB API but is not endorsed or certified by TMDB.
