from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import re
from dateutil import parser as dateparser

app = FastAPI(title="Yilan Website Monitor API", version="1.0.0")


# ---- 測試用：確認伺服器活著 ----
@app.get("/ping")
def ping():
    return {"message": "pong"}


# ---- 79 個站台網址清單 ----
RAW_URLS = [
    "https://www.e-land.gov.tw",
    "https://enwww.e-land.gov.tw",
    "https://civil.e-land.gov.tw/",
    "https://bt.e-land.gov.tw/",
    "https://wres.e-land.gov.tw/",
    "https://agri.e-land.gov.tw/",
    "https://sntroot.e-land.gov.tw/",
    "https://labor.e-land.gov.tw/",
    "https://planning.e-land.gov.tw/",
    "https://personnel.e-land.gov.tw/",
    "https://ethics.e-land.gov.tw/",
    "https://fire.e-land.gov.tw/",
    "https://www.ilccb.gov.tw/",
    "https://fuyuan.e-land.gov.tw/",
    "https://gym.e-land.gov.tw/",
    "https://animal.e-land.gov.tw/",
    "https://yihistory.e-land.gov.tw/",
    "https://www.suao.gov.tw/",
    "https://toucheng.e-land.gov.tw/",
    "https://jiaosi.e-land.gov.tw/",
    "https://www.jw.gov.tw/",
    "https://www.yuanshan.gov.tw/",
    "https://ilwct.e-land.gov.tw/",
    "https://www.sanshing.gov.tw/",
    "http://www.datong.e-land.gov.tw/",
    "https://www.nanao.e-land.gov.tw/",
    "https://memorial.e-land.gov.tw/",
    "https://lcwh.e-land.gov.tw",
    "https://renshan.e-land.gov.tw/",
    "https://yidp.e-land.gov.tw",
    "https://ms.e-land.gov.tw",
    "https://bgacst.e-land.gov.tw/",
    "https://www.ilcpb.gov.tw/",
    "https://www.ilshb.gov.tw/",
    "https://ilhhr.e-land.gov.tw/",
    "https://ldhro.e-land.gov.tw/",
    "https://tchhr.e-land.gov.tw/",
    "https://sahhr.e-land.gov.tw/",
    "https://yshhr.e-land.gov.tw/",
    "https://jwhhr.e-land.gov.tw/",
    "https://tshhr.e-land.gov.tw/",
    "https://wjhhr.e-land.gov.tw",
    "https://tthhr.e-land.gov.tw/",
    "https://nahhr.e-land.gov.tw/",
    "https://jxhhr.e-land.gov.tw/",
    "https://sshhr.e-land.gov.tw/",
    "https://aborigines.e-land.gov.tw/",
    "https://fisheries.e-land.gov.tw/",
    "https://arbor.e-land.gov.tw/",
    "https://ilanland.e-land.gov.tw/",
    "https://ilcpbil.e-land.gov.tw/",
    "https://ilcpbld.e-land.gov.tw/",
    "https://ilcpbjs.e-land.gov.tw/",
    "https://ilcpbsa.e-land.gov.tw/",
    "https://ilcpbss.e-land.gov.tw/",
    "https://yil.ilshb.gov.tw",
    "https://luo.ilshb.gov.tw",
    "https://sua.ilshb.gov.tw",
    "https://tou.ilshb.gov.tw",
    "https://jia.ilshb.gov.tw",
    "https://jhu.ilshb.gov.tw",
    "https://yua.ilshb.gov.tw",
    "https://don.ilshb.gov.tw",
    "https://wuj.ilshb.gov.tw",
    "https://san.ilshb.gov.tw",
    "https://dat.ilshb.gov.tw",
    "https://nan.ilshb.gov.tw",
    "https://ltc.ilshb.gov.tw/",
    "https://yilan.e-land.gov.tw/",
    "https://www.lotong.gov.tw/",
    "https://www.dongshan.gov.tw/",
    "https://ymoa.e-land.gov.tw",
    "https://twtm.e-land.gov.tw",
    "https://idipc.e-land.gov.tw/",
    "https://trp.e-land.gov.tw/",
    "https://www.iltb.gov.tw/",
    "https://land.e-land.gov.tw/",
    "https://lotung-land.e-land.gov.tw/",
    "https://eadept.e-land.gov.tw/",
]

# 之後若你想要改「名稱」，可以把 name 換成中文；目前先用網址當名稱
SITES = [{"name": url.strip(), "url": url.strip()} for url in RAW_URLS]


# ---- 回傳資料的格式定義 ----
class SiteResult(BaseModel):
    name: str
    url: str
    latest_date: Optional[str] = None  # yyyy-mm-dd
    latest_title: Optional[str] = None
    days_since: Optional[int] = None
    status: str                     # ok / outdated / unknown
    note: Optional[str] = None


class CheckAllResponse(BaseModel):
    checked_at: str
    results: List[SiteResult]


# ---- 日期解析規則 ----
DATE_PATTERNS = [
    r"\d{4}[/-]\d{1,2}[/-]\d{1,2}",     # 2025/11/26 或 2025-11-26
    r"\d{3}[/-]\d{1,2}[/-]\d{1,2}",     # 114/11/26（民國年）
]


def parse_date(text: str) -> Optional[datetime]:
    text = text.strip()
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            ds = m.group(0)
            parts = re.split(r"[/-]", ds)
            # 民國年轉西元
            if len(parts[0]) == 3:
                year = 1911 + int(parts[0])
                ds = f"{year}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            try:
                return dateparser.parse(ds)
            except Exception:
                pass
    # 若前面沒抓到，再交給 dateparser 自己亂試一次
    try:
        return dateparser.parse(text, fuzzy=True)
    except Exception:
        return None


# ---- 單一站台檢查 ----
async def check_one_site(name: str, url: str) -> SiteResult:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 嘗試找常見「最新消息」區塊
        candidate_blocks = []
        selectors = [
            ".news", ".latest", ".list", ".announcement",
            "#news", "#latest", "#announcement"
        ]
        for sel in selectors:
            candidate_blocks.extend(soup.select(sel))

        if not candidate_blocks:
            # 找不到就整頁掃一次
            candidate_blocks = [soup]

        best_date: Optional[datetime] = None
        best_title: Optional[str] = None

        for block in candidate_blocks:
            text = block.get_text(" ", strip=True)
            d = parse_date(text)
            if d:
                if (best_date is None) or (d > best_date):
                    best_date = d
                    # 標題先抓附近一段文字，之後交給 GPT 再縮成 10 個字
                    best_title = text[:40]

        if not best_date:
            return SiteResult(
                name=name,
                url=url,
                status="unknown",
                note="頁面無法解析日期，需人工確認",
            )

        today = datetime.now(timezone.utc)
        days = (today - best_date.astimezone(timezone.utc)).days
        status = "ok" if days <= 30 else "outdated"

        return SiteResult(
            name=name,
            url=url,
            latest_date=best_date.date().isoformat(),
            latest_title=best_title or "",
            days_since=days,
            status=status,
            note="",
        )

    except Exception as e:
        return SiteResult(
            name=name,
            url=url,
            status="unknown",
            note=f"連線或解析錯誤：{e}",
        )


# ---- 全部站台檢查的 API ----
@app.get("/check-all", response_model=CheckAllResponse)
async def check_all():
    now = datetime.now(timezone.utc).isoformat()
    results: List[SiteResult] = []

    # 先用「一個一個跑」，雖然慢一點，但邏輯清楚也比較不容易出錯
    for site in SITES:
        res = await check_one_site(site["name"], site["url"])
        results.append(res)

    return CheckAllResponse(
        checked_at=now,
        results=results
    )
