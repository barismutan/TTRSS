import re
import json
import requests
import argparse
from bs4 import BeautifulSoup
import openai
from selenium import webdriver
from requests_html import HTMLSession
import requests
import schedule


def login(endpoint,user,password):
    body = {
        "op": "login",
        "user": user,
        "password": password
    }
    response=requests.get(endpoint,data=json.dumps(body))
    response_content=response.json()['content']

    return response_content['session_id']

def get_article(endpoint,session_id,article_id):
    body = {
        "op": "getArticle",
        "sid": session_id,
        "article_id": article_id
    }
    response=requests.get(endpoint,data=json.dumps(body))
    # print("Repsonse content:"+ str(response.content))
    return response.json()['content'][0] #they put the thing in an array for some reason

def get_article_link_databreaches(article):
    return article['link']

def get_article_link_original(data_breaches_link):
    # print("Data breaches link: "+ data_breaches_link)
    response=make_request_with_session(data_breaches_link)

    html=response.content.decode('utf-8') if response.status_code==200 \
                                          else invoke_selenium(data_breaches_link)
    
    pattern=r'Read more at.*?href="(.*?)"'
    href=re.findall(pattern,html,re.DOTALL)
    return href

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text()

def get_headlines(endpoint,session_id,feed_id=0,is_cat=1):
    body = {"sid":session_id,
            "op":"getHeadlines",
            "feed_id":feed_id,
            "is_cat":is_cat}
    response=requests.get(endpoint,data=json.dumps(body))
    return response.json()['content']

def get_num_articles(headlines):
    return len(headlines)

def gpt_query(prompt,questions,api_key):
    openai.api_key=api_key
    return openai.Completion.create(
        engine="davinci",
        prompt=GPT_PROMPT.format(article=prompt,questions=questions),
        temperature=0.7,
        max_tokens=64,
        top_p=1,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        stop=["\n"]
    ).choices[0].text

def make_request_with_session(url):
    session=HTMLSession()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Set-Fetch-Site': 'none',
        'Accept-Encoding': 'gzip, deflate',
        'Set-Fetch-Mode': 'navigate',
        'Sec-Fetch-Dest': 'document',

        
    }
    session=requests.Session()
    response=session.get(url,headers=headers)
    
    
    print("Response:"+str(response))
    return response

def invoke_selenium(url):
    dr=webdriver.Safari()
    dr.get(url)
    bs=BeautifulSoup(dr.page_source,'html.parser')
    html=bs.prettify()
    return html


if __name__ =="__main__":
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--config', dest='config', default='config.json',
                        help='config file path')
    
    args = parser.parse_args()
    with open(args.config) as f:
        config=json.load(f)

    with open(config['prompt']) as f:
        GPT_PROMPT=f.read()
    
    with open(config['questions']) as f:
        questions=f.readlines()

    
    TTRSS_ENDPOINT=config['TTRSS_ENDPOINT']

    session_id=login(TTRSS_ENDPOINT,config['user'],config['password'])
    headlines=get_headlines(TTRSS_ENDPOINT,session_id)


    breach_link_original_link={}
    with open(args.questions) as f:
        questions=f.readlines()
    for article in headlines:
        # print(article)
        article=get_article(TTRSS_ENDPOINT,session_id,article['id'])
        data_braches_link=get_article_link_databreaches(article)
        original_link=get_article_link_original(data_braches_link)
        print(original_link)  
        breach_link_original_link[data_braches_link]=original_link   
    
    print(breach_link_original_link)
    original_links=[]
    for data_breaches_link,original_link in breach_link_original_link.items():
        print("Data breaches link: "+ data_breaches_link + " Original link: "+ original_link[0] if len(original_link)>0 else "No original link")
        if len(original_link)>0:
            original_links.append(original_link[0])
    
    for original_link in original_links:
        html=make_request_with_session(original_link).content.decode('utf-8')
        text=extract_text(html)
        query_result=gpt_query(text,questions,config['OPENAI_API_KEY'])
        print(query_result)

        
            
    


