import urllib
import json
import pandas as pd
import requests

#Oakland County scraper function
def scrape_oakland():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
 
    #set election site URL
    current_ver_url = "https://results.enr.clarityelections.com/MI/Oakland/124349/current_ver.txt"
    ver_response = requests.get(current_ver_url, headers=headers)
    print(f"Status code: {ver_response.status_code}")
    print(f"Response content: {ver_response.text[:500]}")
    current_ver = ver_response.text.strip()
 
    print(current_ver)
    url = f"https://results.enr.clarityelections.com/MI/Oakland/124349/{current_ver}/json/en/summary.json"
    print(url)

    #request JSON response using url and headers
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            raw_data = response.read().decode()
            # print("Raw response:", raw_data[:200])
            data = json.loads(raw_data)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
    except Exception as e:
        print(f"An error occurred: {e}")


    # reformat data so each Candidate has their own row
    rows = []
    for entry in data:
        elex_name = entry.get("C")
        num_cands = entry.get("K")
        tot_precincts = entry.get("TP")
        prec_reporting = entry.get("PR")
        tot_votes = entry.get("TV")
        cand_names = entry.get("CH", [])
        vote_pcts = entry.get("PCT", [])
        votes = entry.get("V", [])
        
        for name, pct, vote in zip(cand_names, vote_pcts, votes):
            rows.append({
                "elex_name": elex_name,
                "num_cands": num_cands,
                "tot_precincts": tot_precincts,
                "prec_reporting": prec_reporting,
                "tot_votes": tot_votes,
                "cand_name": name,
                "vote_pct": pct,
                "votes": vote
            })

    # Create the DataFrame
    all_df_oakland= pd.DataFrame(rows)
    return all_df_oakland