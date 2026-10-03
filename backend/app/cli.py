"""Interactive command-line chat. Prefix a question with `doc:` to answer from indexed files.
Run from the backend folder with `python -m app.cli` (add `--debug` to print prompts and tool calls).
"""

import sys

from app.services.chat_service import get_answer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conversation_id = None  # the first answer starts a conversation
print("Local AI Assistant - type 'exit' to quit")
print("Prefix a question with 'doc:' to search your indexed files.\n")

while True:
    user_input = input("You: ").strip()
    if user_input.lower() == "exit":
        print("Exiting. Goodbye!")
        break

    if not user_input:
        print("Please enter a question or type exit to quit.")
        continue

    use_docs = user_input.lower().startswith("doc:")
    query = user_input[4:].strip() if use_docs else user_input

    reply = get_answer(query, use_docs=use_docs, conversation_id=conversation_id)
    conversation_id = reply["conversation_id"]
    answer, sources, used_tools = reply["response"], reply["sources"], reply["used_tools"]

    prefix = "🔧" if used_tools else "💬"
    print(f"\n{prefix} Assistant: {answer}")
    if sources:
        print(f"Sources: {', '.join(sorted(set(sources)))}")
    print()
