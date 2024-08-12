from langchain.chains.constitutional_ai.base import ConstitutionalChain
from langchain.chains.constitutional_ai.models import ConstitutionalPrinciple
from ...conf import ETHICAL_PRINCIPLE


ethical_principle = ConstitutionalPrinciple(
    name="Ethical Principle",
    critique_request=ETHICAL_PRINCIPLE,
    revision_request="Rewrite the model's output to be both ethical and legal.",
)


def get_constitutional_chain(llm, qa_chain):
    return ConstitutionalChain.from_llm(
        chain=qa_chain,
        constitutional_principles=[ethical_principle],
        llm=llm,
        verbose=True,
    )
