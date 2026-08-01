import sys
import requests
import database
import tools
from config import CHAT_MODEL, OLLAMA_URL
from retriever import retrieve

DEBUG = "--debug" in sys.argv

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders inside a path within the user's allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace root. Use '.' for the root itself."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file within the user's allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {
                        "type": "string",
                        "description": "Current path of the file, relative to the workspace root."
                    },
                    "dst": {
                        "type": "string",
                        "description": "Destination path for the file, relative to the workspace root."
                    }
                },
                "required": ["src", "dst"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Create a new folder (including any missing parent folders) within the user's allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the folder to create, relative to the workspace root."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "organize_by_extension",
            "description": "Sort every file in a folder into subfolders named after their file extension (e.g. jpg, pdf, txt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Path of the folder to organize, relative to the workspace root. Use '.' for the root itself."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_empty_files",
            "description": "Search a folder (and its subfolders) for zero-byte empty files within the user's allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Path to search, relative to the workspace root. Use '.' for the whole workspace."
                    }
                },
                "required": []
            }
        }
    },
]

available_tools = {
    "list_files": tools.list_files,
    "move_file": tools.move_file,
    "create_folder": tools.create_folder,
    "organize_by_extension": tools.organize_by_extension,
    "find_empty_files": tools.find_empty_files,
}

def build_context(query, k=4, project=None):
    # Vector-search the ingested documents for the k chunks most relevant to the query.
    # `project` optionally pins the search to sources whose path contains that substring.
    results = retrieve(query, k, project=project)
    if DEBUG:
        print(f"\n[DEBUG] Retrieved {len(results)} chunks for query: {query!r}")
        for chunk, source in results:
            print(f"[DEBUG]   source={source}  chunk={chunk[:80]!r}...")
    if not results:
        # Nothing relevant found (e.g. empty index) -> no context to inject.
        return "", []
    labeled_chunks = []
    sources = []
    for chunk, source in results:
        # Tag each chunk with its source file so the LLM (and the caller) can cite it.
        labeled_chunks.append(f"Source: {source}\n{chunk}")
        sources.append(source)

    # Join chunks into a single block, separated so the LLM can tell them apart.
    context_block = "\n\n---\n\n".join(labeled_chunks)
    return context_block, sources

def build_prompt(query, context_block):
    if not context_block:
        # No retrieved context -> fall back to asking the raw question.
        return query
    # Wrap the retrieved context and instructions around the user's question,
    # nudging the LLM to answer from the provided sources instead of hallucinating.
    return (
        "Use the following context from the user's files to answer the question. "
        "If the context does not contain the answer, say so rather than guessing.\n\n"
        f"{context_block}\n\n"
        f"Question: {query}"
    )
def ask(query, use_docs=False, project=None, conversation_id=None):
    SYSTEM_PROMPT = (
        "You are a local assistant with access to tools for file operations: "
        "listing files, moving/renaming files, creating folders, organizing files by "
        "extension, and finding empty files. "
        "Some requests require calling more than one tool in sequence to complete — "
        "for example, first finding which files match a condition, then moving each "
        "one. Call tools directly instead of explaining how to do it manually, and "
        "keep calling tools across turns until the request is fully done. "
        "Only respond with plain text if no combination of the available tools can "
        "fulfill the request."
    )
    sources = []
    if use_docs:
        context_block, sources = build_context(query, project=project)
        prompt = build_prompt(query, context_block)
    else:
        prompt = query
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    if DEBUG:
        print(f"\n[DEBUG] Final prompt sent to model:\n{prompt[:1000]}\n")

    used_tools = False
    MAX_TOOL_ROUNDS = 6
    answer = "Reached the tool-call limit before finishing this request."
    for _ in range(MAX_TOOL_ROUNDS):
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model": CHAT_MODEL,
            "messages": messages,
            "tools": TOOLS_SCHEMA,
            "stream": False,
        })
        resp.raise_for_status()
        message = resp.json()["message"]

        if DEBUG:
            print(f"[DEBUG] Raw model message: {message}\n")

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return message["content"], sources, used_tools

        used_tools = True
        messages.append(message)
        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            if DEBUG:
                print(f"[DEBUG] Tool call requested: {name}({arguments})")
            fn = available_tools.get(name)
            if fn is None:
                result = f"Error: unknown tool '{name}'"
            else:
                try:
                    result = fn(**arguments)
                except PermissionError as e:
                    result = f"Blocked: {e}"
                    tools._log(f"blocked {name}({arguments}): {e}")
                except FileNotFoundError as e:
                    result = f"Not found: {e}"
                except Exception as e:
                    result = f"Error running {name}: {e}"
            if DEBUG:
                print(f"[DEBUG] Tool call result: {result}")
            messages.append({"role": "tool", "content": str(result)})
    if conversation_id:
        try:
            database.save_conversation(conversation_id, "user", query)
            database.save_conversation(conversation_id, "assistant", answer, sources)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] Error saving conversation: {e}")

    return "Reached the tool-call limit before finishing this request.", sources, used_tools, answer
