"""
Tools infrastructure for building Agents.
"""
# Abstract Agent interface
from .abstract import AbstractTool, AbstractToolkit
from .basic import SearchTool, MathTool
from .duck import DuckDuckGoSearchTool, DuckDuckGoRelevantSearch
from .gamma import GammaLink
from .gvoice import GoogleVoiceTool
from .msword import WordToMarkdownTool, DocxGeneratorTool
from .pdf import PDFPrintTool
from .np import PythonREPLTool

# from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool
# from langchain_community.tools import YouTubeSearchTool
# from langchain_community.agent_toolkits import O365Toolkit
# from navconfig import config
# # from .wikipedia import WikipediaTool, WikidataTool
# from .asknews import AskNewsTool

# from .weather import OpenWeather, OpenWeatherMapTool
# from .google import GoogleLocationFinder, GoogleSiteSearchTool, GoogleSearchTool
# from .zipcode import ZipcodeAPIToolkit
# from .bing import BingSearchTool
# from .stack import StackExchangeTool
