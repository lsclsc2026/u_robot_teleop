import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning BLE devices for 15 seconds...")
    devices = await BleakScanner.discover(timeout=15.0, return_adv=True)

    for device, adv in devices.values():
        name = device.name or adv.local_name or ""
        address = device.address
        rssi = getattr(adv, "rssi", None)

        if name:
            print(f"name={name!r} address={address} rssi={rssi}")

asyncio.run(main())
