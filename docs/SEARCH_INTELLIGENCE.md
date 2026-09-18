# Evidence-first search and Q&A

This upgrade extends the existing application. Imports, document selection, internal groups, feedback and collapsed references remain available.

`POST /api/chat` returns answer, evidence, sources and intelligence in one response. Evidence contains retrieved excerpts; sources are citations from the answer. Query understanding detects known people and intent, authorized meeting/document metadata scopes retrieval, hybrid keyword/vector retrieval gathers candidates, and deterministic reranking uses speaker and keyword matches. Azure Search retains its semantic ranking when configured. Ambiguous first names do not select an arbitrary speaker.

Generation receives at most eight excerpts, 3,000 characters per excerpt and 18,000 evidence characters total. It does not receive a full transcript. Historical Word documents use real file/page/sheet/slide/section metadata; absent timestamps are null. The answer appears first and references expand on demand. Related intelligence is collapsible and derived from retrieved evidence; unrelated roster members and unrelated files are excluded.

External research is separate from meeting answers. It requires an explicit request such as ?Search the web for Azure Search best practices?; ordinary recaps, person questions and general recommendations do not trigger it. Configure WEB_RESEARCH_PROVIDER=azure_openai and WEB_RESEARCH_DEPLOYMENT for an Azure deployment supporting the Responses web_search tool. Existing Azure endpoint/key settings are reused. Default `none` reports unavailable honestly. Only the requested topic is sent, never retrieved transcript text. Do not put confidential content in an external research request.

The sample's retired Bing v7 adapter was not retained. See [Azure web search](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search?view=foundry-classic) and [Bing retirement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement).

The separate raw Search page remains a retrieval-only workflow for compatibility. Teams is a separate confirmed workflow; see MICROSOFT_GRAPH_PERMISSIONS.md. Validation results and limitations are recorded in audits/POST_SEARCH_TEAMS_COLLABORATION_AUDIT.md.
