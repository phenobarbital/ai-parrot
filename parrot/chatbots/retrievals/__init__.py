from collections.abc import Callable
from typing import Any
import uuid
import asyncio
from aiohttp import web
from sentence_transformers import SentenceTransformer, util
from langchain.memory import (
    ConversationSummaryMemory,
    ConversationBufferMemory
)
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.chains.conversational_retrieval.base import (
    ConversationalRetrievalChain
)
from langchain.retrievers import (
    EnsembleRetriever,
    ContextualCompressionRetriever
)
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_core.prompts import (
    PromptTemplate,
    ChatPromptTemplate
)
from langchain_community.retrievers import BM25Retriever
from datamodel.exceptions import ValidationError  # pylint: disable=E0611
from asyncdb import AsyncDB
from navconfig.logging import logging
from navigator_session import get_session
from parrot.conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
    BIGQUERY_DATASET
)
try:
    from ...llms import VertexLLM
    VERTEX_ENABLED = True
except ImportError:
    VERTEX_ENABLED = False

try:
    from ...llms import Anthropic
    ANTHROPIC_ENABLED = True
except ImportError:
    ANTHROPIC_ENABLED = False

from ...utils import SafeDict
from ...models import ChatResponse, ChatbotUsage


class RetrievalManager:
    """Managing the Chain Retrieval, answers and sources.
    """
    def __init__(
        self,
        chatbot_id: uuid.UUID,
        chatbot_name: str,
        model: Callable,
        store: Callable,
        memory: ConversationBufferMemory = None,
        template: str = None,
        source_path: str = 'web',
        request: web.Request = None,
        kb: Any = None
    ):
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = chatbot_id
        # Chatbot Name:
        self.chatbot_name: str = chatbot_name
        # Source Path:
        self.source_path: str = source_path
        # Vector Store
        self.store = store
        # Memory Manager
        self.memory = memory
        # LLM Model
        self.model = model
        # template prompt
        # TODO: if none, create a basic template
        self.template = template
        # Knowledge-base
        self.kb = kb
        # Logger:
        self.logger = logging.getLogger('Parrot.Retrieval')
        # Web Request:
        self.request = request

    def __enter__(self):
        self.client_id: str = str(uuid.uuid4())
        self.client, _ = self.store.connect(alias=self.client_id)
        return self

    async def __aenter__(self):
        self.client_id: str = str(uuid.uuid4())
        self.client, _ = self.store.connect(alias=self.client_id)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.client.close()  # closing database connection
        # closing the connection:
        self.store.close(alias=self.client_id)
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()  # closing database connection
        # closing the connection:
        self.store.close(alias=self.client_id)
        pass

    def create_memory(
        self,
        key: str = 'chat_history',
        input_key: str = 'question',
        output_key: str = 'answer'
    ):
        return ConversationBufferMemory(
            memory_key=key,
            return_messages=True,
            input_key=input_key,
            output_key=output_key
        )

    ### Different types of Retrieval
    def conversation(
        self,
        question: str = None,
        chain_type: str = 'stuff',
        search_type: str = 'similarity',
        search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
        return_docs: bool = True,
        metric_type: str = None,
        memory: Any = None,
        use_llm: str = None,
        **kwargs
    ):
        # Question:
        self._question = question
        # Memory:
        self.memory = memory
        # Get a Vector Retriever:
        vector = self.store.get_vector(
            metric_type=metric_type
        )
        simil_retriever = VectorStoreRetriever(
            vectorstore=vector,
            search_type='similarity',
            chain_type=chain_type,
            search_kwargs=search_kwargs
        )
        retriever = vector.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )
        if self.kb:
            # Get a BM25 Retriever:
            b25_retriever = BM25Retriever.from_documents(self.kb)
            retriever = EnsembleRetriever(
                retrievers=[simil_retriever, retriever, b25_retriever],
                weights=[0.6, 0.3, 0.1]
            )
        else:
            retriever = EnsembleRetriever(
                retrievers=[simil_retriever, retriever],
                weights=[0.7, 0.3]
            )
        custom_template = self.template.format_map(
            SafeDict(
                summaries=''
            )
        )
        _prompt = PromptTemplate(
            template=custom_template,
            input_variables=["context", "chat_history", "question"],
        )
        if use_llm is not None:
            if use_llm == 'claude':
                if ANTHROPIC_ENABLED is True:
                    llm = Anthropic(
                        model='claude-3-opus-20240229',
                        temperature=0.2,
                        top_p=0.4,
                        top_k=20
                    )
                else:
                    raise ValueError(
                        "No Anthropic Claude was installed."
                    )
            elif use_llm == 'vertex':
                if VERTEX_ENABLED is True:
                    llm = VertexLLM(
                        model='gemini-pro',
                        temperature=0.2,
                        top_p=0.4,
                        top_k=20
                    )
                else:
                    raise ValueError(
                        "No VertexAI was installed."
                    )
            else:
                raise ValueError(
                    f"Only Claude and Vertex are Supported Now."
                )
            _model = llm.get_llm()
        else:
            _model = self.model
        # Conversational Chain:
        self.chain = ConversationalRetrievalChain.from_llm(
            llm=_model,
            retriever=retriever,
            chain_type=chain_type,
            verbose=True,
            memory=self.memory,
            return_source_documents=return_docs,
            return_generated_question=True,
            combine_docs_chain_kwargs={"prompt": _prompt},
        )
        return self

    def qa(
        self,
        question: str = None,
        chain_type: str = 'stuff',
        search_type: str = 'mmr',
        search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
        return_docs: bool = True,
        metric_type: str = None,
        use_llm: str = None
    ):
        # Question:
        self._question = question
        # Get a Vector Retriever:
        vector = self.store.get_vector(
            metric_type=metric_type
        )
        simil_retriever = VectorStoreRetriever(
            vectorstore=vector,
            search_type='similarity',
            chain_type=chain_type,
            search_kwargs=search_kwargs
        )
        retriever = vector.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )
        if self.kb:
            # Get a BM25 Retriever:
            b25_retriever = BM25Retriever.from_documents(self.kb)
            retriever = EnsembleRetriever(
                retrievers=[simil_retriever, retriever, b25_retriever],
                weights=[0.6, 0.3, 0.1]
            )
        else:
            retriever = EnsembleRetriever(
                retrievers=[simil_retriever, retriever],
                weights=[0.7, 0.3]
            )
            # retriever = simil_retriever
        custom_template = self.template.format_map(
            SafeDict(
                chat_history=''
            )
        )
        if use_llm is not None:
            if use_llm == 'claude':
                if ANTHROPIC_ENABLED is True:
                    llm = Anthropic(
                        model='claude-3-opus-20240229',
                        temperature=0.2,
                        top_p=0.4,
                        top_k=20
                    )
                else:
                    raise ValueError(
                        "No Anthropic Claude was installed."
                    )
            elif use_llm == 'vertex':
                if VERTEX_ENABLED is True:
                    llm = VertexLLM(
                        model='gemini-pro',
                        temperature=0.2,
                        top_p=0.4,
                        top_k=20
                    )
                else:
                    raise ValueError(
                        "No VertexAI was installed."
                    )
            else:
                raise ValueError(
                    f"Only Claude and Vertex are Supported Now."
                )
            self.model = llm.get_llm()

        self.chain = RetrievalQA.from_chain_type(
            llm=self.model,
            chain_type=chain_type,
            retriever=retriever,
            return_source_documents=return_docs,
            verbose=True,
            chain_type_kwargs={
                "prompt": PromptTemplate(
                    template=custom_template,
                    input_variables=['context', 'question']
                )
            },
        )
        # Debug Code ::
        # print('=====================')
        # print(custom_template)
        # response = self.chain.invoke(question)
        # print('Q > ', response['result'])
        # docs = vector.similarity_search(
        #     self._question, k=10
        # )
        # print(" LENGHT DOCS > ", len(docs))
        # print(docs)
        # print(' ========================== ')

        # try:
        #     distance = self.evaluate_distance(
        #         self.store.embedding_name, question, docs
        #     )
        #     print('DISTANCE > ', distance)
        # except Exception as e:
        #     distance = 'EMPTY'
        # print('DISTANCE > ', distance)
        # print('CHAIN > ', self.chain)

        return self

    def get_current_context(self):
        if self.memory:
            return self.memory.buffer_as_str()
        return None

    def as_markdown(self, response: ChatResponse) -> str:
        markdown_output = f"**Question**: {response.question}  \n"
        markdown_output += f"**Answer**: {response.answer}  \n"
        if response.source_documents:
            source_documents = response.source_documents
            current_sources = []
            block_sources = []
            count = 0
            d = {}
            for source in source_documents:
                if count >= 20:
                    break  # Exit loop after processing 10 documents
                metadata = source.metadata
                if 'url' in metadata:
                    src = metadata.get('url')
                elif 'filename' in metadata:
                    src = metadata.get('filename')
                else:
                    src = metadata.get('source', 'unknown')
                if src == 'knowledge-base':
                    continue  # avoid attaching kb documents
                source_title = metadata.get('title', src)
                if source_title in current_sources:
                    continue
                current_sources.append(source_title)
                if src:
                    d[src] = metadata.get('document_meta', {})
                source_filename = metadata.get('filename', src)
                if src:
                    block_sources.append(f"- [{source_title}]({src})")
                else:
                    if 'page_number' in metadata:
                        block_sources.append(f"- {source_filename} (Page {metadata.get('page_number')})")
                    else:
                        block_sources.append(f"- {source_filename}")
            if block_sources:
                markdown_output += f"**Sources**:  \n"
                markdown_output += "\n".join(block_sources)
            if d:
                response.documents = d
        return markdown_output

    def evaluate_distance(self, model, question, source_documents):
        tokenizer = SentenceTransformer(model)
        query_embedding = tokenizer.encode(question)
        document_embeddings = [
            tokenizer.encode(doc.page_content) for doc in source_documents
        ]
        distances = util.cos_sim(query_embedding, document_embeddings)
        result = []
        for doc, distance in zip(source_documents, distances):
            result.append({
                "document": doc,
                "distance": distance
            })
        return result

    async def log_usage(self, response: ChatResponse, request: web.Request = None):
        PARAMS = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        db = AsyncDB(
            'bigquery',
            params=PARAMS
        )
        origin = {
            "user_agent": 'script'
        }
        user_id = 0
        if request:
            origin = {
                "origin": request.remote,
                "user_agent": request.headers.get('User-Agent')
            }
            session = await get_session(request)
            if session:
                user_id = session.user_id
        async with await db.connection() as conn:  #pylint: disable=E1101
            # set connection to model:
            ChatbotUsage.Meta.connection = conn
            # Add a new record of chatbot usage:
            record = {
                "chatbot_id": str(self.chatbot_id),
                "user_id": user_id,  # TODO: add session informtion
                "source_path": self.source_path,
                "platform": 'web',
                "sid": str(response.sid),
                "used_at": response.at,
                "question": response.question,
                "response": response.answer,
                **origin
            }
            try:
                log = ChatbotUsage(**record)
                data = log.to_dict()
                # convert to string (bigquery uses json.dumps to convert to string)
                data['sid'] = str(data['sid'])
                data['chatbot_id'] = str(data['chatbot_id'])
                data['event_timestamp'] = str(data['event_timestamp'])
                # writing directly to bigquery
                await conn.write(
                    [data],
                    table_id=ChatbotUsage.Meta.name,
                    dataset_id=ChatbotUsage.Meta.schema,
                    use_streams=False,
                    use_pandas=False
                )
                # await log.insert()
            except Exception as exc:
                self.logger.error(
                    f"Error inserting log: {exc}"
                )


    async def question(
            self,
            question: str = None,
            chain_type: str = 'stuff',
            search_type: str = 'similarity',
            search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
            return_docs: bool = True,
            metric_type: str = None,
            memory: Any = None,
            **kwargs
    ):
        # Generating Vector:
        async with self.store.connection() as store:  #pylint: disable=E1101
            vector = store.get_vector(metric_type=metric_type)
            retriever = VectorStoreRetriever(
                vectorstore=vector,
                search_type=search_type,
                chain_type=chain_type,
                search_kwargs=search_kwargs
            )
            custom_template = self.template.format_map(
                SafeDict(
                    summaries=''
                )
            )
            _prompt = PromptTemplate(
                template=custom_template,
                input_variables=["context", "chat_history", "question"],
            )
            try:
                chain = ConversationalRetrievalChain.from_llm(
                    llm=self.model,
                    retriever=retriever,
                    chain_type=chain_type,
                    verbose=False,
                    memory=memory,
                    return_source_documents=return_docs,
                    return_generated_question=True,
                    combine_docs_chain_kwargs={"prompt": _prompt},
                    **kwargs
                )
                response = chain.invoke(
                    question
                )
            except Exception as exc:
                self.logger.error(
                    f"Error invoking chain: {exc}"
                )
                return None, None
            try:
                qa_response = ChatResponse(**response)
            except (ValueError, TypeError) as exc:
                self.logger.error(
                    f"Error validating response: {exc}"
                )
                return None, None
            except ValidationError as exc:
                self.logger.error(
                    f"Error on response: {exc.payload}"
                )
                return None, None
        try:
            qa_response.response = self.as_markdown(
                qa_response
            )
            # saving question to Usage Log
            if self.request:
                tasker = self.request.app['service_queue']
                await tasker.put(
                    self.log_usage,
                    response=qa_response,
                    request=self.request
                )
            else:
                asyncio.create_task(
                    self.log_usage(response=qa_response)
                )
            return qa_response
        except Exception as exc:
            self.logger.exception(
                f"Error on response: {exc}"
            )
            return None


    async def invoke(self, question):
        # Invoke the chain with the given question
        try:
            response = self.chain.invoke(
                question
            )
        except Exception as exc:
            self.logger.error(
                f"Error invoking chain: {exc}"
            )
            return None, None
        try:
            qa_response = ChatResponse(**response)
        except (ValueError, TypeError) as exc:
            self.logger.error(
                f"Error validating response: {exc}"
            )
            return None, None
        except ValidationError as exc:
            self.logger.error(
                f"Error on response: {exc.payload}"
            )
            return None, None
        try:
            qa_response.response = self.as_markdown(
                qa_response
            )
            # saving question to Usage Log
            if self.request:
                tasker = self.request.app['service_queue']
                await tasker.put(
                    self.log_usage,
                    response=qa_response,
                    request=self.request
                )
            else:
                asyncio.create_task(self.log_usage(response=qa_response))
            return qa_response
        except Exception as exc:
            self.logger.exception(
                f"Error on response: {exc}"
            )
            return None, None
