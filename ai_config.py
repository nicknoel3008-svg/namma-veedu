"""Explicit provider selection; never switch to a paid provider on failure."""

def select_ai_config(get_value):
    provider = get_value("AI_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        return provider, get_value("GROQ_API_KEY"), get_value("GROQ_MODEL", "openai/gpt-oss-20b")
    if provider == "openai":
        return provider, get_value("OPENAI_API_KEY"), get_value("OPENAI_MODEL", "gpt-5.6-luna")
    return "offline", "", ""
