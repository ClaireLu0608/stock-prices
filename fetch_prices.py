#!/usr/bin/env python3
"""把实时报价抓下来写成 prices.json，供云端 routine 读取。

设计要点：
  - 单只失败不影响其他只，失败的记进 errors，不静默丢弃
  - 总是刷新 fetched_at_utc，让读取方能判断数据新鲜度
  - 全部失败才以非零码退出（让 Actions 标红），部分成功照常提交
"""
import json, os, sys, time
import urllib.request, urllib.error

SYMBOLS = ["COP", "NEM", "JPM", "TSM", "XOM", "SLB",   # 持仓
           "VOO", "QQQ",                               # 基准
           "NVDA", "AMD"]                              # 观察名单

TOKEN = os.environ.get("FINNHUB_TOKEN", "").strip()
if not TOKEN:
    print("FATAL: 缺少 FINNHUB_TOKEN（应配置为仓库 Secret）", file=sys.stderr)
    sys.exit(1)

def quote(sym):
    url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={TOKEN}"
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.load(r)
    # c=现价 d=涨跌 dp=涨跌幅 pc=昨收 o=开盘 h=最高 l=最低 t=报价unix时间
    if not d.get("c"):                       # 0 或缺失都视为无效
        raise ValueError(f"无效报价: {d}")
    return {"price": d.get("c"), "change": d.get("d"), "change_pct": d.get("dp"),
            "prev_close": d.get("pc"), "open": d.get("o"),
            "high": d.get("h"), "low": d.get("l"), "quote_unix": d.get("t")}

quotes, errors = {}, []
for s in SYMBOLS:
    try:
        quotes[s] = quote(s)
        print(f"  {s:5} {quotes[s]['price']}")
    except Exception as e:
        errors.append({"symbol": s, "error": str(e)[:200]})
        print(f"  {s:5} 失败: {e}", file=sys.stderr)
    time.sleep(1.2)                          # 免费额度 60次/分钟，留足余量

out = {
    "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "fetched_at_unix": int(time.time()),
    "source": "finnhub.io/api/v1/quote",
    "symbols_requested": len(SYMBOLS),
    "symbols_ok": len(quotes),
    "quotes": quotes,
    "errors": errors,
}
with open("prices.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"\n成功 {len(quotes)}/{len(SYMBOLS)}，写入 prices.json")
if not quotes:
    print("FATAL: 全部失败", file=sys.stderr)
    sys.exit(1)
