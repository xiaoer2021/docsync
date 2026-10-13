"前导零保护：编码类列不能被当成数值。"

from __future__ import annotations

from app.services.normalize.coercions import infer_type, looks_like_identifier


class TestLooksLikeIdentifier:
    def test_zero_padded_codes(self):
        assert looks_like_identifier(["007", "008", "009"])

    def test_mixed_width_codes(self):
        """编码列里常有几个不需要补零的（`100`），整列仍该当文本。"""
        assert looks_like_identifier(["007", "008", "100"])

    def test_phone_with_area_code(self):
        """带区号的电话以 0 开头 —— 丢了零就不是那个号码了。"""
        assert looks_like_identifier(["01012345678", "02187654321"])

    def test_plain_numbers_are_numbers(self):
        assert not looks_like_identifier(["7", "8", "100"])

    def test_zero_alone_is_number(self):
        """`0` 是数字 —— 只有「0 开头**且长度大于 1**」才算前导零。"""
        assert not looks_like_identifier(["0", "1", "2"])

    def test_decimals_are_numbers(self):
        assert not looks_like_identifier(["0.15", "0.20"])

    def test_real_numbers_in_column_wins(self):
        """列里出现真数字（int/float）就说明是数值列。"""
        assert not looks_like_identifier(["007", 8, "009"])

    def test_text_column_is_not_identifier(self):
        assert not looks_like_identifier(["A007", "B008"])

    def test_negative_numbers(self):
        assert not looks_like_identifier(["-007", "-008"])


class TestInferTypeKeepsLeadingZeros:
    def test_code_column_becomes_text(self):
        assert infer_type(["007", "008", "009"]) == "text"

    def test_plain_number_column_stays_numeric(self):
        "没有前导零的列不能被误判成文本。"
        assert infer_type(["7", "8", "9"]) in ("int", "float")

    def test_amounts_unaffected(self):
        assert infer_type(["100.5", "200.25"]) == "float"

    def test_dates_unaffected(self):
        assert infer_type(["2026-10-01", "2026-10-02"]) == "date"
