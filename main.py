from macomb_scraper import scrape_macomb
from oakland_scraper import scrape_oakland
from wayne_scraper import scrape_wayne

import pandas as pd
import pygsheets

def update_sheet(df, sheet_url):
    gc = pygsheets.authorize(service_file='credentials.json')
    sh = gc.open_by_url(sheet_url)
    wks = sh[0]
    wks.set_dataframe(df, (1, 1), copy_head=True)
    print("Data added to Google Sheet successfully.")

def main():
    #execute Macomb Co. scraper function
    macomb = scrape_macomb()
    #execute Oakland Co. scraper function
    oakland = scrape_oakland()
    #execute Wayne Co. scraper function
    wayne = scrape_wayne()

    #combine dataframes
    combined = pd.concat([macomb, oakland, wayne], ignore_index=True)
    print(combined.head())

    #add to Google sheet
    sheet_url = "https://docs.google.com/spreadsheets/d/1yNhyx82F5PN1hpJnfj1w0OUhbve0--JAhcJ456gcZ2w/edit?usp=sharing"
    update_sheet(combined, sheet_url)

if __name__ == "__main__":
    main()
