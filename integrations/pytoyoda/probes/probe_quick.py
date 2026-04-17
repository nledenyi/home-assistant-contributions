"""Quick Toyota API check - odometer + fuel."""
import asyncio
import os

from loguru import logger
logger.remove()
from pytoyoda import MyT


async def main() -> None:
    client = MyT(
        username=os.environ["TOYOTA_USER"],
        password=os.environ["TOYOTA_PASS"],
    )
    await client.login()
    vehicles = await client.get_vehicles()
    for v in vehicles:
        try:
            await v.update()
            print(
                f"{v.alias}: fuel={getattr(v.dashboard, 'fuel_level', '?')}% "
                f"range={getattr(v.dashboard, 'fuel_range', '?')}km "
                f"odo={getattr(v.dashboard, 'odometer', '?')}km"
            )
        except Exception as e:
            print(f"{v.alias}: ERROR {type(e).__name__}: {e}")


asyncio.run(main())
