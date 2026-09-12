# بخش‌های نمایشی برنامه (غیرعملیاتی)

معیار تشخیص: دکمه یا اکشنی که فقط `self._toast(...)` می‌کند و هیچ state، ناوبری یا درخواست شبکه واقعی ندارد، نمایشی محسوب می‌شود.

## کاملاً نمایشی (فقط Toast)

| قسمت | محل | رفتار فعلی |
|---|---|---|
| دکمه Storage سایدبار | `src/gisheh/window.py:4237` | همیشه `Library storage: 68% used` — عدد هاردکد، محاسبه واقعی ندارد |
| دکمه + سایدبار | `src/gisheh/window.py:4234` | فقط `Add dialog opened` — دیالوگ Add وجود ندارد |
| دکمه تقویم Explore | `src/gisheh/window.py:4222` | فقط `Release calendar opened` |
| دکمه `See all` سکشن‌های جزئیات | `src/gisheh/window.py:4084` | فقط `Open all ...` — صفحه لیست کامل ندارد |
| منوی `⋯` هر ردیف لیست | `src/gisheh/window.py:6662` | فقط `More options for ...` |
| تریلر Hero + کارت‌های Videos | `src/gisheh/window.py:6839` ، `7410` | اسم ویدیو از TMDB واقعی می‌آید (`video_titles`) ولی کلیک فقط `Playing ...` است — پلیر ندارد |
| کارت‌های `More like this` | `src/gisheh/window.py:7514` | فقط `Open ...` — ناوبری به تایتل مقصد نمی‌کند |
| Comments فصل / اپیزود | `src/gisheh/window.py:4250` ، `4258` | فقط `... comments opened` |
| Check-in اپیزود + منوهای `win.detail-comments/check-in/add-note` | `src/gisheh/window.py:4262` ، `8400` | فقط `... for {title}` — در Simkl ثبت نمی‌شود |
| دکمه‌های اکشن ناوبری اپیزود (`_detail_navigation_action`) | `src/gisheh/window.py:4042` به بعد | خود دکمه‌های Watched واقعی‌اند ولی Comments/Check-in تزئینی‌اند |

## نیمه‌نمایشی / ناقص

- **Favorite**: فقط local (`self.favorites` در `src/gisheh/window.py:1751`)، به گفته README عمداً به Simkl وصل نیست.
- **Cast fallback**: اگر TMDB کست ندهد، `Lead Ensemble / Supporting Ensemble` فیک ساخته می‌شود (`src/gisheh/window.py:6875`).
- **Videos fallback**: اگر TMDB ویدیو ندهد، `("New trailer", "Official trailer")` فیک (`src/gisheh/window.py:7416`).
- **Gallery fallback**: اگر عکس نباشد، رندر داخلی `GeneratedPosterWidget` — عمدی و قابل قبول است.
- **Ratings نمایشی `IMDb/Meta/Match`**: وقتی `external_ratings` خالی است از روی ریتینگ داخلی حدس زده می‌شود (`src/gisheh/window.py:6850`).

## عملیاتی واقعی (برای تفکیک)

جستجو/فیلتر/سورت، نمای لیست/گرید، جزئیات TMDB، Explore + صفحه‌بندی + جستجوی TMDB، سینک Simkl، Watched/Bookmark/امتیاز ۱-۱۰ (از طریق Simkl)، ناوبری فصل/اپیزود + preload فصل، پروفایل، MediaViewer (زوم/فول‌اسکرین/کپی واقعی)، لاگ برنامه.
