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
from ttrss_errors import *

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

        self.scoring_metric=config['scoring_metric']
        self.total_score=sum([vals for vals in self.scoring_metric["metric"].values()])
        
        with open(config['prompt_file'],'r') as f:
            self.prompt=f.read()
        
        with open(config['question_file'],'r') as f:
            self.question=f.read()
        
        with open(config['mrkdwn_template'],'r') as f:
            self.mrkdwn_template=f.read()
        
        
        self.anomalies_file=open(config['anomalies_file'],'a')
        self.anomalies_file.write("----beginning of new run at "+str(datetime.now())+"--------\n")

        self.FULL_CONTENT= 1
        self.SUMMARY_CONTENT=2

        
        self.session_id=self.login()
        openai.api_key=self.GPT_API_KEY

        self.extract_link_callbacks=[
            self.get_read_more_href,
            self.get_last_body_href_generic
            ]
        
        self.preprocess_html_callbacks=[
            self.remove_head,
            self.remove_scripts,
            self.remove_styles,
            self.remove_header,
            self.remove_footer,
            self.remove_navbar,
            self.remove_ads,
            
            self.remove_meta
            ]
        #TODO: i already wrote specific one for datareaches.net, might as well include it later...
        # self.scoring_metric=config['scoring_metric']




##-----------------TTRSS API calls-----------------##

    def login(self):
        body = {
            "op": "login",
            "user": self.user,
            "password": self.password
        }
        response=requests.get(self.endpoint,data=json.dumps(body))
        response_content=response.json()['content']
        #print(response_content)

        return response_content['session_id']

    def get_article(self,article_id):
        body = {
            "op": "getArticle",
            "sid": self.session_id,
            "article_id": article_id
        }
        response=requests.get(self.endpoint,data=json.dumps(body))
        return response.json()['content'][0] #they put the thing in an array for some reason

    def get_headlines(self,category):
        body=self.UNREAD_BODY
        body['feed_id']=category
        response=requests.get(self.endpoint,data=json.dumps(
                body
                ))
        
        return response.json()['content']
    
    def mark_as_read(self,article_id): #idea: we can make this a class.
        mark_as_read_body=self.MARK_AS_READ_BODY
        mark_as_read_body['article_ids']=article_id
        mark_as_read_body['sid']=self.session_id

        response=requests.post(self.endpoint,data=json.dumps(
            mark_as_read_body
                                            ))
        #print("MARK AS READ RESPONSE:"+str(response))
        return response
    
    def mark_as_unread(self,article_id):
        mark_as_unread_body=self.MARK_AS_UNREAD_BODY
        mark_as_unread_body['article_ids']=article_id
        mark_as_unread_body['sid']=self.session_id

        response=requests.post(self.endpoint,data=json.dumps(
            mark_as_unread_body
                                            ))

        return response

##-----------------TTRSS API calls-----------------##



##-----------------GPT calls-----------------##

    def gpt_query(self,article):
        # openai.api_key=self.GPT_API_KEY
        prompt=self.prompt+article
        # #print("Prompt:"+prompt)
        # #print("ARTICLE:"+article)
        # #print(openai.api_key)
        # return
        logging.debug("Querying GPT-3.5 Turbo.")
        completion = openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[

            {"role": "assistant", "content": prompt}

        ],
    timeout=30
    )
        #print("Completion:\n"+str(completion))
        try:
            completion_dict=ast.literal_eval(str(completion.choices[0]['message']['content']))
        except SyntaxError as e:
            logging.error("Syntax error (Probably caused by GPT response.):"+str(e))
            logging.error("GPT response:"+str(completion))
            return None
        # completion_dict=json.loads(str(completion.choices[0]['message']['content']))
        return completion_dict

    def score_gpt_response(self,gpt_response):
        score=0
        metric_keys=self.scoring_metric["metric"].keys()
        for field in gpt_response.keys():
            if gpt_response[field]!="N/A" and field in metric_keys:
                score += self.scoring_metric["metric"][field]

        return score

##-----------------GPT calls-----------------##









##-----------------Link Extractions-----------------## --> #TODO: move these to a different file

    def extract_article_link_from_summary(self,summary_link):

        response=self.make_request_with_session(summary_link)
        if response==None:
            raise NoLinksFoundException(summary_link) #TODO: change this to a different exception
        html=response.content.decode('utf-8') if response.status_code==200 \
                                            else self.invoke_selenium(summary_link)
        # #print("EXTRACTING LINK FROM FOLLOWING HTML: ------------------\n"+html+"\n------------------")  
        html=self.preprocess_html(html)

        for callback in self.extract_link_callbacks:
            href=callback(html)
            if href is not None:
                #print("EXTRACTED HREF:"+href) 
                href=self.remove_excess_whitespace(href)
                return href
        #print("NO LINKS FOUND IN FOLLOWING HTML: ------------------\n"+html+"\n------------------")  
        with open("error.html","w") as f:
            f.write(html)
        raise NoLinksFoundException(summary_link)

    def get_last_body_href_databreaches(self,html): # this only works for databreaches.net
        soup = BeautifulSoup(html, 'html.parser')
        #get the div with the class "entry-content"
        entry_content=soup.find('div',attrs={'class':'entry-content'})
        #remove the div with class "crp_related" in the div
        links = entry_content.select('a:not(div.crp_related a)')
        #print("LINKS:"+str(links))

        if len(links)>0:
            return links[-1]['href']
        return None
    
        #NOTE: this can probably throw some exception, but I'm not sure what it would be.

    def get_last_body_href_generic(self,html):
        soup = BeautifulSoup(html, 'html.parser')
        #print("CALLING GET LAST BODY HREF GENERIC")
        #get the outermost div within the body
        body=soup.find('body')
        #get the last link in the body
        links = body.select('a')
        #print("LINKS:"+str(links))
        logging.debug("LINKS:"+str(links))

        if len(links)>0:
            last_link_index=len(links)-1
            last_link=links[last_link_index]
            while last_link.has_attr('href')==False or  not last_link['href'].startswith('http'): #this can be reworked later...
                last_link=links[last_link_index]
                last_link_index-=1

                if last_link_index<0:
                    break
        
        if last_link_index<0:
            return None
        else:
            return last_link['href']

    def get_read_more_href(self,html):
        pattern=r'Read more at.*?href="(.*?)"'
        href=re.findall(pattern,html,re.DOTALL)
        if len(href)==0:
            return None
        else:
            return href[0]
        
    
        
##-----------------Link Extractions-----------------##

##-----------------Text Preprocessing-----------------##
    def preprocess_html(self,html):
        for callback in self.preprocess_html_callbacks:
            #print("Calling callback: "+str(callback))
            html=callback(html)
        return html
    
    def trim_text(self,text):
        #return first 80% of text
        return text[:int(len(text)*0.8)]

    def get_article_link(self,article):
        return article['link']

    def remove_excess_whitespace(self,text):
        text=re.sub(r'\n+',' ',text)
        text=re.sub(r'\s+',' ',text)
        text=re.sub(r'\t+',' ',text)
        return text

    def remove_header(self,text):
        text=re.sub(r'<header.*?</header>','',text,flags=re.DOTALL)
        return text

    def remove_footer(self,text):
        text=re.sub(r'<footer.*?</footer>','',text,flags=re.DOTALL)
        return text

    def remove_navbar(self,text):
        text=re.sub(r'<nav.*?</nav>','',text,flags=re.DOTALL)
        return text

    def remove_ads(self,text):
        text=re.sub(r'<ins.*?</ins>','',text,flags=re.DOTALL)
        return text

    def remove_scripts(self,text):
        text=re.sub(r'<script.*?</script>','',text,flags=re.DOTALL)
        return text

    def remove_styles(self,text):
        text=re.sub(r'<style.*?</style>','',text,flags=re.DOTALL)
        return text
    
    def remove_head(self,text):
        #debugging#
        # match=re.search(r'<head.*?</head>',text,flags=re.DOTALL)
        # if match:
        #     #print("MATCH:"+match.group(0))
        text=re.sub(r'<head.*?</head>','',text,flags=re.DOTALL)
        return text
    
    def remove_meta(self,text):
        text=re.sub(r'<meta.*?>','',text,flags=re.DOTALL)
        return text


    def extract_text(self,html):
        # #print("HTML:"+html)
        soup = BeautifulSoup(html.text, 'html.parser')
        full_text=soup.get_text()
        text=self.remove_excess_whitespace(full_text)
        return text

##-----------------Text Preprocessing-----------------##


##-----------------Utilities-----------------##
    def get_num_articles(self,headlines):
        return len(headlines)
    
    def make_request_with_session(self,url):
        try:
            session=requests.Session()

            response=session.get(url,headers=self.EXTERNAL_HEADERS,timeout=10)
            #print("MAKE REQUEST WITH SESSION RESPONSE:"+str(response))
        except requests.exceptions.MissingSchema as e:
            logging.error("Missing schema:"+str(e))
            return None
        except requests.exceptions.ReadTimeout as e:
            logging.error("Read timeout:"+str(e))
            return None
        # #print("Response:"+str(response))
        return response

    def invoke_selenium(self,url):
        dr=webdriver.Safari()
        dr.get(url)
        bs=BeautifulSoup(dr.page_source,'html.parser')
        html=bs.prettify()
        return html
    
    def generate_mrkdwn(self,query_result):
        #print("QUERY RESULT:" +str(query_result))
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
                                        reference=query_result['Reference'],\
                                        score=query_result['Score']\
                                            )
        #print("MRKDWN:"+mrkdwn)
        return mrkdwn

    def message_zapier(self,mrkdwn):
        #make the post request, encode mrkdwn as utf-8
        response=requests.post(self.zapier_webhook,data=mrkdwn.encode('utf-8'))
        return response



    def label_article_category(self,headlines,category): #NOTE: this is a workaround for the fact that the API does not return the category of the article rn.
        for headline in headlines:
            headline['category']=category
        return headlines


##-----------------Utilities-----------------##




##-----------------Logging-----------------##
    def write_anomaly(self,article_id,error):
        self.anomalies_file.write(str(datetime.now())+"\n")
        self.anomalies_file.write(str(article_id)+"\n")
        self.anomalies_file.write(str(error)+"\n")
        self.anomalies_file.write("--------------------\n")
        self.mark_as_read(article_id)
        ##print traceback of error
        #print(error)
        #print(traceback.format_exc())
        # exit()
        self.anomalies_file.flush()

##-----------------Logging-----------------##

    
##-----------------MAIN------------------##        

    def process_unread(self,article_id,article_category):

        article=self.get_article(article_id)
        if article_category==self.SUMMARY_CONTENT:
            article_link=self.get_article_link(article)#NOTE: change function name to get_article_link_summary later...  
            original_link=self.extract_article_link_from_summary(article_link)
        else:
            original_link=self.get_article_link(article)

        # #print("does it get here?" + original_link)
        html=self.make_request_with_session(original_link)
        # #print("HTML:"+str(html))
        if html is None:
            raise NoHTMLFoundException(article_id)
        text=self.extract_text(html)
        # #print("TEXT:"+text)
        try:
            query_result=self.gpt_query(text)
            if query_result is None:
                raise NoGPTResponseException(article_id)
            #print("MARKED AS READ")
        except openai.error.InvalidRequestError:

            while True:
                text=self.trim_text(text)
                try:
                    #print("Trying again with shorter text")
                    query_result=self.gpt_query(text)
                    if query_result is None: 
                        # break
                        return # to not mark as read NEW
                    self.mark_as_read(article_id)
                    #print("MARKED AS READ")
                    break
                except openai.error.InvalidRequestError as e:
                    # #print(len(text))
                    #print(e)
                    #print("Invalid request error. Trying again with shorter text.")
                    
                    continue

        query_result['Reference']=original_link
        return query_result


    def job(self):
        logging.debug("Starting job at "+str(datetime.now()))
        self.anomalies_file.write("Starting job at "+str(datetime.now())+"\n")
        self.session_id=self.login()
        unread_body=self.UNREAD_BODY
        unread_body['sid']=self.session_id

        headlines_full_content=self.get_headlines(category=self.FULL_CONTENT)
        headlines_summary_content=self.get_headlines(category=self.SUMMARY_CONTENT)

        headlines_full_content=self.label_article_category(headlines_full_content,self.FULL_CONTENT)
        headlines_summary_content=self.label_article_category(headlines_summary_content,self.SUMMARY_CONTENT)

        headlines=headlines_full_content+headlines_summary_content
        
        query_results=[] #DELETE THIS LATER

        batch=[]
        for headline in headlines:
            try:
                #print("HEADLINE and ID:"+str(headline)+str(headline['id']))
                try:
                    query_result=self.process_unread(headline['id'],headline['category'])
                    query_results.append(query_result)#DELETE THIS LATER
                    
                    result_score=self.score_gpt_response(query_result)
                    if result_score<self.scoring_metric['threshold']:
                        self.write_anomaly(headline['id'],"Score is below threshold at "+str(result_score))
                        self.mark_as_read(headline['id'])
                        continue

                except Exception as e:
                    #HERE : in the future we should have a function that takes in the exception and does the hanndling.
                    logging.error(e)
                    self.mark_as_read(headline['id'])
                    self.write_anomaly(headline['id'],e)
                    continue
                
                if query_result is None: #way better idea is to wrap the whole thing in a try except for SyntaxError.
                    logging.error("Query result is None for article:"+str(headline['id']))
                    self.mark_as_read(headline['id'])
                    self.write_anomaly(headline['id'],"Query result is None")
                    continue
                self.mark_as_read(headline['id'])
                query_result['Score']=str(result_score)+"/"+str(self.total_score)
                markdown=self.generate_mrkdwn(query_result)
                # #print("TEMPLATE MARKDOWN"+markdown)
                batch.append(markdown)
                #print("BATCH in for:"+str(batch))

            except NoLinksFoundException as e:
                logging.error("[{}]No links found for article:".format(str(datetime.now()))+"<"+str(headline['id'])+">")
                self.mark_as_read(headline['id'])
                self.write_anomaly(headline['id'],e)
                # logging.error(traceback.format_exc())
                continue # TODO: remove this
            # break #TODO: remove this

        #concatenate batch with newlines
        batch_concat='\n'.join(batch)
        #print("BATCH CONCAT:"+batch_concat)
        #print("BATCH:"+str(batch))

        # self.message_zapier(batch_concat)

        # with open("responses_with_inference.json","w") as f: ##COMMENT this later
        #     json.dump(query_results,f)



def schedule_job(config,batch_mode=False):
    ttrss=TTRSS(config)
    if batch_mode:
        for message_time in config['message_times']:
            schedule.every().day.at(message_time).do(ttrss.job)
    else:
        schedule.every().minute.do(ttrss.job)


    while True:
        schedule.run_pending()
        #sleep for 11 hours and 59 minutes
        if batch_mode:
            time.sleep(43140)
        else:
        #sleep for 59.5 minutes
            time.sleep(3570)

##-----------------MAIN------------------##



if __name__ =="__main__":
    logging.basicConfig(filename='TTRSS.log',level=logging.DEBUG)
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--config', dest='config', default='config.json',
                        help='config file path', required=True)
    
    parser.add_argument('--test', dest='test',
                        help='Specify whether to run in test mode (no scheduling)',required=True)
    
    parser.add_argument('--batch', dest='batch',
                        help='Specify whether to run in batch mode (send all articles at given intervals.)',required=False)
    

    
    logging.info("[{}]Starting TTRSS".format(str(datetime.now())))
    args = parser.parse_args()
    with open(args.config) as f:
        config=json.load(f)

    logging.info("[{}]Starting TTRSS".format(str(datetime.now())))
    try:
        if args.test=="true":
            ttrss=TTRSS(config)
            ttrss.job()
        elif args.test=="false":
            schedule_job(config,args.batch)
        else:
            print("Invalid argument for --test, must be true or false")
    except Exception as e:
        logging.error("[{}]Error in main:".format(str(datetime.now())))
        logging.error(traceback.format_exc())
        # print("Error in main:"+str(e))
        # print(traceback.format_exc())



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
#NOTE: some urls are pdfs, we need to take this into account.
#NOTE: picus library integration with mwalwares ISSUE
#NOTE: slack mention region ISSUE
#NOTE: infer location,industry
#NOTE: added mark as read in write_anomaly, no need to call that whenever write_anomaly is called already.
#NOTE: change anomalies to JSON format
#NOTE: move errors to a separate file

#NOTE: id : 1 --> FullContent || id : 2 --> Summary Content            
    

##NOTE: I moved the following to FullContent:
#bleepingcomputer.com
#helpnetsecurity.com
#theregister.com
#thehackernews.com
#securityweek.com
#hackread.com
#thecyberwire.com

