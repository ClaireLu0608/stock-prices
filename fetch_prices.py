#!/usr/bin/env python3
"""把实时报价抓下来写成 prices.json，供云端 routine 读取。

设计要点：
  - 单只失败不影响其他只，失败的记进 errors，不静默丢弃
  - 总是刷新 fetched_at_utc，让读取方能判断数据新鲜度
  - 全部失败才以非零码退出（让 Actions 标红），部分成功照常提交
"""
import json, os, sys, time
import urllib.request, urllib.error, urllib.parse

SYMBOLS = [
    # ── 持仓（算净值、查止损用）──
    "COP", "NEM", "JPM", "TSM", "XOM", "SLB",
    # ── 业绩基准 ──
    "VOO",   # 追踪 S&P 500，等于买下整个美国大盘
    "QQQ",   # 追踪纳斯达克 100，等于买下美国科技股
    # ── 板块 ETF：直接看到钱在往哪个行业流 ──
    "XLE",   # 能源
    "XLK",   # 科技
    "XLF",   # 金融
    "XLV",   # 医疗
    "XLU",   # 公用事业（利率敏感的典型）
    "XLP",   # 必需消费（防守）
    "XLY",   # 可选消费（经济好坏的温度计）
    "XLI",   # 工业
    "XLB",   # 材料
    "XLRE",  # 房地产——对利率最敏感的板块
    "XLC",   # 通讯服务（含 Meta、Google）
    # ── 宏观锚：把抽象概念变成能读的价格 ──
    "GLD",   # 黄金
    "TLT",   # 20年期以上美国国债——利率的镜子，利息涨它就跌
    "SHY",   # 1-3年短期国债——和 TLT 一对比就是"收益率曲线"，我们买 JPM 的依据
    "USO",   # 原油
    "IWM",   # 罗素2000小盘股——对利率最敏感，"利率如何影响股票"最好的教具
    "HYG",   # 高收益债（垃圾债）——市场压力的早期警报器，常比股市先跌
    "UUP",   # 美元指数——美元涨则大宗商品跌，影响石油仓位和台积电
    # ── 估值对照实验：高 PE vs 低 PE 在利率上行时的表现差异 ──
    "NVDA",  # PE 约 34
    "AMD",   # PE 约 131 —— 太贵，只观察不买
    # ── 候选替补：换股时有价格可参考，买之前就在名单上，不用临时改代码 ──
    "CVX",   # 雪佛龙——石油，对照 XOM
    "AEM",   # Agnico Eagle——金矿，对照 NEM
    "GS",    # 高盛——投行，对照 JPM 这种综合银行
    "MU",    # 美光——内存芯片，芯片周期的另一个观察点
    "AVGO",  # 博通——AI 芯片的另一极
    "WMT",   # 沃尔玛——消费者健康度最权威的读数
    "HD",    # 家得宝——房地产与大额消费
    "AAPL",  # 苹果——科技龙头权重股
    "MSFT",  # 微软——同上
    # ── 各板块龙头：板块指数动的时候，得知道是谁在动 ──
    "GOOGL", # 通讯服务（XLC 的最大权重）
    "META",  # 通讯服务
    "AMZN",  # 可选消费（XLY）
    "TSLA",  # 可选消费
    "LLY",   # 医疗（XLV）
    "UNH",   # 医疗保险
    "JNJ",   # 医疗，防守型
    "PG",    # 必需消费（XLP）
    "KO",    # 必需消费
    "COST",  # 必需消费
    "CAT",   # 工业（XLI），全球经济的风向标
    "GE",    # 工业
    "LIN",   # 材料（XLB）
    "NEE",   # 公用事业（XLU），对利率极敏感
    "PLD",   # 房地产（XLRE）
    "BAC",   # 金融，对照 JPM
    "BRK.B", # 伯克希尔，巴菲特的持仓组合
    "ORCL",  # 科技，AI 基建的另一条线
]

# 机器人可以往 watchlist.json 里写想跟踪的股票，这里自动合并进来。
# 上限 20 只，防止它无节制地扩张导致抓取时间失控。
try:
    with open("watchlist.json") as _f:
        _extra = [str(t).strip().upper() for t in json.load(_f).get("tickers", []) if str(t).strip()]
    _added = [t for t in _extra[:20] if t not in SYMBOLS]
    SYMBOLS = SYMBOLS + _added
    if _added:
        print(f"watchlist.json 追加了 {len(_added)} 只: {_added}")
except FileNotFoundError:
    pass
except Exception as _e:
    print(f"watchlist.json 读取失败（忽略，不影响主名单）: {_e}", file=sys.stderr)

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


# ── 宏观真实数据（Yahoo chart API，不需要密钥）──
# 为什么要这一段：机器人在云端拿不到这些数字，只能从新闻里抄。
# 2026-08-18 的第一份日报证明抄会错——油价、金价、SOX、10年期国债四个全抄错了，
# 其中国债那个连方向都反了（报告说"利息维持高位"，实际当天是跌的），
# 导致整条因果链变成事后编的故事。抓下来它就不用抄。
MACRO = {
    "SP500":  ("^GSPC",     "S&P 500 指数"),
    "NASDAQ": ("^IXIC",     "Nasdaq 综合指数"),
    "DOW":    ("^DJI",      "Dow 道琼斯工业指数"),
    "VIX":    ("^VIX",      "恐慌指数——低说明市场淡定，高说明在害怕"),
    "SOX":    ("^SOX",      "费城半导体指数"),
    "WTI":    ("CL=F",      "WTI 原油期货，美元/桶"),
    "GOLD":   ("GC=F",      "黄金期货，美元/盎司"),
    "US10Y":  ("^TNX",      "10 年期美国国债利息，%"),
    "US30Y":  ("^TYX",      "30 年期美国国债利息，%"),
    "DXY":    ("DX-Y.NYB",  "美元指数"),
}

def yahoo(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=2d&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        m = json.load(r)["chart"]["result"][0]["meta"]
    price = m.get("regularMarketPrice")
    prev  = m.get("chartPreviousClose") or m.get("previousClose")
    if price is None or not prev:
        raise ValueError(f"无效: price={price} prev={prev}")
    return {"price": round(price, 4), "prev_close": round(prev, 4),
            "change": round(price - prev, 4),
            "change_pct": round((price / prev - 1) * 100, 4)}

macro, macro_errors = {}, []
for key, (sym, desc) in MACRO.items():
    try:
        macro[key] = {**yahoo(sym), "symbol": sym, "desc": desc}
        print(f"  {key:7} {macro[key]['price']:>12}  ({macro[key]['change_pct']:+.2f}%)")
    except Exception as e:
        macro_errors.append({"key": key, "symbol": sym, "error": str(e)[:200]})
        print(f"  {key:7} 失败: {e}", file=sys.stderr)
    time.sleep(0.4)
# 宏观失败不影响主流程——个股报价才是算净值的命根子

out = {
    "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "fetched_at_unix": int(time.time()),
    "source": "finnhub.io/api/v1/quote + query1.finance.yahoo.com/v8/finance/chart",
    "symbols_requested": len(SYMBOLS),
    "symbols_ok": len(quotes),
    "quotes": quotes,
    "errors": errors,
    "macro": macro,
    "macro_errors": macro_errors,
}
with open("prices.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"\n个股 {len(quotes)}/{len(SYMBOLS)}，宏观 {len(macro)}/{len(MACRO)}，写入 prices.json")
if not quotes:
    print("FATAL: 全部失败", file=sys.stderr)
    sys.exit(1)
