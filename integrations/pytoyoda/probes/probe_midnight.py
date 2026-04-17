"""Probe what Toyota returns for the new day just after midnight local."""
import os
import asyncio
import json
from datetime import date, timedelta

from loguru import logger
logger.remove()
from pytoyoda import MyT
from pytoyoda.const import VEHICLE_TRIPS_ENDPOINT


async def main() -> None:
    client = MyT(username=os.environ["TOYOTA_USER"], password=os.environ["TOYOTA_PASS"])
    await client.login()
    vehicles = await client.get_vehicles()
    rav4 = next(v for v in vehicles if v.alias == "RAV4")

    today = date.today()
    print(f"Client local date: {today}")

    for label, from_d, to_d in [
        ("today-only", today, today),
        ("yesterday-only", today - timedelta(days=1), today - timedelta(days=1)),
        ("today+yesterday", today - timedelta(days=1), today),
        ("last-3-days", today - timedelta(days=2), today),
    ]:
        endpoint = VEHICLE_TRIPS_ENDPOINT.format(
            from_date=from_d, to_date=to_d,
            route=False, summary=True, limit=10, offset=0,
        )
        raw = await rav4._api.controller.request_json(
            method="GET", endpoint=endpoint, vin=rav4.vin
        )
        payload = raw.get("payload") or {}
        trips = payload.get("trips") or []
        summary = payload.get("summary") or []
        print(f"\n--- {label}: from={from_d} to={to_d} ---")
        print(f"  trips_count={len(trips)}")
        print(f"  summary_items={len(summary)}")
        for item in summary:
            histograms = item.get("histograms", [])
            print(
                f"    year={item.get('year')} month={item.get('month')} "
                f"item_summary={'OBJ' if item.get('summary') else 'None/missing'} "
                f"histograms={len(histograms)}"
            )
            if item.get("summary"):
                print(f"      agg: {json.dumps(item['summary'])}")
            for h in histograms:
                hs = h.get("summary")
                if hs:
                    print(
                        f"      day={h.get('day'):2}: length={hs.get('length')} "
                        f"duration={hs.get('duration')}"
                    )
                else:
                    print(f"      day={h.get('day'):2}: summary=None/missing")


asyncio.run(main())
