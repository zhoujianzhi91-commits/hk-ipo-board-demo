#!/usr/bin/env python3
"""
港股IPO数据自动化修复脚本
一键补全所有新上市股票的缺失数据

用法: python3 scripts/auto_fix_data.py
"""

import json, re, os, sys
import urllib.request
import shutil
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent

def main():
    print("="*60)
    print("🔄 港股IPO数据自动修复")
    print("="*60)
    
    # 1. 加载所有数据源
    ipo = load_json(ROOT / "data/ipo-history-2026.js", "IPO_HISTORY_2026")
    updates = load_json(ROOT / "site-dist/data/official-updates-2026.js", "OFFICIAL_UPDATES_2026")
    latest = load_json(ROOT / "site-dist/data/latest-listed-2026.js", "LATEST_LISTED_2026")
    
    updates_map = {s["stockCode"]: s for s in updates.get("stocks", []) if isinstance(s, dict)}
    latest_map = {s["stockCode"]: s for s in latest if isinstance(s, dict)}
    ipo_codes = {s["stockCode"] for s in ipo}
    
    fixed = 0
    
    # 2. 遍历所有在 official-updates 和 latest-listed 中的股票
    all_codes = set(updates_map.keys()) | set(latest_map.keys())
    
    for code in sorted(all_codes):
        if code in ipo_codes:
            # 已在 ipo-history 中 → 检查是否缺失字段，从其他源补
            s = next(x for x in ipo if x["stockCode"] == code)
            changed = fix_stock_fields(s, updates_map.get(code, {}), latest_map.get(code, {}))
            if changed:
                print(f"  ✅ {code}: 补全字段")
                fixed += 1
        else:
            # 不在 ipo-history 中 → 从其他源写入
            new_stock = build_new_stock(code, updates_map.get(code, {}), latest_map.get(code, {}))
            if new_stock:
                ipo.append(new_stock)
                ipo_codes.add(code)
                print(f"  ✅ {code}: 新增到 IPO_HISTORY ({new_stock.get('name','')})")
                fixed += 1
    
    # 3. 清理 official-updates 中会覆盖 ipo-history 完整 basis 的字段
    for s in updates.get("stocks", []):
        if not isinstance(s, dict): continue
        code = s.get("stockCode", "")
        if code not in ipo_codes: continue
        ipo_stock = next((x for x in ipo if x["stockCode"] == code), None)
        if not ipo_stock: continue
        
        # 如果 IPO_HISTORY 有 >=10 行的完整 basis，清除 OFFICIAL_UPDATES 的 basis
        ipo_basis = ipo_stock.get("basisOfAllocation", [])
        up_basis = s.get("basisOfAllocation", [])
        if len(ipo_basis) >= 10 and 0 < len(up_basis) < 10:
            print(f"  🧹 {code}: 清除 OFFICIAL_UPDATES 的不完整 basis ({len(up_basis)}行)")
            s["basisOfAllocation"] = []
        
        # 如果 OFFICIAL_UPDATES 的 sharesPerLot 与 IPO_HISTORY 不一致，修正
        up_lot = s.get("sharesPerLot")
        ipo_lot = ipo_stock.get("sharesPerLot")
        if up_lot and ipo_lot and up_lot != ipo_lot:
            print(f"  🧹 {code}: 修正 sharesPerLot {up_lot}→{ipo_lot}")
            s["sharesPerLot"] = ipo_lot
    
    # 4. 排序
    ipo.sort(key=lambda s: (s.get("listDate") or "") if s.get("listDate") else "", reverse=True)
    
    # 5. 写出所有文件
    write_json(ROOT / "data/ipo-history-2026.js", "window.IPO_HISTORY_2026", ipo)
    write_json(ROOT / "site-dist/data/official-updates-2026.js", "window.OFFICIAL_UPDATES_2026", updates)
    
    # 6. 复制到 site-dist
    import shutil
    shutil.copy2(ROOT / "data/ipo-history-2026.js", ROOT / "site-dist/data/ipo-history-2026.js")
    
    print(f"\n{'='*60}")
    print(f"✅ 完成! 修复/新增 {fixed} 只股票")
    print(f"当前 IPO_HISTORY: {len(ipo)} 只")
    print(f"{'='*60}")
    
    # 7. 打印缺失报告
    print("\n📋 仍缺失数据的已上市股票:")
    check_remaining(ipo, ROOT)


def load_json(path, var_name):
    with open(path) as f:
        content = f.read()
    # 移除 window.VAR_NAME = 前缀和结尾分号
    content = content.replace(f"window.{var_name} = ", "", 1).strip()
    if content.endswith(";"):
        content = content[:-1]
    return json.loads(content)


def write_json(path, var_name, data):
    output = f"window.{var_name} = {json.dumps(data, ensure_ascii=False, indent=2)};"
    with open(path, "w") as f:
        f.write(output)


def fix_stock_fields(s, updates_data, latest_data):
    """从 updates 和 latest 补全缺失字段"""
    changed = False
    
    # 优先使用 latest-listed (最完整)
    src = latest_data if latest_data else updates_data
    if not src:
        return False
    
    for key in ["offerPrice", "sharesPerLot", "totalOfferShares", 
                 "publicOfferSharesBefore", "publicOfferSharesFinal", 
                 "publicOfferMultiple", "totalApplications", "successfulApplications",
                 "finalPublicOfferPercent", "status", "listDate", "mechanism",
                 "listingType", "groupTotals", "englishName"]:
        if s.get(key) is None and src.get(key) is not None:
            s[key] = src[key]
            changed = True
    
    # Application summary
    src_app = src.get("applicationSummary")
    if src_app and isinstance(src_app, dict):
        if s.get("applicationSummary") is None:
            s["applicationSummary"] = {}
            changed = True
        for k, v in src_app.items():
            if v is not None and s["applicationSummary"].get(k) is None:
                s["applicationSummary"][k] = v
                changed = True
    
    # 如果没有 basis 但 official-updates 或 latest 有，复制过来
    if not s.get("basisOfAllocation") and src.get("basisOfAllocation"):
        s["basisOfAllocation"] = src["basisOfAllocation"]
        changed = True
        # 重新计算中签率
        if s.get("sharesPerLot"):
            lot = s["sharesPerLot"]
            for r in s["basisOfAllocation"]:
                if r.get("group") == "A" and r.get("sharesApplied") == lot:
                    ap = r.get("approxPercent")
                    if ap is not None:
                        s["actualOneLotHitRate"] = float(ap)
                    break
    
    # 计算 minAmountHKD
    app = s.get("applicationSummary") or {}
    if app.get("minAmountHKD") is None and s.get("offerPrice") and s.get("sharesPerLot"):
        app["minAmountHKD"] = round(s["offerPrice"] * s["sharesPerLot"], 2)
        s["applicationSummary"] = app
        changed = True
    if app.get("minShares") is None and s.get("sharesPerLot"):
        app["minShares"] = s["sharesPerLot"]
        s["applicationSummary"] = app
        changed = True
    if app.get("minLots") is None and s.get("sharesPerLot"):
        app["minLots"] = 1
        s["applicationSummary"] = app
        changed = True
    
    # 估算中签率
    if s.get("actualOneLotHitRate") is None:
        sp = s.get("successfulApplications")
        tp = s.get("totalApplications")
        if sp and tp and tp > 0 and sp < tp:
            s["actualOneLotHitRate"] = round(sp / tp * 100, 4)
            changed = True
    
    return changed


def build_new_stock(code, updates_data, latest_data):
    """从已有数据源构建一个完整的股票条目"""
    src = latest_data if latest_data else updates_data
    if not src:
        return None
    
    name = src.get("name") or src.get("englishName", "")
    if not name:
        return None
    
    stock = {
        "stockCode": code,
        "name": name,
        "englishName": src.get("englishName", ""),
        "status": src.get("status", "current"),
        "listDate": src.get("listDate", ""),
        "offerPrice": src.get("offerPrice"),
        "sharesPerLot": src.get("sharesPerLot"),
        "totalOfferShares": src.get("totalOfferShares"),
        "marketCap": src.get("marketCap"),
        "listingMarketCap": src.get("listingMarketCap"),
        "publicOfferSharesBefore": src.get("publicOfferSharesBefore") or src.get("publicOfferSharesFinal"),
        "publicOfferSharesFinal": src.get("publicOfferSharesFinal") or src.get("publicOfferSharesBefore"),
        "publicOfferMultiple": src.get("publicOfferMultiple"),
        "totalApplications": src.get("totalApplications"),
        "successfulApplications": src.get("successfulApplications"),
        "mechanism": src.get("mechanism", "主板B"),
        "listingType": src.get("listingType", "H股"),
        "groupTotals": src.get("groupTotals", {}),
        "source": src.get("source", {}),
        "applicationSummary": {},
        "basisOfAllocation": src.get("basisOfAllocation", []),
        "finalPublicOfferPercent": src.get("finalPublicOfferPercent"),
        "actualOneLotHitRate": None,
    }
    
    # Application summary
    src_app = src.get("applicationSummary")
    if src_app and isinstance(src_app, dict):
        stock["applicationSummary"] = dict(src_app)
    
    app = stock["applicationSummary"]
    if app.get("minAmountHKD") is None and stock.get("offerPrice") and stock.get("sharesPerLot"):
        app["minAmountHKD"] = round(stock["offerPrice"] * stock["sharesPerLot"], 2)
    if app.get("minShares") is None and stock.get("sharesPerLot"):
        app["minShares"] = stock["sharesPerLot"]
    if app.get("minLots") is None and stock.get("sharesPerLot"):
        app["minLots"] = 1
    
    # 中签率
    basis = stock["basisOfAllocation"]
    if basis and stock.get("sharesPerLot"):
        lot = stock["sharesPerLot"]
        for r in basis:
            if r.get("group") == "A" and r.get("sharesApplied") == lot:
                ap = r.get("approxPercent")
                if ap is not None:
                    stock["actualOneLotHitRate"] = float(ap)
                break
    
    if stock["actualOneLotHitRate"] is None:
        sp = stock.get("successfulApplications")
        tp = stock.get("totalApplications")
        if sp and tp and tp > 0 and sp < tp:
            stock["actualOneLotHitRate"] = round(sp / tp * 100, 4)
    
    return stock


def check_remaining(ipo, root):
    """打印仍有缺失的已上市股票"""
    import json
    mp_path = root / "site-dist/data/market-performance-2026.js"
    cp_path = root / "site-dist/data/company-profiles-2026.js"
    
    mp = {}
    if mp_path.exists():
        with open(mp_path) as f:
            c = f.read()
        c = c.replace("window.MARKET_PERFORMANCE_2026 = ", "", 1)
        mp = json.loads(c.rstrip().rstrip(";"))
    
    profile_codes = set()
    if cp_path.exists():
        with open(cp_path) as f:
            c = f.read()
        c = c.replace("window.COMPANY_PROFILES_2026 = ", "", 1)
        cp = json.loads(c.rstrip().rstrip(";"))
        profile_codes = set(cp.get("profiles", {}).keys())
    
    any_missing = False
    for s in ipo:
        code = s["stockCode"]
        if s.get("status") != "listed": continue
        ld = (s.get("listDate") or "")
        if ld and ld < "2026-01-01": continue
        
        missing = []
        if s.get("sharesPerLot") is None: missing.append("每手")
        app = s.get("applicationSummary") or {}
        if app.get("minAmountHKD") is None: missing.append("入场费")
        if s.get("publicOfferSharesFinal") is None: missing.append("公开手数")
        if s.get("actualOneLotHitRate") is None: missing.append("中签率")
        if code not in mp or not mp.get(code, {}).get("greyMarket"): missing.append("暗盘")
        if code not in mp or not mp.get(code, {}).get("firstDay"): missing.append("首日")
        if code not in profile_codes: missing.append("速读")
        
        basis = s.get("basisOfAllocation", [])
        if len(basis) == 0 and s.get("listDate", "") < "2026-06-15": missing.append("中签曲线")
        
        if missing:
            any_missing = True
            print(f"  ❌ {code} {s.get('name','?')[:20]}: {', '.join(missing)}")
    
    if not any_missing:
        print("  ✅ 所有已上市股票数据完整!")


if __name__ == "__main__":
    main()
