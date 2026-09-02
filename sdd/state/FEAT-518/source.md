---
kind: inline
jira_key: null
fetched_at: 2026-09-02T13:36:00+02:00
summary_oneline: PythonREPL WorkerPool death spiral — every python_repl_pandas call fails after 5s with an empty ValueError and the worker is restarted
---

# Source (inline) — `bug-workerpool-repl`

Worker Pool for REPL tool is dying with the following error:

```
[WARNING] 2026-09-02 13:33:09,678 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' worker is dead, restarting
[DEBUG] 2026-09-02 13:33:09,678 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' bound to a prewarmed worker
[DEBUG] 2026-09-02 13:33:09,679 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70250
[DEBUG] 2026-09-02 13:33:09,679 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
[ERROR] 2026-09-02 13:33:14,682 python_repl_pandas.Tool(pythonrepl.py:960) :: Error executing Python code: 
[WARNING] 2026-09-02 13:33:14,690 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' worker is dead, restarting
[DEBUG] 2026-09-02 13:33:14,691 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' bound to a prewarmed worker
[DEBUG] 2026-09-02 13:33:14,692 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70383
[DEBUG] 2026-09-02 13:33:14,692 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
[INFO] 2026-09-02 13:33:19,695 parrot.tools.working_memory.internals(internals.py:537) :: [WorkingMemory] Stored generic '__tee__:python_repl_pandas:a7a96860:1' type=text
[ERROR] 2026-09-02 13:33:19,695 flex_dashboard.Bot(manager.py:1864) :: Error executing tool python_repl_pandas: 
[ERROR] 2026-09-02 13:33:19,703 GoogleGenAIClient(base.py:1504) :: Error executing tool python_repl_pandas: 
[ERROR] 2026-09-02 13:33:19,704 GoogleGenAIClient(client.py:1961) :: Tool python_repl_pandas failed: 
[NOTICE] 2026-09-02 13:33:19,704 :: 🔍 Tool: python_repl_pandas
[NOTICE] 2026-09-02 13:33:19,704 :: 📤 Raw Result Type: <class 'ValueError'>
[NOTICE] 2026-09-02 13:33:19,704 :: Tool python_repl_pandas output preview: ...
```

agents using PythonREPL were not able to use it, dying every time they called:

```
[WARNING] 2026-09-02 13:34:10,205 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' worker is dead, restarting
[DEBUG] 2026-09-02 13:34:10,205 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' bound to a prewarmed worker
[DEBUG] 2026-09-02 13:34:10,206 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70829
[DEBUG] 2026-09-02 13:34:10,206 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
[INFO] 2026-09-02 13:34:15,208 python_repl_pandas.Tool(pythonrepl.py:945) :: Executing Python code: # Let's see what variables are in the namespace
print(dir())
...
[WARNING] 2026-09-02 13:34:15,209 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' worker is dead, restarting
[DEBUG] 2026-09-02 13:34:15,209 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' bound to a prewarmed worker
[DEBUG] 2026-09-02 13:34:15,210 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70860
[DEBUG] 2026-09-02 13:34:15,210 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
[ERROR] 2026-09-02 13:34:20,213 python_repl_pandas.Tool(pythonrepl.py:960) :: Error executing Python code: 
[WARNING] 2026-09-02 13:34:20,213 parrot.tools.repl_worker.pool(pool.py:241) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' worker is dead, restarting
[DEBUG] 2026-09-02 13:34:20,213 parrot.tools.repl_worker.pool(pool.py:265) :: WorkerPool: session 'pythonrepl-2fd699584639497281fd8957c0f21e8f' bound to a prewarmed worker
[DEBUG] 2026-09-02 13:34:20,214 parrot.tools.repl_worker.handle(handle.py:187) :: WorkerHandle: spawned worker pid=70908
[DEBUG] 2026-09-02 13:34:20,214 parrot.tools.repl_worker.pool(pool.py:187) :: WorkerPool: prewarmed worker ready (pool size=2)
[INFO] 2026-09-02 13:34:25,217 parrot.tools.working_memory.internals(internals.py:537) :: [WorkingMemory] Stored generic '__tee__:python_repl_pandas:a7a96860:4' type=text
[ERROR] 2026-09-02 13:34:25,217 flex_dashboard.Bot(manager.py:1864) :: Error executing tool python_repl_pandas: 
[ERROR] 2026-09-02 13:34:25,217 GoogleGenAIClient(base.py:1504) :: Error executing tool python_repl_pandas: 
[ERROR] 2026-09-02 13:34:25,217 GoogleGenAIClient(client.py:1961) :: Tool python_repl_pandas failed: 
[NOTICE] 2026-09-02 13:34:25,217 :: 🔍 Tool: python_repl_pandas
[NOTICE] 2026-09-02 13:34:25,217 :: 📤 Raw Result Type: <class 'ValueError'>
[NOTICE] 2026-09-02 13:34:25,217 :: Tool python_repl_pandas output preview: ...
[DEBUG] 2026-09-02 13:34:25,217 GoogleGenAIClient(client.py:2089) :: Sending 1 responses back to model
[DEBUG] 2026-09-02 13:34:29,068 GoogleGenAIClient(client.py:2384) :: Found proper function call: wm_list_tool_dataframes({})
```

## Signals extracted (not interpreted)

- Every failing call sits on an exact **5.0 s grid** (`.678 → 14.682`, `14.690 → 19.695`, `10.205 → 15.208`, `15.209 → 20.213`, `20.213 → 25.217`).
- Every error message is **empty** (`Error executing Python code: ` / `Tool python_repl_pandas failed: ` / `ValueError` with no text).
- The pool logs `prewarmed worker ready` **in the same millisecond** as `spawned worker pid=…`.
- Each `acquire` finds the previous worker dead and binds the spare that was spawned only 5 s earlier.
- Tool is `python_repl_pandas` (PandasAgent / `flex_dashboard` bot), Google GenAI client.
