"""Synthetic profile data for offline layout checks; never installed."""

from collections import Counter
from datetime import date


def profile_stats(*, empty=False):
    today = date.today()
    result = {
        "watched_records": (),
        "movie_count": 0,
        "episode_count": 0,
        "movie_minutes": 0,
        "television_minutes": 0,
        "total_minutes": 0,
        "rating_histogram": Counter(),
        "rating_count": 0,
        "genres": Counter(),
        "activity": Counter(),
        "month_activity": {},
        "month_episode_count": 0,
        "month_movie_count": 0,
        "month_minutes": 0,
        "year_episode_count": 0,
        "year_movie_count": 0,
        "year_minutes": 0,
        "year_month_activity": Counter(),
        "active_days_year": 0,
    }
    if not empty:
        result.update(
            watched_records=tuple(range(48)),
            movie_count=32,
            episode_count=164,
            movie_minutes=3840,
            television_minutes=7380,
            total_minutes=11220,
            rating_histogram=Counter({10: 3, 9: 7, 8: 16, 7: 10, 6: 4}),
            rating_count=40,
            genres=Counter(
                {
                    "Drama": 24,
                    "Science Fiction": 18,
                    "Thriller": 13,
                    "Comedy": 9,
                    "Animation": 6,
                    "Adventure": 4,
                }
            ),
            activity=Counter({today: 4}),
            month_activity={today: 4},
            month_episode_count=12,
            month_movie_count=3,
            month_minutes=900,
            year_episode_count=104,
            year_movie_count=23,
            year_minutes=7440,
            year_month_activity=Counter(
                {1: 12, 2: 9, 3: 16, 4: 8, 5: 14, 6: 18, 7: 11, 8: 8, 9: 16, 10: 15}
            ),
            active_days_year=61,
        )
    return result
