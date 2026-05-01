import pandas as pd
import pygsheets


def update_election_sheet_cells_only(
    results_df: pd.DataFrame,
    spreadsheet_id: str,
    worksheet_title: str,
    service_account_json: str,
) -> pd.DataFrame:
    """
    Update only the 'votes' and 'precincts_reporting' cells in a Google Sheet
    using a DataFrame formatted like combined_election_data_sample.csv.

    Matching logic:
    - results_df.elex_name <-> sheet.contest
    - results_df.cand_name <-> sheet.first_name + ' ' + sheet.last_name
      (or last_name only for Yes/No ballot rows)

    Returns a DataFrame of matched rows and the values written.
    """

    required_cols = {"elex_name", "cand_name", "votes", "prec_reporting"}
    missing = required_cols - set(results_df.columns)
    if missing:
        raise ValueError(f"results_df is missing required columns: {sorted(missing)}")

    src = results_df.copy()
    src["elex_name"] = src["elex_name"].astype(str).str.strip()
    src["cand_name"] = src["cand_name"].astype(str).str.strip()
    src["votes"] = pd.to_numeric(src["votes"], errors="coerce").fillna(0).astype(int)
    src["prec_reporting"] = pd.to_numeric(src["prec_reporting"], errors="coerce")

    src["match_key"] = (
        src["elex_name"].str.lower().str.replace(' -', '', regex=False).
        str.replace(r"\s+", " ", regex=True)
        + "||"
        + src["cand_name"].str.lower().str.replace(r"\s+", " ", regex=True)
    )

    if src["match_key"].duplicated().any():
        dups = src.loc[src["match_key"].duplicated(keep=False), ["elex_name", "cand_name"]]
        raise ValueError(f"Duplicate contest/candidate pairs found in results_df:\n{dups}")

    src_map = src.set_index("match_key")[["votes", "prec_reporting"]]
    print(src_map)

    gc = pygsheets.authorize(service_file=service_account_json)
    sh = gc.open_by_key(spreadsheet_id)
    wks = sh.worksheet_by_title(worksheet_title)

    sheet_df = wks.get_as_df(empty_value="", numerize=False)

    required_sheet_cols = {"contest", "first_name", "last_name", "votes", "precincts_reporting"}
    missing_sheet = required_sheet_cols - set(sheet_df.columns)
    if missing_sheet:
        raise ValueError(f"Sheet is missing required columns: {sorted(missing_sheet)}")

    for col in ["contest", "first_name", "last_name"]:
        sheet_df[col] = sheet_df[col].fillna("").astype(str).str.strip()

    sheet_df["contest"] = sheet_df["contest"].replace("", pd.NA).ffill().fillna("")


    sheet_df["candidate_name"] = (
        (sheet_df["first_name"] + " " + sheet_df["last_name"])
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    sheet_df.loc[sheet_df["candidate_name"] == "", "candidate_name"] = (
        sheet_df.loc[sheet_df["candidate_name"] == "", "last_name"]
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

    sheet_df["match_key"] = (
        sheet_df["contest"].str.lower().str.replace(r"\s+", " ", regex=True)
        + "||"
        + sheet_df["candidate_name"].str.lower().str.replace(r"\s+", " ", regex=True)
    )

    header_map = {col: idx + 1 for idx, col in enumerate(sheet_df.columns[:-2])}
    votes_col = header_map["votes"]
    precincts_col = header_map["precincts_reporting"]

    updates_made = []

    for sheet_idx, row in sheet_df.iterrows():
        key = row["match_key"]
        if key not in src_map.index:
            continue

        new_votes = src_map.at[key, "votes"]
        new_precincts = src_map.at[key, "prec_reporting"]

        sheet_row_num = sheet_idx + 2  # +1 for 1-based sheet rows, +1 for header row

        current_votes = pd.to_numeric(row["votes"], errors="coerce")
        current_precincts = pd.to_numeric(row["precincts_reporting"], errors="coerce")

        if pd.isna(current_votes) or current_votes != new_votes:
            wks.update_value((sheet_row_num, votes_col), int(new_votes))

        if pd.isna(current_precincts) or current_precincts != new_precincts:
            wks.update_value((sheet_row_num, precincts_col), float(new_precincts))

        updates_made.append({
            "sheet_row": sheet_row_num,
            "contest": row["contest"],
            "candidate_name": row["candidate_name"],
            "votes": int(new_votes),
            "precincts_reporting": float(new_precincts),
        })

    return pd.DataFrame(updates_made)