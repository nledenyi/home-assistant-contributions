"""Dump raw Toyota /trips summary response to see what the API returns for RAV4."""
import os
import asyncio
import sys
from datetime import date

# Silence pytoyoda's loguru firehose
from loguru import logger
logger.remove()

from pytoyoda import MyT


async def main() -> None:
    client = MyT(username=os.environ["TOYOTA_USER"], password=os.environ["TOYOTA_PASS"])
    await client.login()
    vehicles = await client.get_vehicles()
    for v in vehicles:
        alias = getattr(v, "alias", None) or ""
        vin_tail = (v.vin or "------")[-6:]
        print(f"\n=== Vehicle: alias={alias!r} vin=...{vin_tail} ===")
        await v.update()

        today = date.today()
        from_date = today.replace(day=1)
        print(f"from_date={from_date} to_date={today}")

        resp = await v._api.get_trips(
            v.vin, from_date, today, summary=True, limit=1, offset=0
        )
        if resp.payload is None:
            print("  payload=None")
            continue

        print(f"  resp.payload.summary length: {len(resp.payload.summary or [])}")
        for i, item in enumerate(resp.payload.summary or []):
            print(f"\n--- summary[{i}] year={item.year} month={item.month} ---")
            s = item.summary
            if s is None:
                print("  item.summary = None")
            else:
                print(
                    f"  item.summary.length={s.length} "
                    f"duration={s.duration} "
                    f"max_speed={s.max_speed} "
                    f"average_speed={s.average_speed} "
                    f"fuel={s.fuel_consumption}"
                )
            print(f"  histograms ({len(item.histograms or [])}):")
            for h in (item.histograms or [])[:20]:
                hs = h.summary
                if hs is None:
                    print(f"    day={h.day:2}: summary=None")
                else:
                    print(
                        f"    day={h.day:2}: length={hs.length} "
                        f"duration={hs.duration} max_speed={hs.max_speed}"
                    )
            extra = len(item.histograms or []) - 20
            if extra > 0:
                print(f"    ... +{extra} more")


asyncio.run(main())
