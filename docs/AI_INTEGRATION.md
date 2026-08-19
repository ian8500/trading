# Optional structured AI analysis

AI is disabled by default and is not required for any deterministic strategy or backtest. To opt in, configure a server-side `OPENAI_API_KEY`, an explicit `AI_MODEL`, and `AI_PROVIDER=openai` locally. The key is never returned to the browser.

The adapter uses the OpenAI Responses API with `text.format.type=json_schema`, strict schema adherence, no tools, `store=false`, bounded untrusted-news fields, and a second Pydantic validation layer. This follows the current [official OpenAI Responses API reference](https://developers.openai.com/api/reference/java/resources/beta/subresources/responses). It stores provider/model/schema/prompt versions, timestamps, validation status and token counts, but not hidden reasoning.

AI can classify or explain an event. It cannot submit an order, call a tool, modify a stop, change leverage, enable Demo/Live, alter hard limits or promote a strategy. Invalid/unavailable responses make AI-dependent analysis inactive; the quantitative baseline continues.

