import asyncio
import sys
import json
sys.path.append('.')
from core.ryu_client import ryu_client

from core.topo_manager import topo_manager
from core.policy_executor import PolicyExecutor
from models.intent import ParsedIntent

from core.topo_manager import topo_manager
from core.policy_executor import PolicyExecutor
from models.intent import ParsedIntent
from core.ryu_client import ryu_client

async def test():
    await topo_manager.refresh()
    p = PolicyExecutor()
    intent = ParsedIntent(action='vlan', source_nodes=['h1', 'h2'], action_params={'vlan_id': 10}, scope='specific', direction='bidirectional')
    
    # Let's intercept apply_primitive
    original_apply = ryu_client.apply_primitive
    async def intercept(primitive):
        print("PRIMITIVE:", primitive)
        return await original_apply(primitive)
    ryu_client.apply_primitive = intercept
    
    res = await p._vlan(intent, 'test_id')
    print('VLAN_RESULT=', res)

import asyncio
asyncio.run(test())

