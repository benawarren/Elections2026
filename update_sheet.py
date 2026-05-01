import re
import time
import unicodedata
from typing import Iterable, List, Optional

import pandas as pd
import pygsheets


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = text.replace("’", "'").replace("`", "'")
    text = text.replace("–", "-").replace("—", "-")

    text = re.sub(r"\s*-\s*$", "", text)
    text = re.sub(r"[^\w\s'-]", " ", text)
    text = re.sub(r"\bwrite[\s-]?in\b", "write-in", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _build_candidate_name(first_name: object, last_name: object) -> str:
    first = "" if pd.isna(first_name) else str(first_name).strip()
    last = "" if pd.isna(last_name) else str(last_name).strip()
    full = f"{first} {last}".strip()
    return re.sub(r"\s+", " ", full)


def _require_columns(df: pd.DataFrame, required: Iterable[str], df_name: str) -> None:
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"{df_name} is missing required columns: {sorted(missing)}")


def _coerce_int_series(series: pd.Series, col_name: str, allow_null: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")

    if not allow_null and numeric.isna().any():
        bad_idx = numeric[numeric.isna()].index.tolist()[:10]
        raise ValueError(f"Invalid numeric values found in '{col_name}' at rows: {bad_idx}")

    if (numeric.dropna() < 0).any():
        bad_idx = numeric[numeric < 0].index.tolist()[:10]
        raise ValueError(f"Negative values found in '{col_name}' at rows: {bad_idx}")

    non_int_mask = numeric.dropna().mod(1).ne(0)
    if non_int_mask.any():
        bad_idx = numeric.dropna()[non_int_mask].index.tolist()[:10]
        raise ValueError(f"Non-integer values found in '{col_name}' at rows: {bad_idx}")

    return numeric.astype("Int64")


def _retry_update_values_batch(
    worksheet,
    ranges: List[str],
    values: List[List[List[int]]],
    retries: int = 3,
    sleep_seconds: float = 2.0,
) -> None:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            worksheet.update_values_batch(ranges, values)
            return
        except Exception as err:
            last_err = err
            if attempt == retries:
                break
            time.sleep(sleep_seconds * attempt)
    raise last_err


def update_election_sheet_cells_only(
    results_df: pd.DataFrame,
    spreadsheet_id: str,
    worksheet_title: str,
    service_account_json: str,
    fail_on_unmatched_source: bool = True,
    fail_on_unmatched_threshold: Optional[float] = 0.05,
    batch_size: int = 200,
) -> pd.DataFrame:
    """
    Update only the `votes` and `precincts_reporting` cells in a Google Sheet.

    Expected source columns:
      elex_name, cand_name, votes, prec_reporting

    Expected sheet columns:
      contest, first_name, last_name, votes, precincts_reporting

    Returns
    -------
    pd.DataFrame
        Audit dataframe of matched rows and written values.

    Notes
    -----
    - Handles sheets where `contest` appears only on the first row of each contest block
      by forward-filling blank contest cells.
    - Uses batched cell updates via pygsheets.update_values_batch(ranges, values).
    """

    required_src = {"elex_name", "cand_name", "votes", "prec_reporting"}
    _require_columns(results_df, required_src, "results_df")

    src = results_df.copy()

    src["elex_name_raw"] = src["elex_name"].astype(str).str.strip()
    src["cand_name_raw"] = src["cand_name"].astype(str).str.strip()

    src["votes"] = _coerce_int_series(src["votes"], "votes", allow_null=False)
    src["prec_reporting"] = _coerce_int_series(src["prec_reporting"], "prec_reporting", allow_null=False)

    src["contest_norm"] = src["elex_name_raw"].map(_normalize_text)
    src["candidate_norm"] = src["cand_name_raw"].map(_normalize_text)
    src["match_key"] = src["contest_norm"] + "||" + src["candidate_norm"]

    if (src["contest_norm"] == "").any():
        bad_idx = src.index[src["contest_norm"] == ""].tolist()[:10]
        raise ValueError(f"Blank normalized contest names in source rows: {bad_idx}")

    if (src["candidate_norm"] == "").any():
        bad_idx = src.index[src["candidate_norm"] == ""].tolist()[:10]
        raise ValueError(f"Blank normalized candidate names in source rows: {bad_idx}")

    if src["match_key"].duplicated().any():
        dups = src.loc[
            src["match_key"].duplicated(keep=False),
            ["elex_name_raw", "cand_name_raw", "match_key"]
        ].sort_values(["match_key", "elex_name_raw", "cand_name_raw"])
        raise ValueError(f"Duplicate contest/candidate pairs found in results_df:\n{dups}")

    src_map = src.set_index("match_key")[["votes", "prec_reporting"]]

    gc = pygsheets.authorize(service_file=service_account_json)
    sh = gc.open_by_key(spreadsheet_id)
    wks = sh.worksheet_by_title(worksheet_title)

    sheet_df = wks.get_as_df(empty_value="", numerize=False)

    required_sheet = {"contest", "first_name", "last_name", "votes", "precincts_reporting"}
    _require_columns(sheet_df, required_sheet, "sheet")

    header_row = wks.get_row(1, include_tailing_empty=False)
    header_map = {str(col).strip(): idx + 1 for idx, col in enumerate(header_row)}

    missing_headers = {"votes", "precincts_reporting"} - set(header_map)
    if missing_headers:
        raise ValueError(f"Worksheet header row is missing expected columns: {sorted(missing_headers)}")

    votes_col = header_map["votes"]
    precincts_col = header_map["precincts_reporting"]

    for col in ["contest", "first_name", "last_name"]:
        sheet_df[col] = sheet_df[col].fillna("").astype(str).str.strip()

    sheet_df["contest_original"] = sheet_df["contest"]
    sheet_df["contest"] = sheet_df["contest"].replace("", pd.NA).ffill().fillna("")

    still_blank = sheet_df["contest"].eq("")
    if still_blank.any():
        bad_rows = (sheet_df.index[still_blank] + 2).tolist()[:10]
        raise ValueError(
            f"Some sheet rows still have blank contest values after forward-fill. Sheet rows: {bad_rows}"
        )

    sheet_df["candidate_name"] = [
        _build_candidate_name(fn, ln)
        for fn, ln in zip(sheet_df["first_name"], sheet_df["last_name"])
    ]

    blank_candidate = sheet_df["candidate_name"].eq("")
    if blank_candidate.any():
        bad_rows = (sheet_df.index[blank_candidate] + 2).tolist()[:10]
        raise ValueError(f"Some sheet rows have blank candidate/option names. Sheet rows: {bad_rows}")

    sheet_df["contest_norm"] = sheet_df["contest"].map(_normalize_text)
    sheet_df["candidate_norm"] = sheet_df["candidate_name"].map(_normalize_text)
    sheet_df["match_key"] = sheet_df["contest_norm"] + "||" + sheet_df["candidate_norm"]

    if sheet_df["match_key"].duplicated().any():
        dups = sheet_df.loc[
            sheet_df["match_key"].duplicated(keep=False),
            ["contest", "candidate_name", "match_key"]
        ].sort_values(["match_key", "contest", "candidate_name"])
        raise ValueError(f"Duplicate contest/candidate pairs found in sheet:\n{dups}")

    source_keys = set(src["match_key"])
    sheet_keys = set(sheet_df["match_key"])

    unmatched_source_keys = sorted(source_keys - sheet_keys)
    unmatched_sheet_keys = sorted(sheet_keys - source_keys)

    unmatched_source_rate = len(unmatched_source_keys) / max(len(source_keys), 1)

    if fail_on_unmatched_source and unmatched_source_keys:
        sample = unmatched_source_keys[:10]
        raise ValueError(
            f"{len(unmatched_source_keys)} source rows did not match the sheet. "
            f"Sample keys: {sample}"
        )

    if (
        fail_on_unmatched_threshold is not None
        and unmatched_source_rate > fail_on_unmatched_threshold
    ):
        raise ValueError(
            f"Unmatched source key rate {unmatched_source_rate:.1%} exceeds threshold "
            f"{fail_on_unmatched_threshold:.1%}"
        )

    ranges_to_update: List[str] = []
    values_to_update: List[List[List[int]]] = []
    updates_made = []

    for sheet_idx, row in sheet_df.iterrows():
        key = row["match_key"]
        if key not in src_map.index:
            continue

        new_votes = int(src_map.at[key, "votes"])
        new_precincts = int(src_map.at[key, "prec_reporting"])

        current_votes = pd.to_numeric(pd.Series([row["votes"]]), errors="coerce").iloc[0]
        current_precincts = pd.to_numeric(pd.Series([row["precincts_reporting"]]), errors="coerce").iloc[0]

        sheet_row_num = sheet_idx + 2
        row_changed = False

        if pd.isna(current_votes) or int(current_votes) != new_votes:
            ranges_to_update.append(pygsheets.utils.format_addr((sheet_row_num, votes_col)))
            values_to_update.append([[new_votes]])
            row_changed = True

        if pd.isna(current_precincts) or int(current_precincts) != new_precincts:
            ranges_to_update.append(pygsheets.utils.format_addr((sheet_row_num, precincts_col)))
            values_to_update.append([[new_precincts]])
            row_changed = True

        if row_changed:
            updates_made.append({
                "sheet_row": sheet_row_num,
                "contest": row["contest"],
                "candidate_name": row["candidate_name"],
                "votes": new_votes,
                "precincts_reporting": new_precincts,
            })

    for start in range(0, len(ranges_to_update), batch_size):
        batch_ranges = ranges_to_update[start:start + batch_size]
        batch_values = values_to_update[start:start + batch_size]
        _retry_update_values_batch(wks, batch_ranges, batch_values)

    audit_df = pd.DataFrame(updates_made)
    audit_df.attrs["unmatched_source_keys"] = unmatched_source_keys
    audit_df.attrs["unmatched_sheet_keys"] = unmatched_sheet_keys
    audit_df.attrs["num_cell_updates"] = len(ranges_to_update)
    audit_df.attrs["num_rows_changed"] = len(updates_made)

    return audit_df