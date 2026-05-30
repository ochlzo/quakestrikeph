# Welcome to QuakestrikePH Clustering Phase

This is a project on creating an application backed by machine learning approaches to predict the likelihood of an eathequake aftershock sequence based on the historical data presented in ./dataset/phivolcs_earthquake_2018_2026.csv

This is the clustering phase as the current dataset is not yet appropriate for machine learning phase because the features are still lacking. The target clustering algorithm is the Nearest-Neighbor Declustering Algorithm (Zaliapin & Ben-Zion, 2013a). But this project will not claim it to be the exact algorithm, rather it will adapt it to be more accurate on identifying aftershock-mainshock sequences.

Navigate to:
./docs/zaliapin-ben-zion-2013a-algorithm.md
./docs/zaliapin-ben-zion-conceptual-guide.md
./docs/ml_ready_clustered_dataset_schema.md
for more info about the algorithm

'./examples/' contains old files or code, or sample codes for testing. You don't need to worry about this unless you are told to read it.

We are going to implement this clustering using C++ for best performance

OVERRIDE 300 LINES CODE RULE - it's okay here

## graphify

Graphify is configured for this project. When graphify-out/ exists, it contains the knowledge graph, god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the Graphify skill if it is available; otherwise run the matching `graphify` CLI command directly.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
