import sys
from orchestrator import ask
from database import create_conversation

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conversation_id = create_conversation(title="CLI Session")
print(f"Local AI Assistant - conversation {conversation_id[:8]} - type 'exit' to quit")
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

    answer, sources, used_tools = ask(query, use_docs=use_docs, conversation_id=conversation_id)

    prefix = "🔧" if used_tools else "💬"
    print(f"\n{prefix} Assistant: {answer}")
    if sources:
        print(f"Sources: {', '.join(sorted(set(sources)))}")
    print()


