import boto3
import json
import os
import traceback
import datetime
import time
import re

from urllib import parse
import urllib.request

from langchain.llms import Bedrock
from langchain.docstore.document import Document
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from langchain.memory import ConversationBufferWindowMemory
from langchain.retrievers import AmazonKendraRetriever
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.chains import LLMChain

from langchain.embeddings import BedrockEmbeddings
from langchain.vectorstores.faiss import FAISS

from botocore.config import Config
from botocore.exceptions import ClientError

modelId = os.environ.get('model_id')
bedrock_region = os.environ.get('bedrock_region')
callLogTableName = os.environ.get('callLogTableName')
kendra_region = os.environ.get('kendra_region')
kendraIndex = os.environ.get('kendraIndex')
numberOfRelevantDocs = os.environ.get('numberOfRelevantDocs')

enableReference = 'true'
top_k = int(numberOfRelevantDocs)
MSG_LENGTH = 500

rag_method = 'RetrievalPrompt'

# websocket
connection_url = os.environ.get('connection_url')
client = boto3.client('apigatewaymanagementapi', endpoint_url=connection_url)
            
boto3_bedrock = boto3.client(
    service_name='bedrock-runtime',
    region_name=bedrock_region,
    config=Config(
        retries = {
            'max_attempts': 30
        }            
    )
)

HUMAN_PROMPT = "\n\nHuman:"
AI_PROMPT = "\n\nAssistant:"
def get_parameter(modelId):
    if modelId == 'anthropic.claude-v2:1':
        return {
            "max_tokens_to_sample":8191, # 8k
            "temperature":0.1,
            "top_k":250,
            "top_p":0.9,
            "stop_sequences": [HUMAN_PROMPT]            
        }
parameters = get_parameter(modelId)
    
# LLM 정의
llm = Bedrock(
model_id=modelId, 
client=boto3_bedrock, 
streaming=True,
callbacks=[StreamingStdOutCallbackHandler()],
model_kwargs=parameters)
    

map_chain = dict() # RAG
map_chat = dict() # general conversation  
    
kendraRetriever = AmazonKendraRetriever(
    index_id=kendraIndex,
    top_k=top_k,
    region_name=kendra_region,
    attribute_filter = {
        "EqualsTo": {
            "Key": "_language_code",
            "Value": {
                "StringValue": "ko"
            }
        },
    },
)
    
# Langchain Memory 활용 - 채팅 이력 고려
chat_memory = ConversationBufferMemory(human_prefix='Human', ai_prefix='Assistant')
conversation = ConversationChain(llm=llm, verbose=False, memory=chat_memory)

def get_prompt_template(query, convType):
    print('[get_prompt_template]')
 
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(query))
    print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        if convType == "normal": # General Conversation
            prompt_template = """\n\nHuman: 다음의 <history>는 Human과 Assistant의 친근한 이전 대화입니다. Assistant은 상황에 맞는 구체적인 세부 정보를 충분히 제공합니다. Assistant는 모르는 질문을 받으면 솔직히 모른다고 말합니다.

            <history>
            {history}
            </history>

            <question>            
            {input}
            </question>
            
            Assistant:"""

        elif (convType=='qa'):  # RAG
            prompt_template = """\n\nHuman: 다음의 참고자료를 이용하여 상황에 맞는 구체적인 세부 정보를 충분히 제공합니다. Assistant는 모르는 질문을 받으면 솔직히 모른다고 말합니다.
        
            참고자료:
            {context}

            질문:            
            {question}

            Assistant:"""
                
    else:  # English
        if convType == "normal": # General Conversation
            prompt_template = """\n\nHuman: Using the following conversation, answer friendly for the newest question. If you don't know the answer, just say that you don't know, don't try to make up an answer. You will be acting as a thoughtful advisor.

            <history>
            {history}
            </history>
            
            <question>            
            {input}
            </question>

            Assistant:"""

        elif (convType=='qa'):  # RAG
            prompt_template = """\n\nHuman: Use the following information to provide a concise answer to the question at the end. If you don't know the answer, just say that you don't know, don't try to make up an answer. 
            
            Reference Information:
            {context}
                        
            Question:
            {question}

            Assistant:"""

    return PromptTemplate.from_template(prompt_template)

def readStreamMsg(connectionId, requestId, stream):
    print("[readStreamMsg]")
    msg = ""
    if stream:
        for event in stream:
            print('event: ', event)
            msg = msg + event

            result = {
                'request_id': requestId,
                'msg': msg
            }
            sendMessage(connectionId, result)
    print('msg: ', msg)
    return msg
    
def sendMessage(id, body):
    print('[sendMessage]')
    print(body)
    try:
        client.post_to_connection(
            ConnectionId=id, 
            Data=json.dumps(body, ensure_ascii=False)
        )
    except Exception:
        err_msg = traceback.format_exc()
        print('err_msg: ', err_msg)
        raise Exception ("Not able to send a message")
        
def sendErrorMessage(connectionId, requestId, msg):
    errorMsg = {
        'request_id': requestId,
        'msg': msg,
        'status': 'error'
    }
    print('error: ', json.dumps(errorMsg))
    sendMessage(connectionId, errorMsg)

# 대화 기록을 저장할 딕셔너리
map = dict()  # Conversation

def getResponse(connectionId, jsonBody):
    
    print('[getResponse]')

    userId = jsonBody['user_id']
    body = jsonBody['body']
    requestId = jsonBody['request_id']
    requestTime = jsonBody['request_time']
    type = jsonBody['type']
    convType = jsonBody['conv_type'] # conversation type
    modelId = jsonBody['model_id']
    
    global conversation, enableReference
    global map_chain, map_chat, memory_chat, memory_chain
    # global llm, modelId, enableReference, rag_type, conversation
    # global parameters, map_chain, map_chat, memory_chat, memory_chain, debugMessageMode
    
    reference = ""
        
    # create memory
    if convType=='qa':
        if userId in map_chain:  
            memory_chain = map_chain[userId]
            print('memory_chain exist. reuse it!')
        else: 
            memory_chain = ConversationBufferWindowMemory(memory_key="chat_history", output_key='answer', return_messages=True, k=20)
            map_chain[userId] = memory_chain
            print('memory_chain does not exist. create new one!')

            allowTime = getAllowTime()
            load_chat_history(userId, allowTime, convType)

    else:    # normal 
        if userId in map_chat:  
            memory_chat = map_chat[userId]
            print('memory_chat exist. reuse it!')
        else:
            memory_chat = ConversationBufferWindowMemory(human_prefix='Human', ai_prefix='Assistant', k=20)
            map_chat[userId] = memory_chat
            print('memory_chat does not exist. create new one!')        

            allowTime = getAllowTime()
            load_chat_history(userId, allowTime, convType)
        
        conversation = ConversationChain(llm=llm, verbose=False, memory=memory_chat)
    
    # create memory
    # if userId in map:  
    #     print('memory exist. reuse it!')        
    #     chat_memory = map[userId]
    # else: 
    #     print('memory does not exist. create new one!')        
    #     chat_memory = ConversationBufferMemory(human_prefix='Human', ai_prefix='Assistant')
    #     map[userId] = chat_memory

    #     allowTime = getAllowTime()
    #     load_chatHistory(userId, allowTime, convType)
        
    #     conversation = ConversationChain(llm=llm, verbose=False, memory=chat_memory)
    
    start = int(time.time())
    
    msg = ""
    if type == 'text':
        text = body
        
        if convType == 'qa':   # question & answering
            msg, reference = get_answer_using_RAG(text, convType, connectionId, requestId)
        else: # general conversation
            msg = get_answer_from_conversation(text, conversation, convType, connectionId, requestId)
        
    elapsed_time = int(time.time()) - start
    print("total run time(sec): ", elapsed_time)
    
    return msg, reference
    
def get_answer_from_conversation(text, conversation, convType, connectionId, requestId):
    print('[get_answer_from_conversation]')
    conversation.prompt = get_prompt_template(text, convType)
    try: 
        isTyping(connectionId, requestId) 
        stream = conversation.predict(input=text)
        msg = stream
    except Exception:
        err_msg = traceback.format_exc()
        print('error message: ', err_msg)        
        
        raise Exception ("Not able to request to LLM")     

    return msg
    
def isTyping(connectionId, requestId):    
    msg_proceeding = {
        'request_id': requestId,
        'msg': '입력중...',
        'status': 'istyping'
    }
    sendMessage(connectionId, msg_proceeding)
        
def load_chat_history(userId, allowTime, convType):
    print('[load_chat_history]')
    dynamodb_client = boto3.client('dynamodb')

    response = dynamodb_client.query(
        TableName=callLogTableName,
        KeyConditionExpression='user_id = :userId AND request_time > :allowTime',
        ExpressionAttributeValues={
            ':userId': {'S': userId},
            ':allowTime': {'S': allowTime}
        }
    )

    for item in response['Items']:
        text = item['body']['S']
        msg = item['msg']['S']
        type = item['type']['S']

        if type == 'text':
            if convType=='qa':
                memory_chain.chat_memory.add_user_message(text)
                if len(msg) > MSG_LENGTH:
                    memory_chain.chat_memory.add_ai_message(msg[:MSG_LENGTH])                         
                else:
                    memory_chain.chat_memory.add_ai_message(msg)                       
            else:
                if len(msg) > MSG_LENGTH:
                    memory_chat.save_context({"input": text}, {"output": msg[:MSG_LENGTH]})
                else:
                    memory_chat.save_context({"input": text}, {"output": msg})
                
            chat_memory.save_context({"input": text}, {"output": msg}) 

def get_answer_using_RAG(text, convType, connectionId, requestId):    
    print('[get_answer_using_RAG]')
    reference = ""
    if rag_method == 'RetrievalQA': # RetrievalQA
        revised_question = get_revised_question(connectionId, requestId, text) 
        print('revised_question: ', revised_question)
        PROMPT = get_prompt_template(revised_question, convType)

        retriever = kendraRetriever

        qa = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": PROMPT}
        )
        isTyping(connectionId, requestId) 
        result = qa({"query": revised_question})    
        print('result: ', result)
        msg = result['result']

        source_documents = result['source_documents']
        print('source_documents: ', source_documents)

        if len(source_documents)>=1 and enableReference=='true':
            reference = get_reference(source_documents, rag_method)    

    elif rag_method == 'ConversationalRetrievalChain': # ConversationalRetrievalChain
        PROMPT = get_prompt_template(text, convType)
        qa = create_ConversationalRetrievalChain(PROMPT, retriever=kendraRetriever)            

        result = qa({"question": text})
        
        msg = result['answer']
        print('\nquestion: ', result['question'])    
        print('answer: ', result['answer'])    
        print('source_documents: ', result['source_documents']) 

        if len(result['source_documents'])>=1 and enableReference=='true':
            reference = get_reference(result['source_documents'], rag_method)
    
    elif rag_method == 'RetrievalPrompt': # RetrievalPrompt
        # revised_question = get_revised_question(connectionId, requestId, text) # generate new prompt using chat history
        revised_question = text # 임시 수정
        print('revised_question: ', revised_question)      

        relevant_docs = retrieve_from_Kendra(query=revised_question, top_k=top_k)
        print('relevant_docs: ', json.dumps(relevant_docs))
        
        if len(relevant_docs) == 0:
            print('No relevant document! So use naver api')
            relevant_docs = retrieve_from_naver_search_api(revised_question)

        relevant_context = ""
        for document in relevant_docs:
            relevant_context = relevant_context + document['metadata']['excerpt'] + "\n\n"
        print('relevant_context: ', relevant_context)

        PROMPT = get_prompt_template(revised_question, convType)
        #print('PROMPT: ', PROMPT)
        try: 
            isTyping(connectionId, requestId) 
            stream = llm(PROMPT.format(context=relevant_context, question=revised_question))
            msg = stream
        except Exception:
            err_msg = traceback.format_exc()
            print('error message: ', err_msg)       
            raise Exception ("Not able to request to LLM")    

        if len(relevant_docs)>=1 and enableReference=='true':
            reference = get_reference(relevant_docs, rag_method)

    memory_chain.chat_memory.add_user_message(text)  
    memory_chain.chat_memory.add_ai_message(msg)
    
    return msg, reference
    
def remove_html_tags(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)    
    
# 네이버 검색 API
def retrieve_from_naver_search_api(query):
    naver_client_id = os.environ.get('naver_client_id')
    naver_client_secret = os.environ.get('naver_client_secret')
    
    encText = urllib.parse.quote(query)
    url = "https://openapi.naver.com/v1/search/blog.json?query=" + encText
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", naver_client_id)
    request.add_header("X-Naver-Client-Secret", naver_client_secret)
    
    relevant_docs = []
    
    try:
        response = urllib.request.urlopen(request)
        
        rescode = response.getcode()
        if(rescode==200):
            response_body = response.read()
            result = json.loads(response_body.decode('utf-8'))
            print(result)
            if "items" in result:
                print('testing...')
                for item in result['items']:
                    
                    # test
                    print(item)
                    
                    doc_info = {
                        "rag_type": 'search',
                        "api_type": "naver api",
                        "confidence": "",
                        "metadata": {
                            "source": item.get('bloggerlink', ''),
                            "title": remove_html_tags(item.get('title', '')),
                            "excerpt": remove_html_tags(item.get('description', '')),
                            "translated_excerpt": "",
                        },
                        "assessed_score": "",
                    }
                    relevant_docs.append(doc_info)
            else:
                print("No 'items' found in the API response")
        else:
            print(f"Error: Naver API returned status code {rescode}")
    except Exception as e:
        print(f"Error in retrieve_from_naver_search_api: {str(e)}")
    
    return relevant_docs
    
def get_revised_question(connectionId, requestId, query):    
    print('[get_revised_question]')
    # check korean
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(query))
    print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        condense_template = """
        <history>
        {chat_history}
        </history>

        Human: <history>를 참조하여, 다음의 <question>의 뜻을 명확히 하는 새로운 질문을 한국어로 생성하세요. 새로운 질문은 원래 질문의 중요한 단어를 반드시 포함합니다.

        <question>            
        {question}
        </question>
            
        Assistant: 새로운 질문:"""
    else: 
        condense_template = """
        <history>
        {chat_history}
        </history>
        Answer only with the new question.

        Human: using <history>, rephrase the follow up <question> to be a standalone question. The standalone question must have main words of the original question.
         
        <quesion>
        {question}
        </question>

        Assistant: Standalone question:"""

    print('condense_template: ', condense_template)

    condense_prompt_claude = PromptTemplate.from_template(condense_template)
        
    condense_prompt_chain = LLMChain(llm=llm, prompt=condense_prompt_claude)

    chat_history = extract_chat_history_from_memory()
    try:         
        revised_question = condense_prompt_chain.run({"chat_history": chat_history, "question": query})

        print('revised_question: '+revised_question)

    except Exception:
        err_msg = traceback.format_exc()
        print('error message: ', err_msg)                     
        raise Exception ("Not able to request to LLM")    
    
    return revised_question
    
_ROLE_MAP = {"human": "\n\nHuman: ", "ai": "\n\nAssistant: "}
def extract_chat_history_from_memory():
    print('[extract_chat_history_from_memory]')
    chat_history = []
    chats = memory_chain.load_memory_variables({})    
    # print('chats: ', chats)

    for dialogue_turn in chats['chat_history']:
        role_prefix = _ROLE_MAP.get(dialogue_turn.type, f"{dialogue_turn.type}: ")
        history = f"{role_prefix[2:]}{dialogue_turn.content}"
        if len(history)>MSG_LENGTH:
            chat_history.append(history[:MSG_LENGTH])
        else:
            chat_history.append(history)

    return chat_history

def getAllowTime():
    d = datetime.datetime.now() - datetime.timedelta(days = 2)
    timeStr = str(d)[0:19]
    print('allow time: ',timeStr)

    return timeStr
    
def save_text_into_db(userId, requestId, requestTime, type, body, msg):
    
    print('save_text_into_db')
    
    item = {
        'user_id': {'S':userId},
        'request_id': {'S':requestId},
        'request_time': {'S':requestTime},
        'type': {'S':type},
        'body': {'S':body},
        'msg': {'S':msg}
    }
    
    dynamodb_client = boto3.client('dynamodb')
    try:
        resp =  dynamodb_client.put_item(TableName=callLogTableName, Item=item)
    except Exception:
        err_msg = traceback.format_exc()
        print('error message: ', err_msg)
        raise Exception ("Not able to write into dynamodb")   
        
def extract_relevant_doc_for_kendra(query_id, apiType, query_result):
    print('[extract_relevant_doc_for_kendra]')
    rag_type = "kendra"
    if(apiType == "retrieve"): # retrieve API
        excerpt = query_result["Content"] # 발췌문
        confidence = query_result["ScoreAttributes"]['ScoreConfidence']
        document_id = query_result["DocumentId"] 
        document_title = query_result["DocumentTitle"]
        
        document_uri = ""
        document_attributes = query_result["DocumentAttributes"]
        for attribute in document_attributes:
            if attribute["Key"] == "_source_uri":
                document_uri = str(attribute["Value"]["StringValue"])        
        if document_uri=="":  
            document_uri = query_result["DocumentURI"]
            
        doc_info = {
            "rag_type": rag_type,
            "api_type": apiType,
            "confidence": confidence,
            "metadata": {
                "document_id": document_id,
                "source": document_uri,
                "title": document_title,
                "excerpt": excerpt,
            },
        }
        
    else: # query API
        query_result_type = query_result["Type"]
        confidence = query_result["ScoreAttributes"]['ScoreConfidence']
        document_id = query_result["DocumentId"] 
        document_title = ""
        if "Text" in query_result["DocumentTitle"]:
            document_title = query_result["DocumentTitle"]["Text"]
        document_uri = query_result["DocumentURI"]
        feedback_token = query_result["FeedbackToken"] 

        page = ""
        document_attributes = query_result["DocumentAttributes"]
        for attribute in document_attributes:
            if attribute["Key"] == "_excerpt_page_number":
                page = str(attribute["Value"]["LongValue"])

        if query_result_type == "QUESTION_ANSWER":
            question_text = ""
            additional_attributes = query_result["AdditionalAttributes"]
            for attribute in additional_attributes:
                if attribute["Key"] == "QuestionText":
                    question_text = str(attribute["Value"]["TextWithHighlightsValue"]["Text"])
            answer = query_result["DocumentExcerpt"]["Text"]
            excerpt = f"{question_text} {answer}"
            excerpt = excerpt.replace("\n"," ") 
        else: 
            excerpt = query_result["DocumentExcerpt"]["Text"]

        if page:
            doc_info = {
                "rag_type": rag_type,
                "api_type": apiType,
                "confidence": confidence,
                "metadata": {
                    "type": query_result_type,
                    "document_id": document_id,
                    "source": document_uri,
                    "title": document_title,
                    "excerpt": excerpt,
                    "document_attributes": {
                        "_excerpt_page_number": page
                    }
                },
                "query_id": query_id,
                "feedback_token": feedback_token
            }
        else: 
            doc_info = {
                "rag_type": rag_type,
                "api_type": apiType,
                "confidence": confidence,
                "metadata": {
                    "type": query_result_type,
                    "document_id": document_id,
                    "source": document_uri,
                    "title": document_title,
                    "excerpt": excerpt,
                },
                "query_id": query_id,
                "feedback_token": feedback_token
            }
    return doc_info
    
def retrieve_from_Kendra(query, top_k):
    print('[retrieve_from_Kendra]')
    print('query: ', query)
    
    index_id = kendraIndex
    
    kendra_client = boto3.client(
        service_name='kendra', 
        region_name=kendra_region,
        config = Config(
            retries=dict(
                max_attempts=10
            )
        )
    )
    
    try:
        resp =  kendra_client.retrieve(
            IndexId = index_id,
            QueryText = query,
            PageSize = top_k,      
            AttributeFilter = {
                "EqualsTo": {      
                    "Key": "_language_code",
                    "Value": {
                        "StringValue": "ko"
                    }
                },
            },      
        )
        print('resp: ', resp)
        query_id = resp["QueryId"]
        
        if len(resp["ResultItems"]) >= 1:
            relevant_docs = []
            retrieve_docs = []
            for query_result in resp["ResultItems"]:
                confidence = query_result["ScoreAttributes"]['ScoreConfidence']
                retrieve_docs.append(extract_relevant_doc_for_kendra(query_id = query_id, apiType = "retrieve", query_result = query_result))
                
            print('Looking for FAQ...')
            try:
                resp =  kendra_client.query(
                    IndexId = index_id,
                    QueryText = query,
                    PageSize = 1, 
                    QueryResultTypeFilter = "QUESTION_ANSWER",  # 'QUESTION_ANSWER', 'ANSWER', "DOCUMENT"
                    AttributeFilter = {
                        "EqualsTo": {      
                            "Key": "_language_code",
                            "Value": {
                                "StringValue": "ko"
                            }
                        },
                    },      
                )
                    
                print('query resp:', json.dumps(resp))
                query_id = resp["QueryId"]
                    
                if len(resp["ResultItems"]) >= 1:
                        
                    for query_result in resp["ResultItems"]:
                        confidence = query_result["ScoreAttributes"]['ScoreConfidence']
    
                        if confidence == 'VERY_HIGH' or confidence == 'HIGH' or confidence == 'NOT_AVAILABLE': 
                            relevant_docs.append(extract_relevant_doc_for_kendra(query_id=query_id, apiType="query", query_result=query_result))
    
                            if len(relevant_docs) >= top_k:
                                break
                else:
                    print('No result for FAQ')
            
            except Exception:
                err_msg = traceback.format_exc()
                print('error message: ', err_msg)
                raise Exception ("Not able to query from Kendra")                

            for doc in retrieve_docs:                
                if len(relevant_docs) >= top_k:
                    break
                else:
                    relevant_docs.append(doc)        
            
        else:
            print('No result for Retrieve API!')
            try:
                resp =  kendra_client.query(
                    IndexId = index_id,
                    QueryText = query,
                    PageSize = top_k,
                    AttributeFilter = {
                        "EqualsTo": {      
                            "Key": "_language_code",
                            "Value": {
                                "StringValue": "ko"
                            }
                        },
                    },      
                )
                print('query resp:', resp)
                query_id = resp["QueryId"]
                
                if len(resp["ResultItems"]) >= 1:
                    relevant_docs = []
                    for query_result in resp["ResultItems"]:
                        confidence = query_result["ScoreAttributes"]['ScoreConfidence']

                        if confidence == 'VERY_HIGH' or confidence == 'HIGH' or confidence == 'MEDIUM' or confidence == 'NOT_AVAILABLE': 
                            relevant_docs.append(extract_relevant_doc_for_kendra(query_id=query_id, apiType="query", query_result=query_result))

                            if len(relevant_docs) >= top_k:
                                break

                else: 
                    print('No result for Query API. Finally, no relevant docs!')
                    relevant_docs = []

            except Exception:
                err_msg = traceback.format_exc()
                print('error message: ', err_msg)
                raise Exception ("Not able to query from Kendra")
                
    except Exception:
        err_msg = traceback.format_exc()
        print('error message: ', err_msg)        
        raise Exception ("Not able to retrieve from Kendra")     

    for i, rel_doc in enumerate(relevant_docs):
        print(f'## Document {i+1}: {json.dumps(rel_doc)}')  

    if len(relevant_docs) >= 1:
        return check_confidence(query, relevant_docs)
    else:
        return relevant_docs

def check_confidence(query, relevant_docs):
    print('[check_confidence]')
    docs = []
    for doc in relevant_docs:
        confidence = doc['confidence']
        if confidence in ['VERY_HIGH', 'HIGH', 'MEDIUM', 'NOT_AVAILABLE']:
            docs.append(doc)
        
        if len(docs) >= top_k:
            break

    return docs
    
def get_reference(docs, rag_method):
    print('[get_reference]')
    if rag_method == 'RetrievalQA' or rag_method == 'ConversationalRetrievalChain':
        reference = "\n\nFrom\n"
        for i, doc in enumerate(docs):
            name = doc.metadata['title']     

            uri = ""
            if ("document_attributes" in doc.metadata) and ("_source_uri" in doc.metadata['document_attributes']):
                uri = doc.metadata['document_attributes']['_source_uri']
                                    
            if ("document_attributes" in doc.metadata) and ("_excerpt_page_number" in doc.metadata['document_attributes']):
                page = doc.metadata['document_attributes']['_excerpt_page_number']
                reference = reference + f'{i+1}. {name}\n'
            else:
                reference = reference + f'{i+1}. {name}\n'

    elif rag_method == 'RetrievalPrompt':
        reference = "\n\nFrom\n"
        
        unique_titles = set()
        for i, doc in enumerate(docs):
            if 'metadata' in doc and 'title' in doc['metadata'] and doc['metadata']['title'] != '':
                unique_titles.add(doc['metadata']['title'])

        for index, name in enumerate(unique_titles, start=1):
            reference = reference + f"{index}. {name}\n"
        
        # for i, doc in enumerate(docs):
        #     print('doc: ', doc)
        #     # if doc['metadata']['translated_excerpt']:
        #     #     excerpt = str(doc['metadata']['excerpt']+'  [번역]'+doc['metadata']['translated_excerpt']).replace('"'," ") 
        #     # else:
        #     excerpt = str(doc['metadata']['excerpt']).replace('"'," ")
            
        #     if doc['rag_type'] == 'kendra':
                
        #         if doc['api_type'] == 'retrieve': # Retrieve. socre of confidence is only avaialbe for English
        #                 uri = doc['metadata']['source']
        #                 name = doc['metadata']['title']
        #                 reference = reference + f"{i+1}. {name}\n"
        #         else: # Query
        #             confidence = doc['confidence']
        #             if ("type" in doc['metadata']) and (doc['metadata']['type'] == "QUESTION_ANSWER"):
        #                 excerpt = str(doc['metadata']['excerpt']).replace('"'," ") 
        #                 reference = reference + f"{i+1}. <a href=\"#\" onClick=\"alert(`{excerpt}`)\">FAQ ({confidence})</a>\n"
        #             else:
        #                 uri = ""
        #                 if "title" in doc['metadata']:
        #                     #print('metadata: ', json.dumps(doc['metadata']))
        #                     name = doc['metadata']['title']
        #                     if name: 
        #                         uri = path+parse.quote(name)
    
        #                 page = ""
        #                 if "document_attributes" in doc['metadata']:
        #                     if "_excerpt_page_number" in doc['metadata']['document_attributes']:
        #                         page = doc['metadata']['document_attributes']['_excerpt_page_number']
                                                    
        #                 if page: 
        #                     reference = reference + f"{i+1}. {name}\n"
        #                 elif uri:
        #                     reference = reference + f"{i+1}. {name}\n"
        
        #     elif doc['rag_type'] == 'search':
        #         print(f'## Document(get_reference) {i+1}: {doc}')
                
        #         uri = doc['metadata']['source']
        #         name = doc['metadata']['title']
        #         reference = reference + f"{i+1}. {uri} "
        
    return reference
    
def create_ConversationalRetrievalChain(PROMPT, retriever):  
    print('[create_ConversationalRetrievalChain]')
    condense_template = """
        <history>
        {chat_history}
        </history>
        Answer only with the new question.

        Human: using <history>, rephrase the follow up <question> to be a standalone question.
         
        <quesion>
        {question}
        </question>

        Assistant: Standalone question:"""
    CONDENSE_QUESTION_PROMPT = PromptTemplate.from_template(condense_template)
        
    qa = ConversationalRetrievalChain.from_llm(
        llm=llm, 
        retriever=retriever,
        condense_question_prompt=CONDENSE_QUESTION_PROMPT, 
        combine_docs_chain_kwargs={'prompt': PROMPT},

        memory=memory_chain,
        get_chat_history=_get_chat_history,
        verbose=False, 
        
        chain_type='stuff',
        rephrase_question=True,  
        return_source_documents=True, 
        return_generated_question=False, 
    )

    return qa

def lambda_handler(event, context):
    
    if event['requestContext']: 
        connectionId = event['requestContext']['connectionId']
        routeKey = event['requestContext']['routeKey']

        if routeKey == '$connect':
            print('connected!')
        elif routeKey == '$disconnect':
            print('disconnected!')
        else:   # $default
            jsonBody = json.loads(event.get("body", ""))
            print(jsonBody)
            
            text = jsonBody['body']
            requestId  = jsonBody['request_id']
            userId = jsonBody['user_id']
            requestTime = jsonBody['request_time']
            type = jsonBody['type']
            body = jsonBody['body']
            
            try:
                msg, reference = getResponse(connectionId, jsonBody)
                print('msg+reference: ', msg+reference)
            except Exception:
                err_msg = traceback.format_exc()
                print('err_msg: ', err_msg)
                raise Exception ("Not able to send a message")
                                
            readStreamMsg(connectionId, requestId, msg+reference)        
            
            save_text_into_db(userId, requestId, requestTime, type, body, msg+reference)
    
    return {
        'statusCode': 200
    }
            