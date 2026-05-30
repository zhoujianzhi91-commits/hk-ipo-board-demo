#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def test_predefined_allotment_page_entries_are_parsed():
    html = """
    <tr>
      <td>28/05/2026 22:42</td>
      <td>3388</td>
      <td>股份簡稱: 創想三維</td>
      <td>
        公告及通告 - [配發結果]<br>
        <a href="/listedco/listconews/sehk/2026/0528/2026052802544_c.pdf">分配結果公告</a>
      </td>
    </tr>
    """

    entries = app.parse_predefined_allotment_entries(html)

    assert_equal(entries["03388"]["code"], "03388", "predefined allotment parser should normalize stock code")
    assert_equal(entries["03388"]["name"], "創想三維", "predefined allotment parser should keep stock name")
    assert_equal(
        entries["03388"]["url"],
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0528/2026052802544_c.pdf",
        "predefined allotment parser should absolutize PDF URL",
    )


def test_find_allotment_notice_uses_predefined_page_before_title_search():
    originals = {
        "fetch_predefined_allotment_notices": app.fetch_predefined_allotment_notices,
        "post_title_search": app.post_title_search,
    }
    try:
        app.fetch_predefined_allotment_notices = lambda: {
            "03388": {
                "code": "03388",
                "name": "創想三維",
                "title": "公告及通告 - [配發結果] 分配結果公告",
                "url": "https://example.test/03388_allotment.pdf",
                "searchUrl": app.HKEX_PREDEFINED_ALLOTMENT_URL,
            }
        }
        app.post_title_search = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("title search should not be needed"))

        notice = app.find_allotment_notice("03388", None)

        assert_equal(notice["status"], "found", "predefined allotment notice should be enough without stockId")
        assert_equal(notice["url"], "https://example.test/03388_allotment.pdf", "predefined allotment URL should be returned")
    finally:
        for name, value in originals.items():
            setattr(app, name, value)


def test_minimal_allotment_record_preserves_prelisting_terms_when_basis_parse_fails():
    base_stock = {
        "code": "03388",
        "name": "創想三維",
        "status": "current",
        "listDate": "2026-05-29",
        "sharesPerLot": 150,
        "publicOfferSharesBefore": 4895200,
        "applicationSummary": {"minAmountHKD": 2848.44},
        "applicationTiers": [{"shares": 150, "lots": 1, "amountHKD": 2848.44}],
    }
    text = """
    發售價 18.80 港元
    香港公開發售最終發售股份數量 7,342,800
    香港公開發售認購水平 3,829.42
    有效申請數目 251,375
    """

    record = app.extract_minimal_allotment_record(base_stock, "https://example.test/03388.pdf", "data/2026/txt/03388_allotment.txt", text)

    assert_equal(record["sharesPerLot"], 150, "allotment record should preserve sharesPerLot from prelisting data")
    assert_equal(record["publicOfferSharesBefore"], 4895200, "allotment record should preserve initial public offer shares")
    assert_equal(record["applicationSummary"]["minAmountHKD"], 2848.44, "allotment record should preserve entry fee")
    assert_true(record["applicationTiers"], "allotment record should preserve application tiers")


def test_vertical_basis_table_parser_handles_split_lottery_rows():
    text = """
    香港公開發售的分配基準
    所申請H股數目
    有效申請數目
    配發╱抽籤基準
    獲配發股份佔所申請H股總數的
    概約百分比
    100
    57,352
    0股H股
    2.00%
    100
    1,171
    100股H股
    200
    9,684
    0股H股
    1.30%
    200
    259
    100股H股
    200,000
    4,551
    100股H股
    0.05%
    總計
    177,196
    """

    rows = app.parse_basis_rows(text, {"applicationSummary": {"aMaxShares": 100000, "bMinShares": 200000}})

    one_lot = rows[0]
    assert_equal(one_lot["group"], "A", "one-lot row should be group A")
    assert_equal(one_lot["sharesApplied"], 100, "one-lot shares should be parsed")
    assert_equal(one_lot["validApplications"], 58523, "split valid applications should be combined")
    assert_equal(one_lot["successfulApplications"], 1171, "split lottery winners should be combined")
    assert_equal(one_lot["sharesAllotted"], 100, "split allotted shares should keep per-winner allotted shares")
    assert_equal(one_lot["approxPercent"], 2.0, "official approximate percentage should be preserved")
    assert_equal(rows[-1]["group"], "B", "large row should be group B when no explicit group heading exists")


def test_vertical_basis_table_parser_handles_explicit_ab_groups_and_extra_lottery():
    text = """
    香港公開發售的分配基準
    甲組
    所申請
    H股數目
    有效
    申請數目
    分配╱抽籤基準
    獲分配H股佔
    所申請H股總數的
    概約百分比
    150
    38,516
    38,516名申請人中有1,156名獲分配150股H股
    3.00%
    總計
    220,211
    甲組獲接納申請人總數：24,476
    乙組
    所申請
    H股數目
    有效
    申請數目
    分配╱抽籤基準
    獲分配H股佔
    所申請H股總數的
    概約百分比
    1,050,000
    1,129
    150股H股，另加1,129名申請人中有121名
    獲分配額外150股H股
    0.02%
    總計
    31,164
    """

    rows = app.parse_basis_rows(text, {"applicationSummary": {"aMaxShares": 150000, "bMinShares": 300000}})

    assert_equal(rows[0]["group"], "A", "explicit A section should be preserved")
    assert_equal(rows[0]["successfulApplications"], 1156, "A lottery winners should be parsed")
    assert_equal(rows[1]["group"], "B", "explicit B section should be preserved")
    assert_equal(rows[1]["sharesApplied"], 1050000, "B shares should be parsed")
    assert_equal(rows[1]["successfulApplications"], 1129, "guaranteed B row should mark all applications as successful")
    assert_equal(rows[1]["extraLotteryWinners"], 121, "extra lottery winners should be parsed")


def test_check_response_falls_back_to_predefined_allotment_when_new_listing_row_lacks_allotment_link():
    originals = {
        "sync_new_listing_candidates": app.sync_new_listing_candidates,
        "read_official_updates": app.read_official_updates,
        "build_active_update_candidates": app.build_active_update_candidates,
        "refresh_estimated_subscription_multiples": app.refresh_estimated_subscription_multiples,
        "find_allotment_notice": app.find_allotment_notice,
        "apply_official_update": app.apply_official_update,
    }
    try:
        app.sync_new_listing_candidates = lambda: {
            "seenRows": [{
                "code": "03388",
                "name": "創想三維",
                "announcement": "https://example.test/03388_notice.pdf",
                "prospectus": "https://example.test/03388_prospectus.pdf",
                "allotment": None,
            }],
            "newRecords": [],
        }
        app.read_official_updates = lambda: {"generatedAt": "2026-05-29T09:00:00", "stocks": []}
        app.build_active_update_candidates = lambda: [{
            "code": "03388",
            "name": "創想三維",
            "status": "current",
            "stockId": None,
        }]
        app.refresh_estimated_subscription_multiples = lambda candidates=None: {"generatedAt": "2026-05-29T09:01:00", "stocks": []}
        app.find_allotment_notice = lambda code, stock_id=None: {
            "status": "found",
            "title": "公告及通告 - [配發結果] 分配結果公告",
            "url": "https://example.test/03388_allotment.pdf",
            "searchUrl": app.HKEX_PREDEFINED_ALLOTMENT_URL,
        }
        app.apply_official_update = lambda code, pdf_url=None: {
            "message": "03388 已写入",
            "stock": {"stockCode": code, "status": "listed", "source": {"pdf": pdf_url}},
        }

        body = app.build_check_official_updates_response()

        assert_equal(body["items"][0]["status"], "applied", "predefined allotment fallback should be applied")
        assert_equal(body["items"][0]["applied"]["stock"]["source"]["pdf"], "https://example.test/03388_allotment.pdf", "fallback PDF should be used")
    finally:
        for name, value in originals.items():
            setattr(app, name, value)


def main():
    test_predefined_allotment_page_entries_are_parsed()
    test_find_allotment_notice_uses_predefined_page_before_title_search()
    test_minimal_allotment_record_preserves_prelisting_terms_when_basis_parse_fails()
    test_vertical_basis_table_parser_handles_split_lottery_rows()
    test_vertical_basis_table_parser_handles_explicit_ab_groups_and_extra_lottery()
    test_check_response_falls_back_to_predefined_allotment_when_new_listing_row_lacks_allotment_link()
    print("official update workflow tests passed")


if __name__ == "__main__":
    main()
