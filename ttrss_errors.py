#-----------------Exceptions-----------------#
class NoLinksFoundException(Exception):
    def __init__(self,article_id):
        super().__init__("No links found for article "+str(article_id))

class NoHTMLFoundException(Exception):
    def __init__(self,article_id):
        super().__init__("No HTML found for article"+str(article_id))

class URLiSFileException(Exception):
    def __init__(self,article_id):
        super().__init__("URL is file for article "+str(article_id))

class BadStatusCodeException(Exception):
    def __init__(self,article_id,status_code):
        super().__init__("Bad status code "+str(status_code)+" for article "+str(article_id))

class NoGPTResponseException(Exception):
    def __init__(self,article_id):
        super().__init__("No GPT response for article "+str(article_id))

#-----------------Exceptions-----------------#