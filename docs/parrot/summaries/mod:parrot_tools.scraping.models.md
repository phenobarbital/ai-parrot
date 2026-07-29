---
type: Wiki Summary
title: parrot_tools.scraping.models
id: mod:parrot_tools.scraping.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Browser Action System for AI-Parrot WebScrapingTool
relates_to:
- concept: class:parrot_tools.scraping.models.Authenticate
  rel: defines
- concept: class:parrot_tools.scraping.models.AwaitBrowserEvent
  rel: defines
- concept: class:parrot_tools.scraping.models.AwaitHuman
  rel: defines
- concept: class:parrot_tools.scraping.models.AwaitKeyPress
  rel: defines
- concept: class:parrot_tools.scraping.models.Back
  rel: defines
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: defines
- concept: class:parrot_tools.scraping.models.Click
  rel: defines
- concept: class:parrot_tools.scraping.models.Conditional
  rel: defines
- concept: class:parrot_tools.scraping.models.Evaluate
  rel: defines
- concept: class:parrot_tools.scraping.models.Extract
  rel: defines
- concept: class:parrot_tools.scraping.models.ExtractJsonLd
  rel: defines
- concept: class:parrot_tools.scraping.models.FieldSpec
  rel: defines
- concept: class:parrot_tools.scraping.models.Fill
  rel: defines
- concept: class:parrot_tools.scraping.models.GetCookies
  rel: defines
- concept: class:parrot_tools.scraping.models.GetHTML
  rel: defines
- concept: class:parrot_tools.scraping.models.GetText
  rel: defines
- concept: class:parrot_tools.scraping.models.Hover
  rel: defines
- concept: class:parrot_tools.scraping.models.Loop
  rel: defines
- concept: class:parrot_tools.scraping.models.Navigate
  rel: defines
- concept: class:parrot_tools.scraping.models.PressKey
  rel: defines
- concept: class:parrot_tools.scraping.models.Refresh
  rel: defines
- concept: class:parrot_tools.scraping.models.ScrapingResult
  rel: defines
- concept: class:parrot_tools.scraping.models.ScrapingSelector
  rel: defines
- concept: class:parrot_tools.scraping.models.ScrapingStep
  rel: defines
- concept: class:parrot_tools.scraping.models.Screenshot
  rel: defines
- concept: class:parrot_tools.scraping.models.Scroll
  rel: defines
- concept: class:parrot_tools.scraping.models.Select
  rel: defines
- concept: class:parrot_tools.scraping.models.SetCookies
  rel: defines
- concept: class:parrot_tools.scraping.models.Submit
  rel: defines
- concept: class:parrot_tools.scraping.models.Type
  rel: defines
- concept: class:parrot_tools.scraping.models.UploadFile
  rel: defines
- concept: class:parrot_tools.scraping.models.Wait
  rel: defines
- concept: class:parrot_tools.scraping.models.WaitForDownload
  rel: defines
- concept: func:parrot_tools.scraping.models.create_action
  rel: defines
---

# `parrot_tools.scraping.models`

Browser Action System for AI-Parrot WebScrapingTool
Object-oriented action hierarchy for LLM-directed browser automation

## Classes

- **`BrowserAction(BaseModel, ABC)`** — Base class for all browser actions
- **`Navigate(BrowserAction)`** — Navigate to a URL
- **`Click(BrowserAction)`** — Click on a web page element
- **`Fill(BrowserAction)`** — Fill text into an input field
- **`Hover(BrowserAction)`** — Move the mouse over an area/element
- **`Type(BrowserAction)`** — Send keystrokes to the page or an element
- **`FieldSpec(BaseModel)`** — One sub-selector for a row-of-fields ``Extract`` step.
- **`Extract(BrowserAction)`** — Extract data from the page using CSS selectors or XPath.
- **`ExtractJsonLd(BrowserAction)`** — Extract structured data from JSON-LD blocks on the current page.
- **`Submit(BrowserAction)`** — Click on a submit button or submit a form
- **`Select(BrowserAction)`** — Select an option from a dropdown/select element.
- **`Evaluate(BrowserAction)`** — Execute JavaScript code in the browser context
- **`PressKey(BrowserAction)`** — Press keyboard keys
- **`Refresh(BrowserAction)`** — Reload the current web page
- **`Back(BrowserAction)`** — Navigate back to the previous page
- **`Scroll(BrowserAction)`** — Scroll the page or an element
- **`GetCookies(BrowserAction)`** — Extract and evaluate cookies
- **`SetCookies(BrowserAction)`** — Set cookies on the current page or domain
- **`Wait(BrowserAction)`** — Wait for a condition to be met.
- **`Authenticate(BrowserAction)`** — Handle authentication flows
- **`AwaitHuman(BrowserAction)`** — Pause and wait for human intervention
- **`AwaitKeyPress(BrowserAction)`** — Wait for human to press a key in console
- **`AwaitBrowserEvent(BrowserAction)`** — Wait for human interaction in the browser
- **`GetText(BrowserAction)`** — Extract pure text content from elements matching selector
- **`Screenshot(BrowserAction)`** — Take a screenshot of the page or a specific element
- **`GetHTML(BrowserAction)`** — Extract complete HTML content from elements matching selector
- **`WaitForDownload(BrowserAction)`** — Wait for a file download to complete
- **`UploadFile(BrowserAction)`** — Upload a file to a file input element
- **`Conditional(BrowserAction)`** — Execute actions conditionally based on a JavaScript expression
- **`Loop(BrowserAction)`** — Repeat a sequence of actions multiple times
- **`ScrapingStep`** — ScrapingStep that wraps a BrowserAction.
- **`ScrapingSelector`** — Defines what content to extract from a page
- **`ScrapingResult`** — Stores results from a single page scrape

## Functions

- `def create_action(action_type: str, **kwargs) -> BrowserAction` — Factory function to create actions by type name
