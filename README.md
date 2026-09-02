# CineShelf 1.3.0 — Python + GTK4 + libadwaita

یک برنامهٔ بومی لینوکس برای مدیریت فیلم، سریال و انیمه که با Python، GTK4 و libadwaita پیاده‌سازی شده است.

نسخهٔ فعلی: `1.3.0` — شمارهٔ مرجع نسخه در فایل `VERSION` نگهداری می‌شود.

## امکانات

- چیدمان سه‌ستونهٔ دسکتاپ با سایدبار مستقل، فهرست و پنل جزئیات
- نام و اکشن‌های برنامه در HeaderBar اختصاصی سایدبار و فیلترها در بدنهٔ اصلی
- دکمهٔ آواتار در HeaderBar سایدبار برای ورود مستقیم به صفحهٔ Profile
- حالت‌های Movies، Shows و Anime
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
- بارگذاری مستقل جزئیات، زمان پخش، بازیگران مهمان و تصویر هر اپیزود از TMDB هنگام بازشدن صفحهٔ آن
- ناوبری بومی از اطلاعات سریال به فصل و اپیزود همراه با Back و ذخیرهٔ وضعیت تماشا
- پس‌زمینهٔ هماهنگ با پالت پوستر که برای هر عنوان به‌صورت خودکار تغییر می‌کند
- نمای گرید فشرده با پوستر و نام، بدون کشیدگی کارت‌ها در پنجره‌های بزرگ
- تعامل‌های Bookmark و Watched، امتیازدهی ۱ تا ۱۰ از دکمهٔ ستاره و اکشن‌های تکمیلی در منوی سه‌نقطه
- ورود به Simkl با PIN و همگام‌سازی کتابخانه، پروفایل و آمار واقعی کاربر
- لاگ داخلی قابل مشاهده برای مراحل و مدت همگام‌سازی Simkl، بدون ثبت اطلاعات ورود
- پوستر و backdrop زنده از TMDB با طرح داخلی به‌عنوان placeholder/fallback
- نمایش زبان اصلی و رده‌بندی سنی منطقه‌ای هر عنوان از داده‌های رسمی TMDB
- رابط دسکتاپ، پشتیبانی از high contrast و هماهنگی مستقیم با تم و رنگ accent سیستم

## معماری بومی

- `src/cineshelf/application.py`: چرخهٔ استاندارد `Adw.Application` و actionهای عمومی
- `src/cineshelf/window.py`: کنترلر پنجره، نماها و رویدادهای رابط
- `src/cineshelf/ui/window.ui`: رابط GtkBuilder با `AdwNavigationSplitView`
- `src/cineshelf/services/`: کلاینت‌های مستقل TMDB، Simkl و انتقال تصاویر
- `src/cineshelf/io.github.cineshelf.CineShelf.gresource.xml`: بسته‌بندی UI، CSS و دادهٔ نمونه در GResource
- `data/`: Desktop Entry، AppStream، GSettings و آیکن‌های hicolor
- `build-aux/flatpak/`: manifest قابل‌شناسایی توسط GNOME Builder و Flatpak Builder
- `po/`: زیرساخت gettext و فهرست منابع قابل‌ترجمه
- `prototype/`: نمونهٔ قدیمی Vue/Vite که دیگر ورودی اصلی برنامه نیست

تم، رنگ accent و حالت high contrast مستقیماً توسط GTK و libadwaita اعمال می‌شوند و به پل یا لایهٔ نمایش جداگانه‌ای نیاز ندارند.
Bookmark، Watched و امتیاز شخصی از طریق Sync API در Simkl ثبت می‌شوند و state محلی فقط کش رابط و fallback است. Favorite فعلاً محلی است، چون به فهرست سفارشی Simkl متصل نشده است.
Explore در صورت تنظیم `TMDB_READ_TOKEN` از داده‌ها و تصاویر زندهٔ TMDB استفاده می‌کند و در نبود شبکه یا توکن به دادهٔ نمونهٔ داخلی برمی‌گردد.
اتصال Simkl از صفحهٔ Profile انجام می‌شود. Simkl عضویت عنوان‌ها در فهرست‌ها، وضعیت تماشا و امتیاز شخصی را مشخص می‌کند؛ اطلاعات نمایشی و کاورها با شناسهٔ TMDB همان عنوان دریافت می‌شوند.

اندازهٔ پیش‌فرض پنجره `1360×820` و حداقل اندازهٔ دسکتاپ `1120×640` است.

## اجرا

پروژه را مستقیماً در GNOME Builder باز کنید؛ Builder فایل Meson و manifest فلت‌پک را تشخیص می‌دهد و با دکمهٔ Run آن را build و اجرا می‌کند.

برای build و تست روی سیستم میزبان:

```bash
meson setup build --prefix="$PWD/_install"
meson compile -C build
meson test -C build --print-errorlogs
meson install -C build
./_install/bin/cineshelf
```

پس از اولین setup، برای buildهای بعدی فقط `meson compile -C build` لازم است. برای ساخت Flatpak:

```bash
flatpak-builder --user --install --force-clean flatpak-build \
  build-aux/flatpak/io.github.cineshelf.CineShelf.json
```

توکن TMDB را می‌توان با `TMDB_READ_TOKEN` یا فایل خصوصی `tmdb-read-token` در پوشهٔ تنظیمات برنامه ارائه کرد. Client ID و Access Token سرویس Simkl نیز از صفحهٔ Profile یا متغیرهای `SIMKL_CLIENT_ID` و `SIMKL_ACCESS_TOKEN` قابل‌ارائه‌اند؛ توکن‌ها عمداً در GSettings قرار نمی‌گیرند.

## ساختار اصلی

```text
.
├── meson.build
├── meson_options.txt
├── build-aux/flatpak/io.github.cineshelf.CineShelf.json
├── data/
│   ├── meson.build
│   ├── io.github.cineshelf.CineShelf.desktop.in
│   ├── io.github.cineshelf.CineShelf.metainfo.xml.in
│   ├── io.github.cineshelf.CineShelf.gschema.xml
│   └── icons/hicolor/
├── po/
├── src/
│   ├── meson.build
│   ├── cineshelf.in
│   └── cineshelf/
│       ├── application.py
│       ├── main.py
│       ├── window.py
│       ├── services/
│       ├── ui/window.ui
│       ├── style.css
│       └── library.json
├── tests/
└── prototype/
```
