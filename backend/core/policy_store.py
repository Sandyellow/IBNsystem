"""
本地策略与 Meter ID 持久化。
"""

import json
import os
import logging
from typing import Dict, Any, Tuple
from config import settings
from models.policy import ActivePolicy

logger = logging.getLogger(__name__)

# 数据存储目录和文件路径
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
POLICY_FILE = os.path.join(DATA_DIR, "policies.json")

def _ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def save_policies(active_policies: Dict[str, ActivePolicy], meter_counter: int) -> bool:
    """持久化保存当前活跃策略和 Meter 计数器到本地 JSON 文件"""
    _ensure_data_dir()
    try:
        data = {
            "meter_counter": meter_counter,
            "policies": {k: v.model_dump() for k, v in active_policies.items()}
        }
        with open(POLICY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"已成功保存 {len(active_policies)} 条策略到本地。")
        return True
    except Exception as e:
        logger.error(f"保存策略到本地失败: {e}")
        return False

def load_policies() -> Tuple[Dict[str, ActivePolicy], int]:
    """从本地 JSON 文件加载活跃策略和 Meter 计数器"""
    if not os.path.exists(POLICY_FILE):
        return {}, 200  # 默认起始 _meter_counter = 200

    try:
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        meter_counter = data.get("meter_counter", 200)
        policies_data = data.get("policies", {})
        
        active_policies = {}
        for k, v in policies_data.items():
            try:
                active_policies[k] = ActivePolicy.model_validate(v)
            except Exception as validate_e:
                logger.warning(f"解析策略 {k} 失败，已忽略: {validate_e}")
                
        logger.info(f"成功从本地加载了 {len(active_policies)} 条策略，Meter 起点={meter_counter}。")
        return active_policies, meter_counter
    except Exception as e:
        logger.error(f"加载本地策略失败: {e}")
        return {}, 200
