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
import logging
import traceback
import ast
from datetime import datetime
import time

UNREAD_BODY={
    "op":"getHeadlines",
    "feed_id":"0",
    "view_mode":"unread",
    "is_cat":"1"
}

MARK_AS_READ_BODY={
    "op":"updateArticle",
    "article_ids":None,
    "mode":0,
    "field":2,
    "sid":""
}#NOTE: field 2 is the "unread" field, setting it to 0 <false> ideally marks it as read

GPT_PROMPT='''
'''

class NoLinksFoundException(Exception):
    def __init__(self):
        super().__init__("No links found")

def trim_text(text):
    #return first 80% of text
    return text[:int(len(text)*0.8)]

def login(endpoint,user,password):
    body = {
        "op": "login",
        "user": user,
        "password": password
    }
    response=requests.get(endpoint,data=json.dumps(body))
    response_content=response.json()['content']
    print(response_content)

    return response_content['session_id']

def get_article(endpoint,session_id,article_id):
    body = {
        "op": "getArticle",
        "sid": session_id,
        "article_id": article_id
    }
    response=requests.get(endpoint,data=json.dumps(body))
    return response.json()['content'][0] #they put the thing in an array for some reason

def get_article_link_databreaches(article):
    return article['link']

def get_article_link_original(data_breaches_link):
    response=make_request_with_session(data_breaches_link)
    html=response.content.decode('utf-8') if response.status_code==200 \
                                          else invoke_selenium(data_breaches_link)
    
    pattern=r'Read more at.*?href="(.*?)"'
    href=re.findall(pattern,html,re.DOTALL)
    if len(href)==0:
        raise NoLinksFoundException()
    else:
        return href[0] #TODO:rework this

def remove_excess_whitespace(text):
    text=re.sub(r'\n',' ',text)
    text=re.sub(r'\s+',' ',text)
    text=re.sub(r'\t+',' ',text)
    return text

def extract_text(html):
    # print("HTML:"+html)
    soup = BeautifulSoup(html.text, 'html.parser')
    full_text=soup.get_text()
    text=remove_excess_whitespace(full_text)
    return text

def get_headlines(endpoint,session_id,body):
    response=requests.get(endpoint,data=json.dumps(body))
    return response.json()['content']

def get_num_articles(headlines):
    return len(headlines)

def gpt_query(api_key,prompt,article):
    openai.api_key=api_key
    prompt=prompt+article
    # print("Prompt:"+prompt)
    # print("ARTICLE:"+article)
    print(openai.api_key)
    # return
    completion = oresponse=openai.ChatCompletion.create(
  model="gpt-3.5-turbo",
  messages=[

        {"role": "assistant", "content": prompt}

    ]
)
    print("Completion:\n"+str(completion))
    completion_dict=ast.literal_eval(str(completion.choices[0]['message']['content']))
    # completion_dict=json.loads(str(completion.choices[0]['message']['content']))
    return completion_dict

def make_request_with_session(url):

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

def mark_as_read(endpoint,session_id,article_id): #idea: we can make this a class.
    MARK_AS_READ_BODY['article_ids']=article_id
    MARK_AS_READ_BODY['sid']=session_id
    response=requests.post(endpoint,data=json.dumps(
        MARK_AS_READ_BODY 
                                           ))

    return response

def process_unread(session_id,article_id,ttrss_endpoint,prompt,gpt_api_key):

    article=get_article(ttrss_endpoint,session_id,article_id)
    article_link=get_article_link_databreaches(article)
    original_link=get_article_link_original(article_link)
    html=make_request_with_session(original_link)
    text=extract_text(html)
    print("TEXT:"+text)
    try:
        query_result=gpt_query(gpt_api_key,prompt,text)
        mark_as_read(ttrss_endpoint,session_id,article_id)
        print("MARKED AS READ")
    except openai.error.InvalidRequestError:

        while True:
            text=trim_text(text)
            try:
                print("Trying again with shorter text")
                query_result=gpt_query(gpt_api_key,prompt,text)
                mark_as_read(ttrss_endpoint,session_id,article_id)
                print("MARKED AS READ")
                break
            except openai.error.InvalidRequestError as e:
                print(len(text))
                print(e)
                continue
    
    # print("QUERY RESULT:" +query_result)
    query_result['Reference']=original_link
    return query_result


def generate_mrkdwn(query_result,mrkdwn_template):
    print("QUERY RESULT:" +str(query_result))
    mrkdwn=mrkdwn_template.format(organization=query_result['Victim Organization'],\
                                  location=query_result['Victim Location'],\
                                    sector=query_result['Sectors'],\
                                    threat_actor=query_result['Threat Actor'],\
                                    threat_actor_aliases=query_result["Threat Actor Aliases"],\
                                    malware=query_result['Malware'],\
                                    cves=query_result['CVEs'],\
                                    impact=query_result['Impact'],\
                                    key_judgement=query_result['Key Judgement'],\
                                    change_analysis=query_result['Change Analysis'],\
                                    timeline_of_activity=query_result['Timeline of Activity'],\
                                    summary=query_result['Summary'],\
                                    actor_motivation=query_result['Actor Motivation'],\
                                    reference=query_result['Reference']
                                        )
    return mrkdwn

def message_zapier(mrkdwn,webhook):
    #make the post request, encode mrkdwn as utf-8
    response=requests.post(webhook,data=mrkdwn.encode('utf-8'))
    return response


def job(config):
    username=config['ttrss_user']
    password=config['ttrss_password']
    ttrss_endpoint=config['ttrss_url']
    gpt_api_key=config['GPT_API_KEY']
    with open(config['prompt_file']) as f:
        prompt=f.read()
    with open(config['mrkdwn_template']) as f:
        markdown_template=f.read()

    
    session_id=login(ttrss_endpoint,username,password)
    UNREAD_BODY['sid']=session_id
    headlines=get_headlines(ttrss_endpoint,session_id,UNREAD_BODY)

    batch=[]
    for headline in headlines:
        try:
            query_result=process_unread(session_id,headline['id'],ttrss_endpoint,prompt,gpt_api_key)
            markdown=generate_mrkdwn(query_result,markdown_template)
            # print("TEMPLATE MARKDOWN"+markdown)
            batch.append(markdown)
            print("BATCH in for:"+str(batch))

        except NoLinksFoundException as e:
            logging.error("[{}]No links found for article:".format(str(datetime.now()))+str(headline['id']))
            # logging.error(traceback.format_exc())
            continue # TODO: remove this
        # break #TODO: remove this

    #concatenate batch with newlines
    batch_concat='\n'.join(batch)
    print("BATCH CONCAT:"+batch_concat)
    print("BATCH:"+str(batch))
    message_zapier(batch_concat,config['zapier_webhook'])






if __name__ =="__main__":
    logging.basicConfig(filename='TTRSS.log',level=logging.DEBUG)
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--config', dest='config', default='config.json',
                        help='config file path', required=False)
    
    args = parser.parse_args()
    with open(args.config) as f:
        config=json.load(f)

    with open(config['prompt_file']) as f:
        GPT_PROMPT=f.read()
        
    for time in config['times']:
        schedule.every().day.at(time).do(job,config)
    while True:
        schedule.run_pending()
        time.sleep()
        #sleep for 11 hours and 59 minutes
        time.sleep(43140)

#TODO: check response status code from ttrss
#TODO: setup logger w/ datetime
  
            
    


