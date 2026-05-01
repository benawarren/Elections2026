import pandas as pd
import pytest
from unittest.mock import patch

from update_sheet import update_election_sheet_cells_only


class FakeWorksheet:
    def __init__(self, df, header_row=None, fail_times=0):
        self._df = df.copy()
        self._header_row = header_row or list(df.columns)
        self.fail_times = fail_times
        self.calls = []

    def get_as_df(self, empty_value="", numerize=False):
        return self._df.copy()

    def get_row(self, row_num, include_tailing_empty=False):
        assert row_num == 1
        return self._header_row

    def update_values_batch(self, ranges, values):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("Transient API failure")
        self.calls.append((ranges, values))


class FakeSpreadsheet:
    def __init__(self, worksheet):
        self.worksheet = worksheet

    def worksheet_by_title(self, title):
        return self.worksheet


class FakeClient:
    def __init__(self, worksheet):
        self.worksheet = worksheet

    def open_by_key(self, key):
        return FakeSpreadsheet(self.worksheet)


@pytest.fixture
def results_df():
    return pd.DataFrame({
        "elex_name": ["Huron Schools Bond", "Huron Schools Bond"],
        "cand_name": ["Yes", "No"],
        "votes": [123, 45],
        "prec_reporting": [8, 8],
    })


@pytest.fixture
def sheet_df():
    return pd.DataFrame({
        "contest": ["Huron Schools Bond", ""],
        "first_name": ["", ""],
        "last_name": ["Yes", "No"],
        "votes": ["0", "0"],
        "winner": ["no", "no"],
        "runoff": ["no", "no"],
        "precincts_reporting": ["", ""],
    })


def test_happy_path_updates_sparse_contest_rows(results_df, sheet_df):
    fake_wks = FakeWorksheet(sheet_df)

    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        audit_df = update_election_sheet_cells_only(
            results_df=results_df,
            spreadsheet_id="test",
            worksheet_title="Sheet1",
            service_account_json="creds.json",
            fail_on_unmatched_source=True,
        )

    assert audit_df.attrs["num_rows_changed"] == 2
    assert audit_df.attrs["num_cell_updates"] == 4
    assert audit_df.attrs["unmatched_source_keys"] == []
    assert len(fake_wks.calls) == 1
    assert fake_wks.calls[0][0] == ["D2", "G2", "D3", "G3"]
    assert fake_wks.calls[0][1] == [[[123]], [[8]], [[45]], [[8]]]


def test_missing_source_column_raises(sheet_df):
    bad_df = pd.DataFrame({
        "elex_name": ["Huron Schools Bond"],
        "cand_name": ["Yes"],
        "prec_reporting": [8],
    })

    fake_wks = FakeWorksheet(sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        with pytest.raises(ValueError, match="missing required columns"):
            update_election_sheet_cells_only(
                results_df=bad_df,
                spreadsheet_id="test",
                worksheet_title="Sheet1",
                service_account_json="creds.json",
            )


def test_duplicate_source_keys_raise(results_df, sheet_df):
    dup_df = pd.concat([results_df, results_df.iloc[[0]]], ignore_index=True)

    fake_wks = FakeWorksheet(sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        with pytest.raises(ValueError, match="Duplicate contest/candidate pairs found in results_df"):
            update_election_sheet_cells_only(
                results_df=dup_df,
                spreadsheet_id="test",
                worksheet_title="Sheet1",
                service_account_json="creds.json",
            )


def test_duplicate_sheet_keys_raise(results_df):
    dup_sheet_df = pd.DataFrame({
        "contest": ["Huron Schools Bond", ""],
        "first_name": ["", ""],
        "last_name": ["Yes", "Yes"],
        "votes": ["0", "0"],
        "winner": ["no", "no"],
        "runoff": ["no", "no"],
        "precincts_reporting": ["", ""],
    })

    fake_wks = FakeWorksheet(dup_sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        with pytest.raises(ValueError, match="Duplicate contest/candidate pairs found in sheet"):
            update_election_sheet_cells_only(
                results_df=results_df,
                spreadsheet_id="test",
                worksheet_title="Sheet1",
                service_account_json="creds.json",
            )


def test_bad_numeric_votes_raise(results_df, sheet_df):
    bad_num_df = results_df.copy()
    bad_num_df["votes"] = bad_num_df["votes"].astype(object)
    bad_num_df.loc[0, "votes"] = "abc"

    fake_wks = FakeWorksheet(sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        with pytest.raises(ValueError, match="Invalid numeric values found in 'votes'"):
            update_election_sheet_cells_only(
                results_df=bad_num_df,
                spreadsheet_id="test",
                worksheet_title="Sheet1",
                service_account_json="creds.json",
            )

def test_unmatched_source_rows_raise(sheet_df):
    unmatched_df = pd.DataFrame({
        "elex_name": ["Some Other Contest"],
        "cand_name": ["Yes"],
        "votes": [10],
        "prec_reporting": [1],
    })

    fake_wks = FakeWorksheet(sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        with pytest.raises(ValueError, match="source rows did not match the sheet"):
            update_election_sheet_cells_only(
                results_df=unmatched_df,
                spreadsheet_id="test",
                worksheet_title="Sheet1",
                service_account_json="creds.json",
                fail_on_unmatched_source=True,
            )


def test_retry_succeeds_after_transient_failure(results_df, sheet_df):
    fake_wks = FakeWorksheet(sheet_df, fail_times=1)

    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        audit_df = update_election_sheet_cells_only(
            results_df=results_df,
            spreadsheet_id="test",
            worksheet_title="Sheet1",
            service_account_json="creds.json",
            fail_on_unmatched_source=True,
        )

    assert audit_df.attrs["num_rows_changed"] == 2
    assert audit_df.attrs["num_cell_updates"] == 4
    assert len(fake_wks.calls) == 1


def test_no_changes_produces_no_write_calls(results_df):
    unchanged_sheet_df = pd.DataFrame({
        "contest": ["Huron Schools Bond", ""],
        "first_name": ["", ""],
        "last_name": ["Yes", "No"],
        "votes": [123, 45],
        "winner": ["no", "no"],
        "runoff": ["no", "no"],
        "precincts_reporting": [8, 8],
    })

    fake_wks = FakeWorksheet(unchanged_sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        audit_df = update_election_sheet_cells_only(
            results_df=results_df,
            spreadsheet_id="test",
            worksheet_title="Sheet1",
            service_account_json="creds.json",
            fail_on_unmatched_source=True,
        )

    assert audit_df.attrs["num_rows_changed"] == 0
    assert audit_df.attrs["num_cell_updates"] == 0
    assert fake_wks.calls == []


def test_write_in_normalization_matches():
    writein_results_df = pd.DataFrame({
        "elex_name": ["New Baltimore Mayor"],
        "cand_name": ["Write-In"],
        "votes": [4],
        "prec_reporting": [5],
    })

    writein_sheet_df = pd.DataFrame({
        "contest": ["New Baltimore Mayor"],
        "first_name": [""],
        "last_name": ["Write-in"],
        "votes": ["0"],
        "winner": ["no"],
        "runoff": ["no"],
        "precincts_reporting": [""],
    })

    fake_wks = FakeWorksheet(writein_sheet_df)
    with patch("pygsheets.authorize", return_value=FakeClient(fake_wks)):
        audit_df = update_election_sheet_cells_only(
            results_df=writein_results_df,
            spreadsheet_id="test",
            worksheet_title="Sheet1",
            service_account_json="creds.json",
            fail_on_unmatched_source=True,
        )

    assert audit_df.attrs["num_rows_changed"] == 1
    assert fake_wks.calls[0][0] == ["D2", "G2"]
    assert fake_wks.calls[0][1] == [[[4]], [[5]]]