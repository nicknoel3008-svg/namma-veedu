"""Explicit customer feedback saved for owner review, never automatic approval."""
from storage_backend import _redact

CATEGORIES = ("Incorrect answer", "Misunderstood my request", "Difficult to use", "Suggestion", "Other")
FEEDBACK_HEADERS = ("Feedback ID", "Conversation ID", "User ID", "Timestamp (Asia/Kolkata)",
                    "Language", "Feedback category", "Feedback comment", "Feedback related Mira response")


def feedback_record(*, feedback_id, conversation_id, user_id, category, comment, language, timestamp, chat):
    comment = comment.strip()
    if category not in CATEGORIES:
        raise ValueError("Choose a feedback category.")
    if category in {"Suggestion", "Other"} and not comment:
        raise ValueError("Please add a comment for this feedback category.")
    if len(comment) > 2000:
        raise ValueError("Please keep your feedback within 2,000 characters.")
    related = next((item.get("content", "") for item in reversed(chat)
                    if item.get("role") == "assistant" and item.get("mode") != "welcome"), "")
    return _redact({"Inquiry ID": feedback_id, "Feedback ID": feedback_id,
                   "Conversation ID": conversation_id, "User ID": user_id,
                   "Timestamp (Asia/Kolkata)": timestamp, "Language": language,
                   "Response type": "customer_feedback", "Conversation topic": "Customer feedback",
                   "User inquiry": f"[Feedback: {category}] {comment}", "Assistant response": "",
                   "Feedback category": category, "Feedback comment": comment,
                   "Feedback related Mira response": related,
                   "Recent conversation context": "\n".join(f"{item.get('role')}: {item.get('content', '')}" for item in chat[-6:])})


def feedback_drafts(rows):
    guidance = {
        "Incorrect answer": "Verify the relevant saved facts before answering. Correct mistakes clearly and state missing evidence instead of guessing.",
        "Misunderstood my request": "Restate the customer's actual request briefly, preserve their stated constraints, and answer that request before suggesting another action.",
        "Difficult to use": "Give concise, actionable steps using the actual website control names. Complete actions supported in chat instead of redirecting unnecessarily.",
        "Suggestion": "Owner: review the linked customer suggestion and replace this draft with specific, safe guidance before approving.",
        "Other": "Owner: review the linked customer feedback and write an actionable improvement before approving.",
    }
    return [{"Rule ID": "feedback-" + str(row["Feedback ID"]),
             "Scenario": "Customer feedback: " + str(row.get("Feedback category", "Other")),
             "Guidance": guidance.get(row.get("Feedback category"), guidance["Other"]),
             "Status": "Draft", "Source": "Customer feedback " + str(row["Feedback ID"])}
            for row in rows if row.get("Feedback ID")]
