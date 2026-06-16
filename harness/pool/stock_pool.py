"""
两层股票池 —— 100 主板精筛 + 50 用户自选。

日常分析只从池里筛（config.pool.analyze_only_from_pool=True），提升效率、
避免协调器漫无目的地全市场扫描。池外标的需显式 force 才分析。
"""
from __future__ import annotations

from ..config_loader import load_config, load_pool


class StockPool:
    def __init__(self):
        cfg = load_config()["pool"]
        main = load_pool(cfg["main_board_file"])
        watch = load_pool(cfg["watchlist_file"])
        self.main = {s["code"]: s for s in main.get("stocks", [])}
        self.watchlist = {s["code"]: s for s in watch.get("stocks", [])}
        self._restrict = cfg.get("analyze_only_from_pool", True)

    # --- 查询 ---------------------------------------------------------------
    def all_codes(self) -> list:
        """主板池 ∪ 自选池，自选优先（去重）。"""
        seen = dict(self.main)
        seen.update(self.watchlist)
        return list(seen.keys())

    def contains(self, code: str) -> bool:
        return code in self.main or code in self.watchlist

    def membership(self, code: str) -> dict:
        return {"in_main_pool": code in self.main,
                "in_watchlist": code in self.watchlist}

    def is_analyzable(self, code: str, force: bool = False) -> bool:
        """日常只分析池内标的；force=True 可越池（需协调器显式授权）。"""
        if force or not self._restrict:
            return True
        return self.contains(code)

    def info(self, code: str) -> dict:
        return self.watchlist.get(code) or self.main.get(code) or {"code": code}

    # --- 维护：自动剔除退市/暴雷（角色⑨）-----------------------------------
    def prune(self, codes) -> list:
        """从两层池移除给定代码（退市/暴雷）。返回实际移除的代码。"""
        removed = []
        for code in codes:
            if self.main.pop(code, None) is not None or self.watchlist.pop(code, None) is not None:
                removed.append(code)
        return removed

    def prune_by_screen(self, metrics_list, engine) -> list:
        """对一批标的跑红线排除，命中红线者剔出池（自动暴雷剔除）。"""
        bad = [m.code for m in metrics_list if engine.screen(m, {}).has_red_line]
        return self.prune(bad)

    # --- 统计 ---------------------------------------------------------------
    def stats(self) -> dict:
        return {"main": len(self.main), "watchlist": len(self.watchlist),
                "union": len(self.all_codes())}
