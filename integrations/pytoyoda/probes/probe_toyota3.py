"""Dump raw JSON from Toyota /v1/trips to check if the summary field moved."""
import os
import asyncio
import json
from datetime import date, timedelta

from loguru import logger
logger.remove()
from pytoyoda import MyT


async def main() -> None:
    client = MyT(username=os.environ["TOYOTA_USER"], password=os.environ["TOYOTA_PASS"])
    await client.login()
    vehicles = await client.get_vehicles()
    rav4 = next(v for v in vehicles if v.alias == "RAV4")

    from_d = date.today() - timedelta(days=7)
    to_d = date.today()
    from pytoyoda.const import VEHICLE_TRIPS_ENDPOINT
    endpoint = VEHICLE_TRIPS_ENDPOINT.format(
        from_date=from_d,
        to_date=to_d,
        route=False,
        summary=True,
        limit=5,
        offset=0,
    )
    raw = await rav4._api.controller.request_json(
        method="GET", endpoint=endpoint, vin=rav4.vin
    )
    print(json.dumps(raw, indent=2, default=str)[:12000])


asyncio.run(main())
