import asyncio
from bleak import BleakClient

ADDRESS = "98:DA:10:09:E5:A7"

async def main():
    print(f"Connecting to {ADDRESS} ...")
    async with BleakClient(ADDRESS, timeout=20.0) as client:
        print("connected:", client.is_connected)

        services = client.services
        for s in services:
            print(f"\nSERVICE {s.uuid} {s.description}")
            for c in s.characteristics:
                print(f"  CHAR {c.uuid} {c.description} props={c.properties}")

asyncio.run(main())
