import asyncio
from core.vm_connector import vm_connector
import json

async def main():
    topo = await vm_connector.get_topology()
    with open("topo_dump.json", "w") as f:
        json.dump(topo, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
