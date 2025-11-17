import asyncio
from nats.aio.client import Client as NATS

async def main():
    # Connect to NATS (change host if needed)
    nc = NATS()
    await nc.connect("nats://localhost:4222")

    print("✅ Listening to ALL subjects using '>' wildcard...")

    async def message_handler(msg):
        subject = msg.subject
        data = msg.data.decode()
        print(f"[{subject}] {data}")

    # Subscribe to ALL subjects
    await nc.subscribe(">", cb=message_handler)

    # Keep running forever
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
