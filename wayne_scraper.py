import requests
from bs4 import BeautifulSoup
import pandas as pd

DETROIT_ELEX_NAMES = [
    'Mayor - City of Detroit',
    'Clerk - City of Detroit',
    'City Council At- Large - City of Detroit',
    'City Council - Detroit District 2',
    'City Council - Detroit District 3',
    'City Council - Detroit District 5',
    'City Council - Detroit District 6',
    'City Council - Detroit District 7',
    'Police Commissioner - Detroit District 6'
]

#helper functions

#convert strings to clean ints
def convert_num(val):
    if type(val) == str:
        return int(val.strip().replace(",",""))
    else:
        return int(val)


#parse table function -> pass indiv. election results table and return df of Candidate results
def parse_elec_table(table):
    election_el = table.find('div', 'display-results-box-a').find('h1')

    election_name = str(election_el).split('<br/>')[0].replace('<h1>', '')
    
    rows = table.find_all('div', class_=['section group', 'section group winner', 'section group tied'])
    precincts_reported = rows[0].find('div', class_='precinct-fully').text.split(':')[1]
    
    #iterate through Candidate rows
    cand_df = pd.DataFrame({
        'election': [],
        'cand_name': [],
        'cand_party': [],
        'cand_vote_count': [],
        'precincts_reported': [] 
    })
    for i in range(1, len(rows)-3):
        cand_row = rows[i]

        
        box_d = cand_row.find('div', class_='col display-results-box-d')

        
        cand_name = box_d.find('h1').text.strip()

        #no party for proposals, value should be NA
        try:
            cand_party = box_d.find('h2').text.strip()
        except:
            cand_party = 'NA'
        
        box_f = cand_row.find('div', class_='col display-results-box-f')
        cand_vote_count = convert_num(box_f.find('h1').text.strip())

        elex_name = election_name
        precincts = precincts_reported
    
        row_df = pd.DataFrame({'election': [elex_name],
                      'cand_name': [cand_name],
                      'cand_party': [cand_party],
                      'cand_vote_count': [cand_vote_count],
                              'precincts_reported': [precincts]})
    
        cand_df = pd.concat([cand_df, row_df])
    
    return cand_df

#format scraped election data
def format_elex_data_wayne(input_df, election):
    filtered = input_df[input_df['election'] == election]
    filtered = filtered.rename({'cand_name': 'Candidate', 'cand_vote_count': 'Votes', 'precincts_reported': 'Precincts'}, axis=1)
    filtered['Votes'] = filtered['Votes'].apply(convert_num)
    filtered['Total Votes'] = filtered['Votes'].sum()

    vote_vals = filtered['Votes']
    total_votes = filtered['Total Votes'].values[0]

    if total_votes == 0:
        percent_vals = [0]*len(vote_vals)
    else:
        percent_vals = []
        for vote in vote_vals:
            percent_vals.append(float(vote)/float(total_votes)*100)

        

    filtered['Percent'] = percent_vals

    #remove write-in votes
    filtered = filtered[filtered['Candidate'] != 'Write-In']
    
    return filtered[['Candidate', 'Votes', 'Percent', 'Total Votes', 'Precincts']]

def format_sheet_name(title):
    #get rid of the last '-' in the string
    stripped = title.strip()
    
    if stripped[-1] == '-':
        formatted = stripped[:-1]
    else:
        formatted = stripped.copy()
    
    #uppercase everything
    formatted = formatted.upper()

    return formatted.strip()

def format_final_data(df):
    #Split precincts_reported into two columns: prec_reporting and tot_precincts
    df['prec_reporting'] = df['precincts_reported'].str.split('/').str[0].str.strip().apply(lambda x: int(x))
    df['tot_precincts'] = df['precincts_reported'].str.split('/').str[1].str.strip().apply(lambda x: int(x))

    #rename columns to match Macomb and Oakland
    df = df.rename({'election': 'elex_name', 'cand_vote_count': 'votes'}, axis=1)

    #add total votes, vote pct and num_cands columns
    df['tot_votes'] = df.groupby('elex_name')['votes'].transform('sum')
    df['vote_pct'] = df['votes']/df['tot_votes']*100
    df['num_cands'] = df.groupby('elex_name')['cand_name'].transform('count')
    return df[['elex_name', 'num_cands', 'tot_precincts', 'prec_reporting', 'tot_votes', 'cand_name', 'vote_pct', 'votes']]

def scrape_wayne():
    #Fetch the page content (elections)
    url = 'https://michigan.totalvote.com/Wayne/ResultsSW.aspx?type=CIT&cid=05&map=' #election results URL
    response = requests.get(url)

    print("Got URL")
    soup = BeautifulSoup(response.content, 'html.parser')

    #Locate the table and extract rows
    tables = soup.find_all('div', class_='wrapper-inside wrapper-border') #election table div
    print("Located table ")

    #loop through all Candidate tables and create a list of election dfs
    election_dfs = []
    for table in tables:
        election_dfs.append(parse_elec_table(table))

    print(f"Length of election_dfs object: {len(election_dfs)}")
    all_df_wayne = pd.concat(election_dfs)

    #add the proposals

    #fetch page content (proposals)
    url = 'https://michigan.totalvote.com/Wayne/ResultsSW.aspx?type=PRP&cid=05&map='
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    #Locate the table and extract rows
    tables = soup.find_all('div', class_='wrapper-inside wrapper-border') #election table div

    #loop through all Candidate tables and create a list of election dfs
    proposal_dfs = []
    for table in tables:
        proposal_dfs.append(parse_elec_table(table))

    all_proposals = pd.concat(proposal_dfs)
    all_df_wayne = pd.concat([all_df_wayne, all_proposals])
    final_df = format_final_data(all_df_wayne)
    return final_df