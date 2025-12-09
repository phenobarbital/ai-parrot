from .huggingface import SentenceTransformerModel
from .google import GoogleEmbeddingModel
from .openai import OpenAIEmbeddingModel

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}
