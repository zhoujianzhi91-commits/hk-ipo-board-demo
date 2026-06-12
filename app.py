#!/usr/bin/env python3

import json
import math
import os
import re
import ssl
import socket
import subprocess
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "hk-ipo.html"
HKEX_TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh"
HKEX_NEW_LISTING_INFO_URL = "https://www2.hkexnews.hk/new-listings/new-listing-information/main-board?sc_lang=zh-HK"
HKEX_PREDEFINED_ALLOTMENT_URL = "https://www1.hkexnews.hk/search/predefineddoc.xhtml?lang=zh&predefineddocuments=4"
OFFICIAL_UPDATES_FILE = ROOT / "data" / "official-updates-2026.js"
OFFICIAL_UPDATES_GLOBAL = "window.OFFICIAL_UPDATES_2026"
OFFICIAL_UPDATE_API_VERSION = "2026-05-18-title-search-v4-live-subscription"
PRELISTING_PARSE_VERSION = "2026-05-18-pymupdf-v2"
ESTIMATED_SUBSCRIPTION_SOURCE = "致富证券"


def read_html_stocks():
    text = HTML_FILE.read_text(encoding="utf-8")
    stock_ids = read_hkex_stock_ids(text)
    stocks = []
    for block in re.finditer(r"\{\s*stockCode:\"(\d{5})\"([\s\S]*?)basisOfAllocation:\[\]\s*\}", text):
        body = block.group(2)
        status = string_field(body, "status")
        stocks.append({
            "code": block.group(1),
            "name": string_field(body, "name"),
            "englishName": string_field(body, "englishName"),
            "status": status or "current",
            "listDate": string_field(body, "listDate"),
            "mechanism": string_field(body, "mechanism"),
            "listingType": string_field(body, "listingType"),
            "stockId": stock_ids.get(block.group(1)),
        })
    return stocks


def read_known_stock_codes():
    codes = set()
    for path in (
        ROOT / "data" / "official-updates-2026.js",
        ROOT / "data" / "ipo-history-2026.js",
        ROOT / "data" / "latest-listed-2026.js",
        HTML_FILE,
    ):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        codes.update(re.findall(r'["\']?stockCode["\']?\s*:\s*["\'](\d{5})["\']', text))
    return codes


def read_hkex_stock_ids(text):
    match = re.search(r"const\s+HKEX_STOCK_IDS\s*=\s*\{([^}]+)\}", text)
    if not match:
        return {}
    pairs = re.findall(r'"(\d{5})"\s*:\s*(\d+)', match.group(1))
    return {code: stock_id for code, stock_id in pairs}


def string_field(body, key):
    match = re.search(rf'{key}:"([^"]*)"', body)
    return match.group(1) if match else ""


def hkex_search_url(code, stock_id=None):
    if stock_id:
        return f"https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&lang=ZH&market=SEHK&stockId={stock_id}"
    return f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&stockCode={urllib.parse.quote(code)}"


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return subprocess.check_output(
            ["curl", "-L", "-s", "-A", "Mozilla/5.0", url],
            text=True,
            timeout=30,
        )


def chief_subscription_url(code):
    symbol = str(int(str(code).strip())) if str(code).strip().isdigit() else str(code).strip()
    return f"https://www.chiefgroup.com.hk/cn/securities/hk-ipo-detail?symbol={symbol}"


def extract_chief_subscription_multiple(html):
    if not html:
        return None
    label_match = re.search(r"认购倍数|認購倍數", html)
    if not label_match:
        return None
    section = html[label_match.end(): label_match.end() + 500]
    match = re.search(r"([\d,]+(?:\.\d+)?)", strip_html(section))
    if not match:
        return None
    value = parse_float(match.group(1))
    return value if value > 0 else None


def fetch_chief_subscription_estimate(code, captured_at=None):
    url = chief_subscription_url(code)
    value = extract_chief_subscription_multiple(fetch_text(url))
    return {
        "multiple": value,
        "source": ESTIMATED_SUBSCRIPTION_SOURCE,
        "sourceUrl": url,
        "capturedAt": captured_at or datetime.now().isoformat(timespec="seconds"),
    }


def positive_number(value):
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def sanitize_json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_value(item) for item in value]
    return value


def json_response_bytes(body):
    return json.dumps(sanitize_json_value(body), ensure_ascii=False, allow_nan=False).encode("utf-8")


def merge_estimated_subscription_multiple(stock, estimate):
    merged = dict(stock or {})
    if positive_number(merged.get("publicOfferMultiple")):
        return merged

    value = positive_number((estimate or {}).get("multiple"))
    if value is not None:
        merged.update({
            "estimatedSubscriptionMultiple": value,
            "estimatedSubscriptionSource": (estimate or {}).get("source") or ESTIMATED_SUBSCRIPTION_SOURCE,
            "estimatedSubscriptionSourceUrl": (estimate or {}).get("sourceUrl"),
            "estimatedSubscriptionCapturedAt": (estimate or {}).get("capturedAt") or datetime.now().isoformat(timespec="seconds"),
            "estimatedSubscriptionStatus": "estimated",
        })
        return merged

    if positive_number(merged.get("estimatedSubscriptionMultiple")):
        merged["estimatedSubscriptionStatus"] = "frozen_last_valid"
        if (estimate or {}).get("capturedAt"):
            merged["estimatedSubscriptionLastCheckedAt"] = estimate["capturedAt"]
    return merged


def records_equal(left, right):
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(right, ensure_ascii=False, sort_keys=True)


def merge_missing_stock_fields(primary, fallback):
    merged = dict(primary or {})
    for key, value in (fallback or {}).items():
        if key == "code":
            key = "stockCode"
        current = merged.get(key)
        if (current is None or current == "" or current == []) and value not in (None, ""):
            merged[key] = value
    return merged


def refresh_estimated_subscription_multiples(candidates=None):
    payload = read_official_updates()
    official_stocks = payload.get("stocks", [])
    by_code = {stock.get("stockCode"): stock for stock in official_stocks if stock.get("stockCode")}
    candidates = build_active_update_candidates() if candidates is None else candidates
    captured_at = datetime.now().isoformat(timespec="seconds")
    changed = False

    for candidate in candidates:
        code = str(candidate.get("code") or candidate.get("stockCode") or "").zfill(5)
        if not code.strip("0"):
            continue
        candidate_record = {
            **candidate,
            "stockCode": code,
            "name": candidate.get("name", ""),
            "englishName": candidate.get("englishName", ""),
            "status": candidate.get("status") or "current",
        }
        existing = merge_missing_stock_fields(by_code.get(code), candidate_record)
        if positive_number(existing.get("publicOfferMultiple")):
            continue
        try:
            estimate = fetch_chief_subscription_estimate(code, captured_at=captured_at)
        except Exception:
            estimate = {"multiple": None, "capturedAt": captured_at}
        merged = merge_estimated_subscription_multiple(existing, estimate)
        if not records_equal(existing, merged):
            by_code[code] = merged
            changed = True

    if not changed:
        return payload
    return write_official_update_records(list(by_code.values()))


def normalize_stock_codes(codes):
    result = []
    seen = set()
    for code in codes or []:
        normalized = re.sub(r"\D", "", str(code or "")).zfill(5)
        if not normalized.strip("0") or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def build_live_subscription_multiples_response(codes):
    payload = read_official_updates()
    by_code = {
        stock.get("stockCode"): stock
        for stock in payload.get("stocks", [])
        if stock.get("stockCode")
    }
    requested_codes = normalize_stock_codes(codes)
    captured_at = datetime.now().isoformat(timespec="seconds")
    changed = False
    response_stocks = []

    for code in requested_codes:
        existing = by_code.get(code) or {"stockCode": code, "status": "current"}
        if positive_number(existing.get("publicOfferMultiple")):
            response_stocks.append(existing)
            continue
        try:
            estimate = fetch_chief_subscription_estimate(code, captured_at=captured_at)
        except Exception:
            estimate = {"multiple": None, "capturedAt": captured_at}
        merged = merge_estimated_subscription_multiple(existing, estimate)
        if not records_equal(existing, merged):
            by_code[code] = merged
            changed = True
        response_stocks.append(merged)

    official_updates = write_official_update_records(list(by_code.values())) if changed else payload
    return {
        "apiVersion": OFFICIAL_UPDATE_API_VERSION,
        "capturedAt": captured_at,
        "stocks": response_stocks,
        "officialUpdates": official_updates,
    }


def post_title_search(stock_id=None, t1code="10000", t2gcode="5", t2code="15100", days=365):
    today = date.today()
    start = today - timedelta(days=days)
    form = urllib.parse.urlencode({
        "lang": "ZH",
        "category": "0",
        "market": "SEHK",
        "searchType": "1",
        "documentType": "",
        "t1code": str(t1code),
        "t2Gcode": str(t2gcode),
        "t2code": str(t2code),
        "stockId": str(stock_id or ""),
        "from": start.strftime("%Y%m%d"),
        "to": today.strftime("%Y%m%d"),
    }).encode("utf-8")
    request = urllib.request.Request(
        HKEX_TITLE_SEARCH_URL,
        data=form,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return subprocess.check_output(
            [
                "curl", "-L", "-s", "-A", "Mozilla/5.0",
                "-X", "POST", HKEX_TITLE_SEARCH_URL,
                "-d", "lang=ZH",
                "-d", "category=0",
                "-d", "market=SEHK",
                "-d", "searchType=1",
                "-d", "documentType=",
                "-d", f"t1code={t1code}",
                "-d", f"t2Gcode={t2gcode}",
                "-d", f"t2code={t2code}",
                "-d", f"stockId={stock_id or ''}",
                "-d", f"from={start:%Y%m%d}",
                "-d", f"to={today:%Y%m%d}",
            ],
            text=True,
            timeout=30,
        )


def find_allotment_notice(code, stock_id=None):
    predefined = fetch_predefined_allotment_notices().get(str(code).zfill(5))
    if predefined:
        return {"status": "found", **predefined}
    url = hkex_search_url(code, stock_id)
    if not stock_id:
        return {"status": "manual_review", "searchUrl": url, "title": "缺少披露易 stockId，请人工打开搜索页确认。"}
    html = post_title_search(stock_id)
    candidates = []
    for href, title in re.findall(r'<a\s+href="([^"]+\.pdf[^"]*)"[^>]*>([\s\S]*?)</a>', html, flags=re.I):
        clean_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title)).strip()
        if re.search(r"配發結果|分配結果|發售價及配發結果|allotment results|basis of allocation", clean_title, re.I):
            pdf = href if href.startswith("http") else urllib.parse.urljoin("https://www1.hkexnews.hk", href)
            candidates.append({"title": clean_title, "url": pdf})
    if candidates:
        return {"status": "found", **candidates[0], "searchUrl": url}
    return {"status": "not_found", "searchUrl": url}


def parse_int(value):
    return int(str(value).replace(",", ""))


def parse_float(value):
    return float(str(value).replace(",", ""))


def first_number_after(text, label, max_chars=220):
    match = re.search(re.escape(label) + rf"[\s\S]{{0,{max_chars}}}?([\d,]+(?:\.\d+)?)", text)
    return match.group(1) if match else None


def first_number_after_any(text, labels, max_chars=220):
    for label in labels:
        value = first_number_after(text, label, max_chars)
        if value:
            return value
    return None


def parse_hk_date(text):
    match = re.search(r"開始買賣日(?:期)?\s+(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_final_public_offer_percent(text):
    patterns = [
        r"香港公開發售的發售股份數量佔全球發售的最\s*終數量百分比\s*([\d.]+)%",
        r"香港公開發售[\s\S]{0,220}?最終數量百分比[\s\S]{0,80}?([\d.]+)%",
        r"香港公開發售項下發售\s*股份的最終數目調整為[\d,]+股[\s\S]{0,80}?約\s*([\d.]+)%",
        r"香港公開發售項下的最終\s*發售股份數目調整為[\d,]+股[\s\S]{0,80}?約\s*([\d.]+)%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return parse_float(match.group(1))
    return None


def clean_pdf_text(text):
    return re.sub(r"\s+", " ", text.replace("獲配\n發", "獲配發").replace("獲配 發", "獲配發")).strip()


def strip_html(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).replace("&nbsp;", " ").strip()


def parse_new_listing_rows(html):
    rows = []
    table_match = re.search(r"<tbody>([\s\S]*?)</tbody>", html, re.I)
    if not table_match:
        return rows
    for row_html in re.findall(r"<tr>([\s\S]*?)</tr>", table_match.group(1), re.I):
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html, re.I)
        if len(cells) < 5:
            continue
        code_match = re.search(r"\d{4,5}", strip_html(cells[0]))
        if not code_match:
            continue
        links = []
        for cell in cells[2:5]:
            match = re.search(r'href="([^"]+\.pdf[^"]*)"', cell, re.I)
            links.append(match.group(1) if match else None)
        rows.append({
            "code": code_match.group(0).zfill(5),
            "name": strip_html(cells[1]),
            "announcement": links[0],
            "prospectus": links[1],
            "allotment": links[2],
        })
    return rows


def parse_title_search_entries(html):
    entries = []
    for row_html in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html, re.I):
        if ".pdf" not in row_html.lower():
            continue
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html, re.I)
        row_text = strip_html(row_html)
        code_source = strip_html(cells[1]) if len(cells) >= 2 else row_text
        code_match = re.search(r"\b(\d{4,5})\b", code_source)
        if not code_match:
            continue
        doc_cell = cells[3] if len(cells) >= 4 else row_html
        name = clean_title_search_stock_name(strip_html(cells[2]) if len(cells) >= 3 else "")
        doc_text = strip_html(doc_cell)
        for href, link_text in re.findall(r'<a\s+href="([^"]+\.pdf[^"]*)"[^>]*>([\s\S]*?)</a>', doc_cell, flags=re.I):
            pdf = href if href.startswith("http") else urllib.parse.urljoin("https://www1.hkexnews.hk", href)
            entries.append({
                "code": code_match.group(1).zfill(5),
                "name": name,
                "title": doc_text or strip_html(link_text),
                "url": pdf,
            })
    return entries


def clean_title_search_stock_name(value):
    return re.sub(r"^股份簡稱\s*:\s*", "", value or "").strip()


def parse_predefined_allotment_entries(html):
    entries = {}
    for row_html in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html, re.I):
        if ".pdf" not in row_html.lower():
            continue
        row_text = strip_html(row_html)
        if not re.search(r"配發結果|分配結果|配发结果|allotment results|basis of allocation", row_text, re.I):
            continue
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html, re.I)
        code_source = strip_html(cells[1]) if len(cells) >= 2 else row_text
        code_match = re.search(r"\b(\d{4,5})\b", code_source)
        if not code_match:
            continue
        doc_cell = cells[3] if len(cells) >= 4 else row_html
        link_match = re.search(r'<a\s+href="([^"]+\.pdf[^"]*)"[^>]*>([\s\S]*?)</a>', doc_cell, flags=re.I)
        if not link_match:
            continue
        href, link_text = link_match.groups()
        pdf = href if href.startswith("http") else urllib.parse.urljoin("https://www1.hkexnews.hk", href)
        code = code_match.group(1).zfill(5)
        entries[code] = {
            "code": code,
            "name": clean_title_search_stock_name(strip_html(cells[2]) if len(cells) >= 3 else ""),
            "title": row_text or strip_html(link_text),
            "url": pdf,
            "searchUrl": HKEX_PREDEFINED_ALLOTMENT_URL,
        }
    return entries


def fetch_predefined_allotment_notices():
    return parse_predefined_allotment_entries(fetch_text(HKEX_PREDEFINED_ALLOTMENT_URL))


def is_global_offering_entry(entry):
    title = entry.get("title", "")
    return "全球發售" in title or "全球发售" in title or re.search(r"\bglobal offering\b", title, re.I)


def title_search_entries_to_prelisting_rows(entries):
    rows_by_code = {}
    for entry in entries:
        if not is_global_offering_entry(entry):
            continue
        title = entry.get("title", "")
        row = rows_by_code.setdefault(entry["code"], {
            "code": entry["code"],
            "name": entry.get("name", ""),
            "announcement": None,
            "prospectus": None,
            "allotment": None,
        })
        if entry.get("name") and not row.get("name"):
            row["name"] = entry["name"]
        if "正式通告" in title:
            row["announcement"] = entry["url"]
        if "發售以供認購" in title or "发售以供认购" in title or "Offer for Subscription" in title:
            row["prospectus"] = entry["url"]
    return sorted(rows_by_code.values(), key=lambda row: row["code"])


def prelisting_rows_to_refresh(rows, known_codes, current_updates):
    selected = []
    for row in rows:
        code = row["code"]
        existing = current_updates.get(code)
        should_refresh = needs_prelisting_refresh(row, existing) if existing else code not in known_codes
        if (
            not row.get("allotment")
            and prelisting_source_url(row)
            and should_refresh
        ):
            selected.append(row)
    return selected


def merge_new_listing_rows(*row_groups):
    merged = {}
    for rows in row_groups:
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            current = merged.setdefault(code, {"code": code, "name": "", "announcement": None, "prospectus": None, "allotment": None})
            for key in ("name", "announcement", "prospectus", "allotment"):
                if row.get(key):
                    current[key] = row[key]
    return sorted(merged.values(), key=lambda row: row["code"])


def fetch_recent_prelisting_rows_from_title_search():
    entries = []
    for t1code, t2gcode, t2code in (("10000", "5", "15200"), ("30000", "-1", "30700")):
        html = post_title_search(None, t1code=t1code, t2gcode=t2gcode, t2code=t2code, days=31)
        entries.extend(parse_title_search_entries(html))
    return title_search_entries_to_prelisting_rows(entries)


def parse_zh_date_time(text, label):
    match = re.search(
        re.escape(label) + r"[\s\S]{0,180}?(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[\s\S]{0,80}?(上午|中午|下午)?\s*([一二三四五六七八九十零〇\d]+)\s*時\s*([一二三四五六七八九十零〇\d]+)?分?",
        text,
    )
    if not match:
        return None
    year, month, day, period, hour_text, minute_text = match.groups()
    hour = zh_time_number(hour_text)
    minute = zh_time_number(minute_text) if minute_text else 0
    if period == "下午" and hour < 12:
        hour += 12
    if period == "中午":
        hour = 12
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {hour:02d}:{minute:02d}"


def parse_first_zh_date_time(text, labels):
    for label in labels:
        parsed = parse_zh_date_time(text, label)
        if parsed:
            return parsed
    return None


def zh_time_number(value):
    if value is None:
        return 0
    value = str(value).strip()
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits.get(value[1:], 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 0) * 10 + (digits.get(right, 0) if right else 0)
    return digits.get(value, 0)


def parse_hk_date_time_date(value):
    match = re.search(r"^(\d{4}-\d{2}-\d{2})", value or "")
    return match.group(1) if match else None


def parse_prelisting_application_summary(text):
    min_match = re.search(r"最少\s*([\d,]+)\s*股香港發售股", text)
    anchor_labels = [
        "閣下應透過",
        "須至少申請認購",
        "須申請認購至少",
        "可申請認購的香港發售股份數目",
        "可申請的香港發售股份數目",
        "所申請",
        "申請認購的",
    ]
    starts = [index for index in (text.find(label) for label in anchor_labels) if index >= 0]
    start = min(starts) if starts else 0
    ends = [
        index
        for index in (
            text.find("附註", start),
            text.find("預期時間表", start),
            text.find("禁止重複申請", start),
        )
        if index > start
    ]
    end = min(ends) if ends else start + 10000
    segment = text[start:end]
    raw_pairs = [
        (parse_int(shares), parse_float(amount))
        for shares, amount in re.findall(r"([\d,]+)(?:\s*\(\d+\))?\s+([\d,]+\.\d{2})", segment)
    ]
    amount_by_shares = {}
    for shares, amount in raw_pairs:
        amount_by_shares[shares] = amount
    pairs = sorted(amount_by_shares.items())
    if not pairs:
        return None
    min_shares = parse_int(min_match.group(1)) if min_match else pairs[0][0]
    max_shares, max_amount = max(pairs, key=lambda item: item[0])
    min_amount = amount_by_shares.get(min_shares, pairs[0][1])
    min_lots = 1
    max_lots = max_shares // min_shares if min_shares else None
    application_tiers = [
        {
            "shares": shares,
            "lots": shares // min_shares if min_shares else None,
            "amountHKD": amount,
        }
        for shares, amount in pairs
    ]
    a_candidates = [(shares, amount) for shares, amount in pairs if amount / 1.010085 <= 5000000]
    b_candidates = [(shares, amount) for shares, amount in pairs if amount / 1.010085 > 5000000]
    a_max_shares, a_max_amount = max(a_candidates, key=lambda item: item[0]) if a_candidates else (None, None)
    b_min_shares, b_min_amount = min(b_candidates, key=lambda item: item[0]) if b_candidates else (None, None)
    return {
        "minShares": min_shares,
        "minLots": min_lots,
        "minAmountHKD": min_amount,
        "aMaxShares": a_max_shares,
        "aMaxLots": a_max_shares // min_shares if min_shares and a_max_shares else None,
        "aMaxAmountHKD": a_max_amount,
        "bMinShares": b_min_shares,
        "bMinLots": b_min_shares // min_shares if min_shares and b_min_shares else None,
        "bMinAmountHKD": b_min_amount,
        "maxShares": max_shares,
        "maxLots": max_lots,
        "maxAmountHKD": max_amount,
        "publicOfferSharesBefore": max_shares * 2 if max_shares else None,
        "applicationTiers": application_tiers,
    }


PRELISTING_TYPE_OVERRIDES = {
    "01511": ("18C", "18C 特专科技"),
}

PRELISTING_FIELD_OVERRIDES = {
    "01392": {
        "subscriptionStart": "2026-06-11 09:00",
        "subscriptionEnd": "2026-06-16 12:00",
        "listDate": "2026-06-22",
        "offerPrice": 7.20,
    },
    "06675": {
        "subscriptionStart": "2026-06-09 09:00",
        "subscriptionEnd": "2026-06-12 12:00",
        "listDate": "2026-06-17",
        "offerPrice": 18.36,
    },
}


def infer_prelisting_type(name, code=None):
    if code in PRELISTING_TYPE_OVERRIDES:
        return PRELISTING_TYPE_OVERRIDES[code]
    if "- P" in name or " -P" in name:
        return "18C", "18C 特专科技-P"
    if "- B" in name or " -B" in name:
        return "主板B", "18A 生物科技-B"
    if "- W" in name or " -W" in name:
        return "主板B", "WVR-W"
    return "主板B", "H股"


def extract_prelisting_record(row, text_path, text):
    summary = parse_prelisting_application_summary(text) or {}
    subscription_start = parse_zh_date_time(text, "香港公開發售開始")
    subscription_end = parse_first_zh_date_time(text, [
        "截止辦理香港公開發售申請登記",
        "截止辦理申請登記",
    ])
    listing_start = parse_first_zh_date_time(text, [
        "H股開始在聯交所買賣",
        "預期H股開始於聯交所買賣",
        "預期H股開始於香港聯交所買賣",
        "預期H股股份開始於聯交所買賣",
        "預期H股於聯交所開始買賣",
    ])
    offer_price = (
        first_number_after(text, "發售價將為每股發售股份", 80)
        or first_number_after(text, "最高發售價", 80)
        or first_number_after(text, "發售價", 80)
    )
    total_offer_shares = (
        first_number_after(text, "全球發售項下的發售股份數目", 120)
        or first_number_after(text, "全球發售的發售股份數目", 120)
    )
    mechanism, listing_type = infer_prelisting_type(row["name"], row["code"])
    fallback_offer_price = None
    if summary.get("minAmountHKD") and summary.get("minShares"):
        fallback_offer_price = round(summary["minAmountHKD"] / summary["minShares"] / 1.010085, 2)
    overrides = PRELISTING_FIELD_OVERRIDES.get(row["code"], {})
    record = {
        "stockCode": row["code"],
        "name": row["name"],
        "englishName": "",
        "status": "current",
        "subscriptionStart": subscription_start or overrides.get("subscriptionStart"),
        "subscriptionEnd": subscription_end or overrides.get("subscriptionEnd"),
        "listDate": parse_hk_date_time_date(listing_start) or overrides.get("listDate") or "",
        "offerPrice": parse_float(offer_price) if offer_price else overrides.get("offerPrice") or fallback_offer_price,
        "sharesPerLot": summary.get("minShares"),
        "publicOfferSharesBefore": summary.get("publicOfferSharesBefore"),
        "publicOfferSharesFinal": None,
        "totalOfferShares": parse_int(total_offer_shares) if total_offer_shares else None,
        "mechanism": mechanism,
        "listingType": listing_type,
        "publicOfferMultiple": None,
        "totalApplications": None,
        "applicationSummary": {key: value for key, value in summary.items() if key not in ("publicOfferSharesBefore", "applicationTiers")},
        "applicationTiers": summary.get("applicationTiers"),
        "source": {
            "pdf": row.get("announcement") or row.get("prospectus") or "",
            "prospectus": row.get("prospectus") or "",
            "extractedText": text_path,
            "title": "官方新上市公告 PDF",
            "parserVersion": PRELISTING_PARSE_VERSION,
        },
        "basisOfAllocation": [],
    }
    return {key: value for key, value in record.items() if value is not None}


def prelisting_source_url(row):
    return row.get("prospectus") or row.get("announcement")


def normalized_basis_lines(segment):
    lines = []
    for line in segment.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean:
            continue
        lines.append(clean)
    return lines


def is_integer_line(value):
    return bool(re.fullmatch(r"\d[\d,]*", value or ""))


def is_percent_line(value):
    return bool(re.fullmatch(r"\d+(?:\.\d+)?%", value or ""))


def is_next_entry_start(lines, index):
    return index + 1 < len(lines) and is_integer_line(lines[index]) and is_integer_line(lines[index + 1])


def vertical_basis_entries(segment):
    lines = normalized_basis_lines(segment)
    entries = []
    i = 0
    while i < len(lines):
        shares = None
        valid = None
        initial_basis = ""
        if is_next_entry_start(lines, i):
            shares = parse_int(lines[i])
            valid = parse_int(lines[i + 1])
            i += 2
        elif is_integer_line(lines[i]) and i + 1 < len(lines):
            combined_match = re.match(r"^(\d[\d,]*)\s+(.+)$", lines[i + 1])
            if combined_match:
                shares = parse_int(lines[i])
                valid = parse_int(combined_match.group(1))
                initial_basis = combined_match.group(2).strip()
                i += 2
            else:
                i += 1
                continue
        else:
            i += 1
            continue
        basis_lines = [initial_basis] if initial_basis else []
        percent = None
        while i < len(lines):
            line = lines[i]
            if is_percent_line(line):
                percent = parse_float(line.rstrip("%"))
                i += 1
                break
            if is_next_entry_start(lines, i):
                break
            if line.startswith("總計") or line.startswith("截至本公告日期"):
                break
            basis_lines.append(line)
            i += 1
        basis = re.sub(r"\s+", "", "".join(basis_lines))
        if basis:
            entries.append({
                "sharesApplied": shares,
                "validApplications": valid,
                "basis": basis,
                "approxPercent": percent,
            })
    return entries


def parse_basis_entry_allocation(entry):
    basis = entry["basis"]
    valid = entry["validApplications"]
    zero_match = re.fullmatch(r"0股H?股(?:股份)?", basis)
    if zero_match:
        return {
            "successfulApplications": 0,
            "baseAllottedShares": 0,
            "baseSuccessfulApplications": 0,
            "extraLotteryShares": None,
            "extraLotteryWinners": None,
            "sharesAllotted": 0,
            "guaranteedShares": 0,
        }

    guaranteed_extra = re.search(
        r"([\d,]+)\s*股(?:H?股)?(?:股份)?[，,]?(?:另加|加上)([\d,]+)\s*名(?:申請人|申請者)?(?:當中|中|中的)?(?:有)?([\d,]+)\s*名獲(?:分配|配發|發|得)額外([\d,]+)\s*股(?:H?股)?(?:股份)?",
        basis,
    )
    if guaranteed_extra:
        base, listed_valid, winners, extra = guaranteed_extra.groups()
        base_shares = parse_int(base)
        extra_shares = parse_int(extra)
        winner_count = parse_int(winners)
        return {
            "successfulApplications": valid,
            "baseAllottedShares": base_shares,
            "baseSuccessfulApplications": valid,
            "extraLotteryShares": extra_shares,
            "extraLotteryWinners": winner_count,
            "sharesAllotted": valid * base_shares + winner_count * extra_shares,
            "guaranteedShares": base_shares,
        }

    lottery = re.search(
        r"([\d,]+)\s*名(?:申請人|申請者)?(?:當中|中|中的)?(?:有)?([\d,]+)\s*名(?:將)?獲(?:分配|配發|發|得)([\d,]+)\s*股(?:H?股)?(?:股份)?",
        basis,
    )
    if lottery:
        listed_valid, winners, allotted = lottery.groups()
        winner_count = parse_int(winners)
        allotted_shares = parse_int(allotted)
        return {
            "successfulApplications": winner_count,
            "baseAllottedShares": allotted_shares,
            "baseSuccessfulApplications": winner_count,
            "extraLotteryShares": None,
            "extraLotteryWinners": None,
            "sharesAllotted": winner_count * allotted_shares,
            "guaranteedShares": 0,
        }

    guaranteed = re.fullmatch(r"([\d,]+)\s*股(?:H?股)?(?:股份)?", basis)
    if guaranteed:
        allotted_shares = parse_int(guaranteed.group(1))
        return {
            "successfulApplications": valid,
            "baseAllottedShares": allotted_shares,
            "baseSuccessfulApplications": valid,
            "extraLotteryShares": None,
            "extraLotteryWinners": None,
            "sharesAllotted": valid * allotted_shares,
            "guaranteedShares": allotted_shares,
        }

    return None


def group_for_shares(shares, explicit_group, base_stock):
    if explicit_group:
        return explicit_group
    summary = (base_stock or {}).get("applicationSummary") or {}
    b_min = positive_number(summary.get("bMinShares"))
    if b_min and shares >= b_min:
        return "B"
    return "A"


def combine_vertical_basis_entries(entries, explicit_group=None, base_stock=None):
    rows = []
    pending = None
    for entry in entries:
        allocation = parse_basis_entry_allocation(entry)
        if not allocation:
            continue
        shares = entry["sharesApplied"]
        if not pending or pending["sharesApplied"] != shares:
            if pending:
                rows.append(pending)
            pending = {
                "group": group_for_shares(shares, explicit_group, base_stock),
                "sharesApplied": shares,
                "validApplications": 0,
                "baseAllottedShares": 0,
                "baseSuccessfulApplications": 0,
                "extraLotteryShares": None,
                "extraLotteryWinners": None,
                "successfulApplications": 0,
                "sharesAllotted": 0,
                "guaranteedShares": 0,
                "approxPercent": entry.get("approxPercent"),
                "rawBasis": "",
            }
        pending["validApplications"] += entry["validApplications"]
        pending["successfulApplications"] += allocation["successfulApplications"]
        pending["baseSuccessfulApplications"] += allocation["baseSuccessfulApplications"]
        pending["sharesAllotted"] = max(pending["sharesAllotted"], allocation["baseAllottedShares"])
        pending["baseAllottedShares"] = max(pending["baseAllottedShares"], allocation["baseAllottedShares"])
        pending["guaranteedShares"] = max(pending["guaranteedShares"], allocation["guaranteedShares"])
        if allocation["extraLotteryShares"]:
            pending["extraLotteryShares"] = allocation["extraLotteryShares"]
            pending["extraLotteryWinners"] = (pending["extraLotteryWinners"] or 0) + (allocation["extraLotteryWinners"] or 0)
        if pending["approxPercent"] is None and entry.get("approxPercent") is not None:
            pending["approxPercent"] = entry["approxPercent"]
        pending["rawBasis"] = "；".join(part for part in (pending["rawBasis"], entry["basis"]) if part)
    if pending:
        rows.append(pending)
    for row in rows:
        if row["approxPercent"] is None and row["sharesApplied"] and row["validApplications"]:
            row["approxPercent"] = round(row["sharesAllotted"] / (row["sharesApplied"] * row["validApplications"]) * 100, 2)
    return rows


def parse_vertical_basis_rows(text, base_stock=None):
    start = text.find("香港公開發售的分配基準")
    if start < 0:
        return []
    end_candidates = [
        index for index in (
            text.find("截至本公告日期", start),
            text.find("遵守上市規則", start),
            text.find("其他╱額外資料", start),
        ) if index > start
    ]
    end = min(end_candidates) if end_candidates else len(text)
    segment = text[start:end]
    a_index = segment.find("甲組")
    b_index = segment.find("乙組")
    if a_index >= 0 and b_index > a_index:
        return (
            combine_vertical_basis_entries(vertical_basis_entries(segment[a_index:b_index]), "A", base_stock)
            + combine_vertical_basis_entries(vertical_basis_entries(segment[b_index:]), "B", base_stock)
        )
    return combine_vertical_basis_entries(vertical_basis_entries(segment), None, base_stock)


def parse_basis_rows(text, base_stock=None):
    compact = clean_pdf_text(text)
    a_start = compact.find("甲組")
    b_start = compact.find("乙組", a_start + 1)
    table_end = compact.find("截至本公告日期", b_start + 1)
    if table_end < 0:
        table_end = compact.find("附加資料", b_start + 1)
    if table_end < 0:
        table_end = len(compact)
    if a_start < 0 or b_start < 0 or table_end < 0:
        return parse_vertical_basis_rows(text, base_stock)

    rows = []
    for group, start, end in (("A", a_start, b_start), ("B", b_start, table_end)):
        segment = compact[start:end]
        matches = []
        simple_pattern = re.compile(
            r"([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*名(?:申請人|申請者)?(?:當中|中|中的)?(?:有)?\s*([\d,]+)\s*名(?:將)?獲(?:配發|分配|發|得)\s*([\d,]+)\s*股(?:H\s*股)?(?:股份)?\s+([\d.]+)%"
        )
        extra_pattern = re.compile(
            r"([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*股(?:H\s*股)?(?:股份)?[，,]?\s*(?:加上|另加)\s*([\d,]+)\s*名(?:申請人|申請者)?(?:當中|中|中的)?(?:有)?\s*([\d,]+)\s*名(?:將)?獲(?:配發|分配|發|得)\s*額外\s*([\d,]+)\s*股(?:H\s*股)?(?:股份)?\s+([\d.]+)%"
        )
        guaranteed_pattern = re.compile(
            r"([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*股(?:H\s*股)?(?:股份)?\s+([\d.]+)%"
        )
        for match in simple_pattern.finditer(segment):
            matches.append(("simple", match.start(), match))
        for match in extra_pattern.finditer(segment):
            matches.append(("extra", match.start(), match))
        for match in guaranteed_pattern.finditer(segment):
            matches.append(("guaranteed", match.start(), match))

        for kind, _, match in sorted(matches, key=lambda item: item[1]):
            if kind == "simple":
                shares, valid, listed_valid, winners, allotted, pct = match.groups()
                rows.append({
                    "group": group,
                    "sharesApplied": parse_int(shares),
                    "validApplications": parse_int(valid),
                    "baseAllottedShares": parse_int(allotted),
                    "baseSuccessfulApplications": parse_int(winners),
                    "extraLotteryShares": None,
                    "extraLotteryWinners": None,
                    "successfulApplications": parse_int(winners),
                    "sharesAllotted": parse_int(allotted),
                    "guaranteedShares": 0,
                    "approxPercent": parse_float(pct),
                    "rawBasis": f"{listed_valid}名申請人中{winners}名獲配發{allotted}股H股股份",
                })
            elif kind == "extra":
                shares, valid, base, listed_valid, winners, extra, pct = match.groups()
                rows.append({
                    "group": group,
                    "sharesApplied": parse_int(shares),
                    "validApplications": parse_int(valid),
                    "baseAllottedShares": parse_int(base),
                    "baseSuccessfulApplications": parse_int(valid),
                    "extraLotteryShares": parse_int(extra),
                    "extraLotteryWinners": parse_int(winners),
                    "successfulApplications": parse_int(valid),
                    "sharesAllotted": None,
                    "guaranteedShares": parse_int(base),
                    "approxPercent": parse_float(pct),
                    "rawBasis": f"{base}股H股股份加上{listed_valid}名申請人中{winners}名獲配發額外{extra}股H股股份",
                })
            else:
                shares, valid, allotted, pct = match.groups()
                rows.append({
                    "group": group,
                    "sharesApplied": parse_int(shares),
                    "validApplications": parse_int(valid),
                    "baseAllottedShares": parse_int(allotted),
                    "baseSuccessfulApplications": parse_int(valid),
                    "extraLotteryShares": None,
                    "extraLotteryWinners": None,
                    "successfulApplications": parse_int(valid),
                    "sharesAllotted": parse_int(allotted),
                    "guaranteedShares": parse_int(allotted),
                    "approxPercent": parse_float(pct),
                    "rawBasis": f"{allotted}股H股股份",
                })
    vertical_rows = parse_vertical_basis_rows(text, base_stock)
    return vertical_rows if len(vertical_rows) > len(rows) else rows


def parse_group_totals(text):
    totals = {}
    for group_name, key in (("甲", "A"), ("乙", "B")):
        match = re.search(rf"總計\s+([\d,]+)\s+{group_name}組獲接納申請人總數[:：]\s*([\d,]+)", text)
        if match:
            totals[key] = {
                "totalApplications": parse_int(match.group(1)),
                "successfulApplications": parse_int(match.group(2)),
            }
    return totals


def extract_minimal_allotment_record(base_stock, pdf_url, text_path, text):
    code = base_stock["code"]
    offer_price = first_number_after(text, "發售價", 80)
    total_offer_shares = first_number_after(text, "發售股份數目", 80)
    issued_shares = first_number_after(text, "於上市時已發行的股份數目", 100)
    public_before = first_number_after_any(text, [
        "香港公開發售初步可供認購的發售股份數量",
        "香港公開發售項下初步可供認購發售股份數目",
    ])
    public_reallocated = first_number_after_any(text, [
        "自國際發售重新分配的發售股份數量",
        "由國際發售重新分配的發售股份數目",
    ])
    public_final = first_number_after_any(text, [
        "香港公開發售最終發售股份數量",
        "香港公開發售項下最終發售股份數目",
        "香港公開發售項下的最終發售股份數目調整為",
    ])
    final_percent = parse_final_public_offer_percent(text)
    public_offer_multiple = first_number_after_any(text, ["認購水平", "認購額"], 80)

    offer_price_value = parse_float(offer_price) if offer_price else positive_number(base_stock.get("offerPrice"))
    issued_shares_value = parse_int(issued_shares) if issued_shares else None
    basis_rows = parse_basis_rows(text, base_stock)
    shares_per_lot = min((row["sharesApplied"] for row in basis_rows if row["group"] == "A"), default=None) or base_stock.get("sharesPerLot")

    successful_applications = parse_int(first_number_after_any(text, [
        "受理申請數目",
        "獲接納申請數目",
        "成功申請數目",
        "獲分配股份的申請人數目",
    ]) or "0") or None
    group_totals = parse_group_totals(text)
    if not successful_applications:
        total_winners = sum(
            positive_number(group.get("successfulApplications")) or 0
            for group in group_totals.values()
        )
        successful_applications = total_winners or None

    record = {
        "stockCode": code,
        "name": base_stock.get("name") or "",
        "englishName": base_stock.get("englishName") or "",
        "status": "listed",
        "listDate": parse_hk_date(text) or base_stock.get("listDate") or "",
        "offerPrice": offer_price_value,
        "sharesPerLot": shares_per_lot,
        "totalOfferShares": parse_int(total_offer_shares) if total_offer_shares else None,
        "marketCap": issued_shares_value * offer_price_value if issued_shares_value and offer_price_value else None,
        "publicOfferSharesBefore": parse_int(public_before) if public_before else base_stock.get("publicOfferSharesBefore"),
        "publicOfferReallocatedShares": parse_int(public_reallocated) if public_reallocated else None,
        "publicOfferSharesFinal": parse_int(public_final) if public_final else None,
        "publicOfferMultiple": parse_float(public_offer_multiple) if public_offer_multiple else None,
        "totalApplications": parse_int(first_number_after(text, "有效申請數目", 80) or "0") or None,
        "successfulApplications": successful_applications,
        "finalPublicOfferPercent": final_percent,
        "mechanism": base_stock.get("mechanism") or "主板B",
        "listingType": base_stock.get("listingType") or "H股",
        "groupTotals": group_totals,
        "source": {
            "pdf": pdf_url,
            "extractedText": text_path,
            "title": "官方配發結果 PDF",
        },
        "applicationSummary": base_stock.get("applicationSummary"),
        "applicationTiers": base_stock.get("applicationTiers"),
        "basisOfAllocation": basis_rows,
    }
    return {key: value for key, value in record.items() if value is not None}


def fetch_binary(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            return response.read()
    except Exception:
        return subprocess.check_output(["curl", "-L", "-s", "-A", "Mozilla/5.0", url], timeout=45)


def extract_pdf_text(pdf_path):
    try:
        import fitz

        document = fitz.open(str(pdf_path))
        text = "\n".join(page.get_text("text") or "" for page in document)
        if text.strip():
            return text
    except Exception:
        pass

    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_official_updates():
    if not OFFICIAL_UPDATES_FILE.exists():
        return {"generatedAt": None, "stocks": []}
    raw = OFFICIAL_UPDATES_FILE.read_text(encoding="utf-8")
    match = re.search(r"window\.OFFICIAL_UPDATES_2026\s*=\s*(\{[\s\S]*\});?\s*$", raw)
    if not match:
        return {"generatedAt": None, "stocks": []}
    return sanitize_json_value(json.loads(match.group(1)))


def official_update_by_code():
    return {
        stock.get("stockCode"): stock
        for stock in read_official_updates().get("stocks", [])
        if stock.get("stockCode")
    }


def base_stock_from_official(stock):
    code = stock.get("stockCode", "")
    stock_ids = read_hkex_stock_ids(HTML_FILE.read_text(encoding="utf-8"))
    return {
        "code": code,
        "name": stock.get("name", ""),
        "englishName": stock.get("englishName", ""),
        "status": stock.get("status", "current"),
        "listDate": stock.get("listDate", ""),
        "mechanism": stock.get("mechanism", ""),
        "listingType": stock.get("listingType", ""),
        "offerPrice": stock.get("offerPrice"),
        "sharesPerLot": stock.get("sharesPerLot"),
        "totalOfferShares": stock.get("totalOfferShares"),
        "publicOfferSharesBefore": stock.get("publicOfferSharesBefore"),
        "applicationSummary": stock.get("applicationSummary"),
        "applicationTiers": stock.get("applicationTiers"),
        "stockId": stock_ids.get(code),
    }


def has_written_allotment(stock):
    if not stock:
        return False
    source_title = stock.get("source", {}).get("title", "")
    source_pdf = stock.get("source", {}).get("pdf", "")
    return (
        stock.get("status") == "listed"
        and (
            "配發結果" in source_title
            or "配发结果" in source_title
            or "allotment" in source_pdf.lower()
        )
    )


def allotment_record_is_complete(stock):
    if not has_written_allotment(stock):
        return False
    return bool(
        positive_number(stock.get("sharesPerLot"))
        and positive_number(stock.get("totalApplications"))
        and positive_number(stock.get("successfulApplications"))
        and stock.get("basisOfAllocation")
    )


def list_date_is_future(value):
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not match:
        return False
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day) > date.today()


def build_active_update_candidates(html_stocks=None, official_stocks=None):
    html_stocks = read_html_stocks() if html_stocks is None else html_stocks
    official_stocks = read_official_updates().get("stocks", []) if official_stocks is None else official_stocks
    by_code = {}

    for stock in html_stocks:
        if stock.get("status") == "current":
            by_code[stock["code"]] = stock

    for stock in official_stocks:
        code = stock.get("stockCode")
        if not code:
            continue
        if stock.get("status") == "current":
            by_code[code] = merge_missing_stock_fields(base_stock_from_official(stock), by_code.get(code, {}))
        elif has_written_allotment(stock) and list_date_is_future(stock.get("listDate")):
            by_code[code] = {
                **merge_missing_stock_fields(base_stock_from_official(stock), by_code.get(code, {})),
                "alreadyWrittenAllotment": True,
            }

    return sorted(by_code.values(), key=lambda item: item.get("code", ""))


def find_base_stock(code):
    code = str(code).zfill(5)
    for stock in build_active_update_candidates():
        if stock.get("code") == code:
            return stock
    for stock in read_html_stocks():
        if stock.get("code") == code:
            return stock
    official = official_update_by_code().get(code)
    if official:
        return base_stock_from_official(official)
    return None


def write_official_update_record(record):
    return write_official_update_records([record])


def write_official_update_records(records):
    payload = read_official_updates()
    existing_by_code = {stock.get("stockCode"): stock for stock in payload.get("stocks", []) if stock.get("stockCode")}
    merged_records = [
        merge_missing_stock_fields(record, existing_by_code.get(record.get("stockCode")))
        for record in records
    ]
    incoming_codes = {record["stockCode"] for record in merged_records}
    stocks = [stock for stock in payload.get("stocks", []) if stock.get("stockCode") not in incoming_codes]
    stocks.extend(merged_records)
    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "stocks": sorted(stocks, key=lambda stock: stock.get("stockCode", "")),
    }
    payload = sanitize_json_value(payload)
    OFFICIAL_UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFICIAL_UPDATES_FILE.write_text(
        f"{OFFICIAL_UPDATES_GLOBAL} = {json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)};\n",
        encoding="utf-8",
    )
    return payload


def sync_new_listing_candidates():
    html = fetch_text(HKEX_NEW_LISTING_INFO_URL)
    known_codes = read_known_stock_codes()
    current_updates = {
        stock.get("stockCode"): stock
        for stock in read_official_updates().get("stocks", [])
        if stock.get("status") == "current"
    }
    rows = merge_new_listing_rows(parse_new_listing_rows(html), fetch_recent_prelisting_rows_from_title_search())
    new_rows = prelisting_rows_to_refresh(rows, known_codes, current_updates)
    records = []
    for row in new_rows:
        source_url = prelisting_source_url(row)
        source_kind = "prospectus" if source_url == row.get("prospectus") else "announcement"
        pdf_path = ROOT / "data" / "2026" / "current_pdf" / f"{row['code']}_{source_kind}_c.pdf"
        txt_path = ROOT / "data" / "2026" / "txt" / f"{row['code']}_prospectus.txt"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(fetch_binary(source_url))
        text = extract_pdf_text(pdf_path)
        txt_path.write_text(text, encoding="utf-8")
        records.append(extract_prelisting_record(row, str(txt_path.relative_to(ROOT)), text))
    if records:
        write_official_update_records(records)
    return {
        "pageUpdated": re.search(r"更新日期:\s*([^<]+)", html).group(1).strip() if re.search(r"更新日期:\s*([^<]+)", html) else None,
        "seenRows": rows,
        "newRecords": records,
    }


def needs_prelisting_refresh(row, existing):
    if not existing:
        return False
    source = existing.get("source", {})
    if source.get("prospectus") != row.get("prospectus"):
        return True
    if source.get("pdf") != (row.get("announcement") or row.get("prospectus") or ""):
        return True
    if source.get("parserVersion") != PRELISTING_PARSE_VERSION and prelisting_record_is_incomplete(existing):
        return True
    return False


def prelisting_record_is_incomplete(stock):
    summary = stock.get("applicationSummary") or {}
    required = (
        stock.get("subscriptionStart"),
        stock.get("subscriptionEnd"),
        stock.get("listDate"),
        stock.get("offerPrice"),
        stock.get("sharesPerLot"),
        stock.get("publicOfferSharesBefore"),
        summary.get("minAmountHKD"),
    )
    return any(value in (None, "") for value in required)


def apply_official_update(code, pdf_url=None):
    stock = find_base_stock(code)
    if not stock:
        raise ValueError(f"找不到股票 {code}")
    if not pdf_url:
        notice = find_allotment_notice(code, stock.get("stockId"))
        if notice.get("status") != "found":
            raise ValueError(f"{code} 暂无可写入的配发结果公告")
        pdf_url = notice["url"]

    pdf_path = ROOT / "data" / "2026" / "pdf" / f"{code}_allotment.pdf"
    txt_path = ROOT / "data" / "2026" / "txt" / f"{code}_allotment.txt"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_path.write_bytes(fetch_binary(pdf_url))
    text = extract_pdf_text(pdf_path)
    txt_path.write_text(text, encoding="utf-8")

    rel_txt = str(txt_path.relative_to(ROOT))
    record = extract_minimal_allotment_record(stock, pdf_url, rel_txt, text)
    write_official_update_record(record)
    return {
        "message": f"{code} 已写入最小官方配发数据。",
        "stock": record,
        "pdfPath": str(pdf_path.relative_to(ROOT)),
        "txtPath": rel_txt,
    }


def build_check_official_updates_response():
    new_listing_result = {"newRecords": [], "seenRows": []}
    new_listing_error = None
    try:
        new_listing_result = sync_new_listing_candidates()
    except Exception as error:
        new_listing_error = str(error)
    new_listing_rows = {
        row.get("code"): row
        for row in new_listing_result.get("seenRows", [])
        if row.get("code")
    }
    stocks = build_active_update_candidates()
    official_updates = refresh_estimated_subscription_multiples(stocks)
    written_updates = {
        stock.get("stockCode"): stock
        for stock in official_updates.get("stocks", [])
        if stock.get("stockCode")
    }
    items = []
    for stock in stocks:
        try:
            written = written_updates.get(stock["code"])
            if has_written_allotment(written) and not allotment_record_is_complete(written):
                try:
                    applied = apply_official_update(stock["code"], written.get("source", {}).get("pdf"))
                    items.append({**stock, "status": "applied", "applied": applied, "title": "配发结果已补全解析"})
                except Exception as apply_error:
                    items.append({**stock, "status": "apply_error", "error": str(apply_error), "title": "配发结果已发现但补全解析失败"})
                continue

            if stock.get("alreadyWrittenAllotment") or has_written_allotment(written):
                items.append({
                    **stock,
                    "status": "already_written",
                    "title": "已写入配发结果，等待上市或行情更新",
                    "searchUrl": hkex_search_url(stock["code"], stock.get("stockId")),
                })
                continue

            listing_row = new_listing_rows.get(stock["code"])
            if listing_row and listing_row.get("allotment"):
                result = {
                    "status": "found",
                    "title": "股份配发结果",
                    "url": listing_row["allotment"],
                    "searchUrl": HKEX_NEW_LISTING_INFO_URL,
                }
            elif listing_row and not stock.get("stockId"):
                result = find_allotment_notice(stock["code"], stock.get("stockId"))
                if result.get("status") != "found":
                    result = {
                        "status": "not_found",
                        "title": "披露易新上市资料暂未列出股份配发结果",
                        "searchUrl": HKEX_NEW_LISTING_INFO_URL,
                    }
            else:
                result = find_allotment_notice(stock["code"], stock.get("stockId"))
            if result.get("status") == "found":
                try:
                    applied = apply_official_update(stock["code"], result.get("url"))
                    items.append({**stock, **result, "status": "applied", "applied": applied})
                except Exception as apply_error:
                    items.append({**stock, **result, "status": "apply_error", "error": str(apply_error)})
            else:
                items.append({**stock, **result})
        except Exception as error:
            items.append({
                **stock,
                "status": "error",
                "error": str(error),
                "searchUrl": hkex_search_url(stock["code"], stock.get("stockId")),
            })
    applied = [item for item in items if item["status"] == "applied"]
    apply_errors = [item for item in items if item["status"] == "apply_error"]
    errors = [item for item in items if item["status"] == "error"]
    pending = [item for item in items if item["status"] == "not_found"]
    manual = [item for item in items if item["status"] == "manual_review"]
    already_written = [item for item in items if item["status"] == "already_written"]
    if applied:
        official_updates = read_official_updates()
    return {
        "apiVersion": OFFICIAL_UPDATE_API_VERSION,
        "message": f"检查完成：{len(new_listing_result.get('newRecords', []))} 只新增招股资料，{len(applied)} 只配发结果已自动写入，{len(pending)} 只暂无配发结果，{len(already_written)} 只已写入待后续行情，{len(manual)} 只需人工确认，{len(apply_errors) + len(errors) + (1 if new_listing_error else 0)} 只检查或写入失败。",
        "items": items,
        "newListing": {
            "pageUpdated": new_listing_result.get("pageUpdated"),
            "newRecords": new_listing_result.get("newRecords", []),
            "error": new_listing_error,
        },
        "officialUpdates": official_updates,
    }


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_GET(self):
        clean_path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if clean_path in ("", "/hk-ipo"):
            self.path = "/hk-ipo.html"
        super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/apply-official-update":
            self.handle_apply_official_update()
            return
        if self.path == "/api/live-subscription-multiples":
            self.handle_live_subscription_multiples()
            return
        if self.path != "/api/check-official-updates":
            self.send_error(404)
            return
        body = build_check_official_updates_response()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_response_bytes(body))

    def handle_live_subscription_multiples(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            body = build_live_subscription_multiples_response(payload.get("codes", []))
            self.send_response(200)
        except Exception as error:
            body = {"error": str(error)}
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_response_bytes(body))

    def handle_apply_official_update(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            code = str(payload.get("code", "")).zfill(5)
            pdf_url = payload.get("url") or None
            if not code.strip("0"):
                raise ValueError("缺少股票代码")
            body = apply_official_update(code, pdf_url)
            self.send_response(200)
        except Exception as error:
            body = {"error": str(error)}
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_response_bytes(body))


def server_host():
    return os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"


def lan_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        candidates = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        candidates = []
    for candidate in candidates:
        ip = candidate[4][0]
        if ip.startswith("127.") or ip in addresses:
            continue
        addresses.append(ip)
    return addresses


def serving_urls(host, port, lan_ips=None):
    urls = [f"http://127.0.0.1:{port}/hk-ipo"]
    if host == "0.0.0.0":
        for ip in lan_ips if lan_ips is not None else lan_ipv4_addresses():
            urls.append(f"http://{ip}:{port}/hk-ipo")
    return urls


def main():
    os.chdir(ROOT)
    port = int(os.environ.get("PORT", "8766"))
    host = server_host()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving on {host}:{port}")
    for url in serving_urls(host, port):
        print(f"Open: {url}")
    if host == "127.0.0.1":
        print("Phone access is disabled. Use HOST=0.0.0.0 python3 app.py for LAN preview.")
    server.serve_forever()


if __name__ == "__main__":
    main()
