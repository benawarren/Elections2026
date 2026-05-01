from macomb_scraper import scrape_macomb
from oakland_scraper import scrape_oakland
from wayne_scraper import scrape_wayne
from update_sheet import update_election_sheet_cells_only

import pandas as pd
import pygsheets

def main():
    #execute Macomb Co. scraper function
    macomb = scrape_macomb()
    print(macomb.head())
    #execute Oakland Co. scraper function
    oakland = scrape_oakland()
    print(oakland.head())
    #execute Wayne Co. scraper function
    wayne = scrape_wayne()
    print(wayne.head())

    #combine dataframes
    combined = pd.concat([macomb.head(), oakland.head(), wayne], ignore_index=True)

    sheet_id= "1yNhyx82F5PN1hpJnfj1w0OUhbve0--JAhcJ456gcZ2w"
    
    updated_cells_df = update_election_sheet_cells_only(
        results_df=combined,
        spreadsheet_id=sheet_id,
        worksheet_title="Sheet1",
        service_account_json="credentials.json",
    )
    print(updated_cells_df)

if __name__ == "__main__":
    main()
