import sys
from orchestrator import ask

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

    answer, sources = ask(query, use_docs=use_docs)

    print (f"Assistant: {answer}")
    if sources :
        unique_sources = sorted(set(sources))
        print(f"Sources: {chr(44).join(unique_sources)}")
    print() # Add a blank line for readability


