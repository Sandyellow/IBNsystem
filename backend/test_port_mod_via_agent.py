import asyncio
from core.vm_connector import vm_connector

async def main():
    cmd = "curl -X POST -d '{\"dpid\": 1, \"port_no\": 1, \"config\": 1, \"mask\": 1}' http://127.0.0.1:8080/stats/portdesc/modify"
    resp = await vm_connector.exec_mininet_cmd(cmd)
    print(resp)

if __name__ == "__main__":
    asyncio.run(main())
