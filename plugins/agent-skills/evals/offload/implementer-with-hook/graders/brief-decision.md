---
# The decision lives only in the conversation: the implementer's brief carries it (round once) and its reason
# (invoice.py rounds each line; rounding twice drifts a cent). input_match reads the call's JSON-encoded input.
type: tool_used
tool: Agent
input_match: '^(?=.*implementer)(?=.*([Oo]nce|[Ss]ingle|[Oo]nly in|[Oo]nly inside))(?=.*(already rounds|rounds each|rounds per|per[- ]line|each line|drift|twice|double))'
---
