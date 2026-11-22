"""Conservative project hints from the source, never from invented model titles."""
import re


def project_mentions(text):
    found = set()
    if re.search(r"업무\s*비서|로켓\s*챗|rocket\.?chat", text, re.I):
        found.add("ai-assistant")
    if re.search(r"공간\s*정보|\bGIS\b", text, re.I):
        found.add("spatial-agent")
    return found


def suggest_project(raw, evidence):
    explicit = project_mentions(evidence)
    if explicit:
        return next(iter(explicit)) if len(explicit) == 1 else None
    # A single explicitly named project is a report-wide hint. Mixed-project
    # reports require task-local evidence; generic 'Agent' alone is insufficient.
    context = project_mentions(raw)
    return next(iter(context)) if len(context) == 1 else None
