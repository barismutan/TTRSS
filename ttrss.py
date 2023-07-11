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

class NoLinksFoundException(Exception):
    def __init__(self):
        super().__init__("No links found")

class TTRSS:
    def __init__(self,config):
        self.GPT_API_KEY=config['GPT_API_KEY']
        self.gpt_endpoint=config['gpt_endpoint']
        self.endpoint=config['ttrss_url']
        self.user=config['ttrss_user']
        self.password=config['ttrss_password']
        self.gpt_config=config['gpt_config']
        # self.mrkdwn_template=config['mrkdwn_template']
        self.zapier_webhook=config['zapier_webhook']
        # self.message_time=config['message_time']

        self.UNREAD_BODY={
            "op":"getHeadlines",
            "feed_id":"0",
            "view_mode":"unread",
            "is_cat":"1"
        }

        self.MARK_AS_READ_BODY={
            "op":"updateArticle",
            "article_ids":None,
            "mode":0,
            "field":2,
            "sid":""
        }#NOTE: field 2 is the "unread" field, setting it to 0 <false> ideally marks it as read

        self.MARK_AS_UNREAD_BODY={
            "op":"updateArticle",
            "article_ids":None,
            "mode":1,
            "field":2,
            "sid":""
        }

        self.EXTERNAL_HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Set-Fetch-Site': 'none',
            'Accept-Encoding': 'gzip, deflate',
            'Set-Fetch-Mode': 'navigate',
            'Sec-Fetch-Dest': 'document',

            
        }
        
        with open(config['prompt_file'],'r') as f:
            self.prompt=f.read()
        
        with open(config['question_file'],'r') as f:
            self.question=f.read()
        
        with open(config['mrkdwn_template'],'r') as f:
            self.mrkdwn_template=f.read()

        
        self.session_id=self.login()
        openai.api_key=self.GPT_API_KEY

        self.extract_link_callbacks=[self.get_read_more_href,self.get_last_body_href]
        # self.scoring_metric=config['scoring_metric']

    def trim_text(self,text):
        #return first 80% of text
        return text[:int(len(text)*0.8)]

    def login(self):
        body = {
            "op": "login",
            "user": self.user,
            "password": self.password
        }
        response=requests.get(self.endpoint,data=json.dumps(body))
        response_content=response.json()['content']
        print(response_content)

        return response_content['session_id']

    def get_article(self,article_id):
        body = {
            "op": "getArticle",
            "sid": self.session_id,
            "article_id": article_id
        }
        response=requests.get(self.endpoint,data=json.dumps(body))
        return response.json()['content'][0] #they put the thing in an array for some reason

    def get_article_link_databreaches(self,article):
        return article['link']

    def get_article_link_original(self,data_breaches_link):

        response=self.make_request_with_session(data_breaches_link)
        if response==None:
            raise NoLinksFoundException() #TODO: change this to a different exception
        html=response.content.decode('utf-8') if response.status_code==200 \
                                            else self.invoke_selenium(data_breaches_link)
        
        for callback in self.extract_link_callbacks:
            href=callback(html)
            if href is not None:
                print("HREF:"+href) 
                return href
            
        raise NoLinksFoundException()

    def get_last_body_href(self,html):
        soup = BeautifulSoup(html, 'html.parser')
        #get the div with the class "entry-content"
        entry_content=soup.find('div',attrs={'class':'entry-content'})
        #remove the div with class "crp_related" in the div
        links = entry_content.select('a:not(div.crp_related a)')
        print("LINKS:"+str(links))

        if len(links)>0:
            return links[-1]['href']
        return None
    
        #NOTE: this can probably throw some exception, but I'm not sure what it would be.


    def get_read_more_href(self,html):
        pattern=r'Read more at.*?href="(.*?)"'
        href=re.findall(pattern,html,re.DOTALL)
        if len(href)==0:
            return None
        else:
            return href[0]

    def remove_excess_whitespace(self,text):
        text=re.sub(r'\n',' ',text)
        text=re.sub(r'\s+',' ',text)
        text=re.sub(r'\t+',' ',text)
        return text

    def extract_text(self,html):
        # print("HTML:"+html)
        soup = BeautifulSoup(html.text, 'html.parser')
        full_text=soup.get_text()
        text=self.remove_excess_whitespace(full_text)
        return text

    def get_headlines(self):
        response=requests.get(self.endpoint,data=json.dumps(self.UNREAD_BODY))
        return response.json()['content']

    def get_num_articles(self,headlines):
        return len(headlines)

    def gpt_query(self,article):
        # openai.api_key=self.GPT_API_KEY
        prompt=self.prompt+article
        # print("Prompt:"+prompt)
        # print("ARTICLE:"+article)
        # print(openai.api_key)
        # return
        logging.debug("Querying GPT-3.5 Turbo.")
        completion = openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[

            {"role": "assistant", "content": prompt}

        ],
    timeout=30
    )
        print("Completion:\n"+str(completion))
        try:
            completion_dict=ast.literal_eval(str(completion.choices[0]['message']['content']))
        except SyntaxError as e:
            logging.error("Syntax error (Probably caused by GPT response.):"+str(e))
            logging.error("GPT response:"+str(completion))
            return None
        # completion_dict=json.loads(str(completion.choices[0]['message']['content']))
        return completion_dict

    def make_request_with_session(self,url):
        try:
            session=requests.Session()

            response=session.get(url,headers=self.EXTERNAL_HEADERS,timeout=10)
            print("MAKE REQUEST WITH SESSION RESPONSE:"+str(response))
        except requests.exceptions.MissingSchema as e:
            logging.error("Missing schema:"+str(e))
            return None
        except requests.exceptions.ReadTimeout as e:
            logging.error("Read timeout:"+str(e))
            return None
        # print("Response:"+str(response))
        return response

    def invoke_selenium(self,url):
        dr=webdriver.Safari()
        dr.get(url)
        bs=BeautifulSoup(dr.page_source,'html.parser')
        html=bs.prettify()
        return html

    def mark_as_read(self,article_id): #idea: we can make this a class.
        mark_as_read_body=self.MARK_AS_READ_BODY
        mark_as_read_body['article_ids']=article_id
        mark_as_read_body['sid']=self.session_id

        response=requests.post(self.endpoint,data=json.dumps(
            mark_as_read_body
                                            ))

        return response
    
    def mark_as_unread(self,article_id):
        mark_as_unread_body=self.MARK_AS_UNREAD_BODY
        mark_as_unread_body['article_ids']=article_id
        mark_as_unread_body['sid']=self.session_id

        response=requests.post(self.endpoint,data=json.dumps(
            mark_as_unread_body
                                            ))

        return response

    def process_unread(self,article_id):

        article=self.get_article(article_id)
        article_link=self.get_article_link_databreaches(article)
        original_link=self.get_article_link_original(article_link)
        print("does it get here?" + original_link)
        html=self.make_request_with_session(original_link)
        if html==None:
            return
        text=self.extract_text(html)
        print("TEXT:"+text)
        try:
            query_result=self.gpt_query(text)
            if query_result is None:
                return 
            # self.mark_as_read(article_id)
            print("MARKED AS READ")
        except openai.error.InvalidRequestError:

            while True:
                text=self.trim_text(text)
                try:
                    print("Trying again with shorter text")
                    query_result=self.gpt_query(text)
                    if query_result is None: 
                        # break
                        return # to not mark as read NEW
                    self.mark_as_read(article_id)
                    print("MARKED AS READ")
                    break
                except openai.error.InvalidRequestError as e:
                    print(len(text))
                    print(e)
                    continue

        query_result['Reference']=original_link
        return query_result


    def generate_mrkdwn(self,query_result):
        print("QUERY RESULT:" +str(query_result))
        mrkdwn=self.mrkdwn_template.format(title=query_result['Title'],\
                                        organization=query_result['Victim Organization'],\
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
        print("MRKDWN:"+mrkdwn)
        return mrkdwn

    def message_zapier(self,mrkdwn):
        #make the post request, encode mrkdwn as utf-8
        response=requests.post(self.zapier_webhook,data=mrkdwn.encode('utf-8'))
        return response


    def job(self):
   
        self.session_id=self.login()
        unread_body=self.UNREAD_BODY
        unread_body['sid']=self.session_id
        headlines=self.get_headlines()

        batch=[]
        for headline in headlines:
            try:
                print("HEADLINE and ID:"+str(headline)+str(headline['id']))
                try:
                    query_result=self.process_unread(headline['id'])
                except Exception as e:
                    #HERE : in the future we should have a function that takes in the exception and does the hanndling.
                    logging.error(e)
                    continue
                if query_result is None: #way better idea is to wrap the whole thing in a try except for SyntaxError.
                    continue
                self.mark_as_read(headline['id'])
                markdown=self.generate_mrkdwn(query_result)
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
        self.message_zapier(batch_concat)



def schedule_job(config):
    ttrss=TTRSS(config)
    for message_time in config['message_times']:
        schedule.every().day.at(message_time).do(ttrss.job)

    while True:
        schedule.run_pending()
        #sleep for 11 hours and 59 minutes
        time.sleep(43140)

def score_article(self,gpt_response):
    pass

if __name__ =="__main__":
    logging.basicConfig(filename='TTRSS.log',level=logging.DEBUG)
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--config', dest='config', default='config.json',
                        help='config file path', required=True)
    
    parser.add_argument('--test', dest='test',
                        help='Specify whether to run in test mode (no scheduling)',required=True)
    
    logging.info("[{}]Starting TTRSS".format(str(datetime.now())))
    args = parser.parse_args()
    with open(args.config) as f:
        config=json.load(f)

    logging.info("[{}]Starting TTRSS".format(str(datetime.now())))

    if args.test=="true":
        ttrss=TTRSS(config)
        ttrss.job()
    elif args.test=="false":
        schedule_job(config)
    else:
        print("Invalid argument for --test, must be true or false")



#TODO: check response status code from ttrss
#TODO: setup logger w/ datetime
#TODO: rework the way we handle SyntaxError exception caused by GPT response, see line 266
#NOTE: is there a limit on the size of the text we can send to slack?
#NOTE: i think gpt just outputs 'Not specified.' as the whole text if it can't find anything useful, do we
#catch the exception and just skip the article, or do we change the prompt?
#NOTE: sometimes the request takes too long, modify the default timeout for requests.
#NOTE: sometimes when the page has a banner, we get stuck.
#NOTE: sometimes the page has a paywall, we get stuck.
#NOTE: we need to add a timeout to gpt query.
#NOTE: 502 error from bad gateway when querying gpt, need to handle this.
#NOTE: we get SSL error from some sites, need to handle this.
#NOTE: better idea: DO THE MARK AS READ AFTER THE CALL TO THE PROCESS UNREAD FUNCTION, embed some logic there.
#NOTE: We are getting 403 errors from some sites, including cisa.gov

            
    


