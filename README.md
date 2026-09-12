# Gisheh 1.3.0 — Python + GTK4 + libadwaita

یک برنامهٔ بومی لینوکس برای مدیریت فیلم، سریال و انیمه که با Python، GTK4 و libadwaita پیاده‌سازی شده است.

نسخهٔ فعلی: `1.3.0` — شمارهٔ مرجع نسخه در فایل `VERSION` نگهداری می‌شود.

## امکانات

- چیدمان سه‌ستونهٔ دسکتاپ با سایدبار مستقل، فهرست و پنل جزئیات
- نام و اکشن‌های برنامه در HeaderBar اختصاصی سایدبار و فیلترها در بدنهٔ اصلی
- دکمهٔ آواتار در HeaderBar سایدبار برای ورود مستقیم به صفحهٔ Profile
- حالت‌های Movies، Shows و Anime
- Welcome Tour سه‌مرحله‌ای به سبک GNOME برای معرفی برنامه و انتخاب صریح Local-first یا Simkl
- حالت Local-first واقعی برای نگهداری Watchlist، امتیازها، تاریخ تماشا و وضعیت اپیزودها فقط روی دستگاه
- مقصد مستقل Explore برای دیدن محتوای تازه با فیلتر روند، بازه و ژانر
- موزاییک واکنش‌گر Explore با کارت‌های Hero، افقی و پوستر و اتصال مستقیم به پنل جزئیات
- بخش Lists با Watchlist مستقل و وضعیت‌های Watching، Watched، On Hold، Calendar و Dropped
- جست‌وجوی زنده و فیلتر بر اساس ژانر
- مرتب‌سازی بر اساس آخرین مشاهده، عنوان، امتیاز و سال انتشار
- تغییر بین نمای فهرستی و شبکه‌ای
- جست‌وجوی مستقیم کل کاتالوگ TMDB در Explore از دکمهٔ سایدبار و میان‌بر `Ctrl+K`
- انتقال خودکار فیلترهای Explore به ردیف دوم در پنجره‌های باریک، بدون اسکرول افقی
- اسکرول نامحدود Explore با صفحه‌بندی تدریجی TMDB
- نمایش Loading برای صفحه‌های بعد، تصاویر بازیگران و گالری جزئیات
- انتخاب عنوان و نمایش جزئیات، امتیاز، وضعیت و فعالیت کاربر
- نمای جزئیات کامل با Hero، تریلر، امتیازهای چندمنبعی، عوامل، ویدئوها، تصاویر و پیشنهادها
- Media Viewer تمام‌سطح به سبک Tuba برای پوستر و backdrop، همراه با پیمایش مجموعه، Zoom، Fullscreen، Copy و میان‌برهای صفحه‌کلید
- نمایش فصل‌ها و وضعیت اپیزودها برای سریال و انیمه
- نگهداری Specials به‌صورت فصل مستقل، بدون اثر روی Next/Last Episode فصل‌های اصلی
- همگام‌سازی تاریخچهٔ دقیق هر اپیزود از Simkl، شامل پشتیبانی از فاصله میان اپیزودهای دیده‌شده
- پیش‌بارگذاری فراداده و تصویر هر اپیزود از TMDB هنگام بازشدن صفحهٔ فصل
- ناوبری بومی از اطلاعات سریال به فصل و اپیزود همراه با Back و ذخیرهٔ وضعیت تماشا
- پس‌زمینهٔ هماهنگ با پالت پوستر که برای هر عنوان به‌صورت خودکار تغییر می‌کند
- نمای گرید فشرده با پوستر و نام، بدون کشیدگی کارت‌ها در پنجره‌های بزرگ
- تعامل‌های Bookmark و Watched با انتخاب تاریخ و ساعت تماشا، امتیازدهی ۱ تا ۱۰ از دکمهٔ ستاره و پیشنهادهای واقعی «More like this» از TMDB
- ورود به Simkl با PIN و همگام‌سازی کتابخانه، پروفایل و آمار واقعی کاربر
- لاگ داخلی قابل مشاهده برای مراحل و مدت همگام‌سازی Simkl، بدون ثبت اطلاعات ورود
- پوستر و backdrop زنده از TMDB با سطح Loading یکسان تا زمان دریافت تصویر واقعی و بدون کاور نمایشی ساختگی
- نمایش زبان اصلی و رده‌بندی سنی منطقه‌ای هر عنوان از داده‌های رسمی TMDB
- رابط دسکتاپ، پشتیبانی از high contrast و هماهنگی مستقیم با تم و رنگ accent سیستم

## معماری بومی

- `src/gisheh/application.py`: چرخهٔ استاندارد `Adw.Application` و actionهای عمومی
- `src/gisheh/onboarding.py`: Welcome Tour و انتخاب روش مدیریت کتابخانه
- `src/gisheh/state_store.py`: خواندن و نوشتن اتمیک state خصوصی کاربر
- `src/gisheh/window.py`: کنترلر پنجره، نماها و رویدادهای رابط
- `src/gisheh/ui/window.ui`: رابط GtkBuilder با `AdwNavigationSplitView`
- `src/gisheh/services/`: کلاینت‌های مستقل TMDB، Simkl و انتقال تصاویر
- `src/gisheh/io.github.gisheh.Gisheh.gresource.xml`: بسته‌بندی UI، CSS و fixtureهای تست در GResource
- `data/`: Desktop Entry، AppStream، GSettings و آیکن‌های hicolor
- `build-aux/flatpak/`: manifest قابل‌شناسایی توسط GNOME Builder و Flatpak Builder
- `po/`: زیرساخت gettext و فهرست منابع قابل‌ترجمه

تم، رنگ accent و حالت high contrast مستقیماً توسط GTK و libadwaita اعمال می‌شوند و به پل یا لایهٔ نمایش جداگانه‌ای نیاز ندارند.
در اولین اجرا، کاربر مالکیت دادهٔ کتابخانه را انتخاب می‌کند. در حالت Local-first، Watchlist، Watched، امتیاز شخصی، تاریخ‌های تماشا و وضعیت فصل و اپیزود در `state.json` خصوصی با مجوز `0600` ذخیره می‌شوند و برنامه برای مدیریت کتابخانه به Simkl متصل نمی‌شود. در حالت Simkl، همین عملیات از طریق Sync API در حساب کاربر ثبت می‌شوند و snapshot محلی برای اجرای سریع و بازیابی شبکه نگهداری می‌شود.
در حالت Local-first، Watched شدن حداقل یک اپیزود باعث می‌شود عنوان سریال یا انیمه در بخش Watching دیده شود؛ این دسته‌بندی به‌معنی Completed شدن همهٔ اپیزودها نیست و با Unwatched شدن همهٔ قسمت‌ها به وضعیت قبلی عنوان برمی‌گردد.
Explore فقط از داده‌ها و تصاویر زندهٔ TMDB استفاده می‌کند و در نبود شبکه یا credential معتبر، وضعیت خالی/خطا را بدون محتوای نمایشی نشان می‌دهد. نسخهٔ عمومی credential خواندنی TMDB را همراه build دارد و کاربر نهایی نیازی به واردکردن API Key ندارد.
اتصال و همگام‌سازی Simkl از Preferences → Services انجام می‌شود. صفحهٔ Profile فقط آمار کتابخانه را نمایش می‌دهد و بخش تکراری نام، عکس و وضعیت حساب ندارد. Simkl عضویت عنوان‌ها در فهرست‌ها، وضعیت تماشا و امتیاز شخصی را مشخص می‌کند؛ اطلاعات نمایشی و کاورها با شناسهٔ TMDB همان عنوان دریافت می‌شوند.

## اولین اجرا و مالکیت داده

وقتی هیچ انتخاب قبلی در state وجود نداشته باشد، Gisheh به‌جای پنجرهٔ اصلی یک Tour بومی سه‌مرحله‌ای نشان می‌دهد. دو گزینهٔ مرحلهٔ آخر عبارت‌اند از:

- **Local-first:** نیازی به حساب ندارد، دادهٔ شخصی را آپلود نمی‌کند و نسخهٔ کامل رکوردهای افزوده‌شده از Explore را برای راه‌اندازی بعدی روی دستگاه نگه می‌دارد.
- **Sync with Simkl:** ورود PIN را آغاز می‌کند و Simkl را به‌عنوان منبع همگام کتابخانه، امتیازها و تاریخچه انتخاب می‌کند.

انتخاب در `~/.local/state/io.github.gisheh.Gisheh/state.json` ذخیره می‌شود. در Flatpak این مسیر داخل فضای خصوصی برنامه قرار می‌گیرد. وضعیت فعال با نشانگر `Local` یا `Synced/Not synced` در HeaderBar قابل مشاهده است و از Preferences → Data ownership می‌توان روش مدیریت کتابخانه را تغییر داد. Welcome Tour فقط در اولین اجرا یا پس از اجرای Reset Gisheh نمایش داده می‌شود و ورودی تکراری آن در منوی اصلی وجود ندارد.

اندازهٔ پیش‌فرض پنجره `1100×700` است تا در فضای کاری رایج `1366×768` جا شود؛ حداقل معتبر حدود `360×480` است.

## چیدمان تطبیقی

- پنجره‌های پهن از سایدبار کاملِ داک‌شده (`248–300px`) کنار محتوا استفاده می‌کنند.
- پنجره‌های باریک سایدبار را مخفی می‌کنند و همان سایدبار کامل با دکمه منو به‌صورت دراور نیمه‌عرض روی محتوا باز می‌شود؛ انتخاب مقصد دراور را می‌بندد.
- پنل جزئیات تطبیقی است: کنار محتوا در عرض زیاد، شناور روی محتوا در عرض متوسط، و در عرض خیلی باریک به‌صورت صفحه تمام‌عرض با جریان Back (اپیزود → فصل → عنوان → محتوا).
- فیلترهای Explore بر اساس عرض واقعی می‌شکنند و گرید Explore تا یک ستون پایین می‌آید. تغییر تعداد ستون‌ها حاشیهٔ پایداری دارد تا بازشدن هم‌زمان پنل‌ها باعث رفت‌وبرگشت اندازه و بازچینی حلقه‌ای نشود.
- اندازهٔ پیش‌فرض `1100×700` است و چیدمان تا عرض‌های حدود موبایل کار می‌کند.

این یک برنامهٔ تطبیقی دسکتاپ است؛ پشتیبانی موبایل ادعا نمی‌شود.

## اجرا

پروژه را مستقیماً در GNOME Builder باز کنید؛ Builder فایل Meson و manifest فلت‌پک را تشخیص می‌دهد و با دکمهٔ Run آن را build و اجرا می‌کند.
فایل اجرایی Python در Meson به‌عنوان target نصب‌شوندهٔ `gisheh` ثبت شده است؛ بنابراین در تنظیمات پروژهٔ Builder، گزینهٔ Run Command باید به‌صورت خودکار `gisheh` باشد.

برای build و تست روی سیستم میزبان:

```bash
meson setup build --prefix="$PWD/_install"
meson compile -C build
meson test -C build --print-errorlogs
meson install -C build
./_install/bin/gisheh
```

پس از اولین setup، برای buildهای بعدی فقط `meson compile -C build` لازم است. برای ساخت Flatpak:

```bash
flatpak-builder --user --install --force-clean flatpak-build \
  build-aux/flatpak/io.github.gisheh.Gisheh.json
```

نسخه‌های عمومی باید Client ID ثبت‌شدهٔ Gisheh در Simkl و credential تأییدشدهٔ TMDB را هنگام build همراه برنامه کنند. در این حالت کاربر برای Simkl فقط دکمهٔ Connect را می‌زند و PIN نمایش‌داده‌شده را در مرورگر تأیید می‌کند؛ ساختن برنامهٔ توسعه‌دهنده یا واردکردن Client Secret لازم نیست. Access Token سیمکل ابتدا در Secret Service سیستم ذخیره می‌شود و اگر keyring در دسترس نباشد، برنامه از فایل خصوصی با مجوز `0600` استفاده می‌کند.

مقادیر عمومی release با گزینه‌های Meson تنظیم می‌شوند:

```bash
meson setup build \
  -Dsimkl_client_id="$GISHEH_PUBLIC_SIMKL_CLIENT_ID" \
  -Dtmdb_read_token="$GISHEH_PUBLIC_TMDB_READ_TOKEN"
```

این دو مقدار داخل برنامهٔ نصب‌شده قابل استخراج‌اند و نباید Client Secret یا credential محرمانه در آن‌ها قرار گیرد. برای توسعهٔ محلی، `SIMKL_CLIENT_ID`، `SIMKL_ACCESS_TOKEN` و `TMDB_READ_TOKEN` همچنان به‌عنوان override پشتیبانی می‌شوند. در build فاقد credential عمومی، صفحهٔ تنظیمات وضعیت integration را صریحاً «Unavailable» نشان می‌دهد؛ ورود token شخصی TMDB فقط به‌عنوان Developer Setup باقی مانده است.

## منابع داده و انتساب

داده‌ها و تصاویر فیلم و سریال توسط [The Movie Database (TMDB)](https://www.themoviedb.org) و تاریخچهٔ تماشا و همگام‌سازی حساب توسط [Simkl](https://simkl.com) فراهم می‌شوند. لوگوی رسمی TMDB، لینک منبع و متن انتساب الزامی داخل صفحهٔ `Credits & Data Sources` برنامه قرار گرفته‌اند:

> This product uses the TMDB API but is not endorsed or certified by TMDB.

## ساختار اصلی

```text
.
├── meson.build
├── meson_options.txt
├── build-aux/flatpak/io.github.gisheh.Gisheh.json
├── data/
│   ├── meson.build
│   ├── io.github.gisheh.Gisheh.desktop.in
│   ├── io.github.gisheh.Gisheh.metainfo.xml.in
│   ├── io.github.gisheh.Gisheh.gschema.xml
│   └── icons/hicolor/
├── po/
├── src/
│   ├── meson.build
│   ├── gisheh.in
│   └── gisheh/
│       ├── application.py
│       ├── main.py
│       ├── onboarding.py
│       ├── state_store.py
│       ├── window.py
│       ├── services/
│       ├── ui/window.ui
│       ├── style.css
│       └── library.json
└── tests/
```
