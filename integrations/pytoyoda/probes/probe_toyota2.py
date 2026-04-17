"""Check older months + non-summary trips for the RAV4."""
import os
import asyncio
from datetime import date, timedelta

from loguru import logger
logger.remove()
from pytoyoda import MyT


async def main() -> None:
    client = MyT(username=os.environ["TOYOTA_USER"], password=os.environ["TOYOTA_PASS"])
    await client.login()
    vehicles = await client.get_vehicles()
    rav4 = next(v for v in vehicles if v.alias == "RAV4")
    await rav4.update()

    today = date.today()

    # Check 3 prior calendar months
    for months_ago in (1, 2, 3):
        y, m = today.year, today.month - months_ago
        while m <= 0:
            m += 12
            y -= 1
        from_date = date(y, m, 1)
        to_date = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
        resp = await rav4._api.get_trips(
            rav4.vin, from_date, to_date, summary=True, limit=1, offset=0
        )
        items = (resp.payload.summary or []) if resp.payload else []
        print(f"\n=== summary=True month={y}-{m:02} ===  items={len(items)}")
        for item in items:
            has_item_summary = item.summary is not None
            histograms = item.histograms or []
            non_null = sum(1 for h in histograms if h.summary is not None)
            print(
                f"  item.summary={'OBJ' if has_item_summary else 'None'} "
                f"histograms={len(histograms)} non_null={non_null}"
            )
            if has_item_summary:
                s = item.summary
                print(f"    aggregate length={s.length} duration={s.duration}")

    # Non-summary trips for the last 7 days
    from_date = today - timedelta(days=7)
    resp = await rav4._api.get_trips(
        rav4.vin, from_date, today, summary=False, limit=20, offset=0
    )
    trips = (resp.payload.trips or []) if resp.payload else []
    print(f"\n=== summary=False last 7 days ===  trip_count={len(trips)}")
    for t in trips[:5]:
        s = t.summary
        if s is None:
            print(f"  trip {t.id}: summary=None")
        else:
            print(
                f"  trip {t.id}: start={s.start_ts} end={s.end_ts} "
                f"length={s.length} duration={s.duration}"
            )


asyncio.run(main())
