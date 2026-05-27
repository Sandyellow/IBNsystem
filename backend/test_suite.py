import asyncio
import logging
from unittest.mock import patch, MagicMock

# Set up logging to see errors
logging.basicConfig(level=logging.ERROR)

from models.intent import ParsedIntent, IntentAction
from core.intent_validator import intent_validator
from core.policy_executor import policy_executor
from core.topo_manager import topo_manager

# Mock topology data
mock_topo = {
    "nodes": [
        {"id": "h1", "type": "host", "mac": "00:00:00:00:11:01", "ip": "10.0.0.1", "connected_switch": "s1"},
        {"id": "h2", "type": "host", "mac": "00:00:00:00:11:02", "ip": "10.0.0.2", "connected_switch": "s2"},
        {"id": "h3", "type": "host", "mac": "00:00:00:00:11:03", "ip": "10.0.0.3", "connected_switch": "s3"},
        {"id": "s1", "type": "switch", "dpid": "1"},
        {"id": "s2", "type": "switch", "dpid": "2"},
        {"id": "s3", "type": "switch", "dpid": "3"}
    ],
    "links": [
        {"source": "h1", "target": "s1", "src_port": None, "dst_port": 1},
        {"source": "s1", "target": "s2", "src_port": 2, "dst_port": 2},
        {"source": "s2", "target": "h2", "src_port": 1, "dst_port": None},
    ]
}

# Apply mock topology
topo_manager._topology = mock_topo
topo_manager._hosts = [n for n in mock_topo["nodes"] if n["type"] == "host"]

async def run_tests():
    intents = [
        ParsedIntent(action=IntentAction.BLOCK_TRAFFIC, source_node="h1", target_node="h3", explanation="test block"),
        ParsedIntent(action=IntentAction.ALLOW_TRAFFIC, source_node="h1", target_node="h3", explanation="test allow"),
        ParsedIntent(action=IntentAction.RATE_LIMIT, source_node="h1", target_node="h2", parameters={"bandwidth_mbps": 10}, explanation="test rate limit"),
        ParsedIntent(action=IntentAction.SET_PRIORITY, source_node="h1", target_node="h2", parameters={"priority": 300}, explanation="test prio"),
        ParsedIntent(action=IntentAction.REDIRECT_TRAFFIC, source_node="h1", target_node="h2", parameters={"via_switch": "s3"}, explanation="test redirect"),
        ParsedIntent(action=IntentAction.QUERY_FLOWS, target_switch="s1", explanation="test query")
    ]
    
    passed = 0
    failed = 0
    
    from unittest.mock import AsyncMock
    with patch("core.policy_executor.ryu_client") as mock_ryu:
        mock_ryu.add_flow = AsyncMock(return_value=True)
        mock_ryu.add_meter = AsyncMock(return_value=True)
        mock_ryu.delete_flow_by_cookie = AsyncMock(return_value=True)
        mock_ryu.delete_meter = AsyncMock(return_value=True)
        mock_ryu.get_flows = AsyncMock(return_value=[])
        mock_ryu.get_port_stats = AsyncMock(return_value=[])

        for i, intent in enumerate(intents):
            try:
                # 1. Validation Test
                report = await intent_validator.validate(intent, mock_topo)
                
                # 2. Execution Test
                res = await policy_executor.execute(intent, f"test-intent-{i}")
                
                if res.get("success"):
                    passed += 1
                else:
                    print(f"Test Failed for {intent.action}: {res.get('error')}")
                    failed += 1
            except Exception as e:
                print(f"Exception in {intent.action}: {repr(e)}")
                failed += 1

    print(f"\n--- Test Results ---")
    print(f"Total: {len(intents)}, Passed: {passed}, Failed: {failed}")

if __name__ == "__main__":
    asyncio.run(run_tests())
