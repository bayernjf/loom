"""配置中心消费侧：标量旋钮统一入口（M10c）。

knob(key) 读进程内 config_cache；缓存未引导（如测试/启动前）或键缺失时，
回落种子表中的拍板默认值——默认值单一事实源是 seeds.CONFIG_SEEDS，不二次抄写。
类型由发布校验保证（int/float/bool/string），调用处按种子类型直接使用。
"""

from app.core.config_center.cache import config_cache
from app.core.config_center.seeds import SEED_BY_KEY


def knob(key: str):
    default = SEED_BY_KEY[key][3]
    return config_cache.get(key, default)
