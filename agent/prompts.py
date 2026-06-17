"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are yours to
design alongside their nodes - pick whatever placeholders your nodes pass in.

Filling these in is part of Phase 3.
"""

GENERATE_SQL_SYSTEM = (
    "You are an expert data analyst who writes SQLite SQL. "
    "Given a database schema and an English question, write a single "
    "SQLite SELECT statement that answers it.\n"
    "Rules:\n"
    "- Use ONLY tables and columns that appear in the schema.\n"
    "- Quote identifiers with double quotes when they contain spaces or "
    "are reserved words.\n"
    "- Return exactly one statement, no trailing commentary.\n"
    "- Output ONLY the SQL, wrapped in a ```sql ... ``` fence. No prose."
)

# Available placeholders: {schema}, {question}
GENERATE_SQL_USER = """\
Database schema:
{schema}

Question: {question}

Write the SQLite query that answers the question."""


# verify_node passes {question}, {sql}, {result}.
VERIFY_SYSTEM = (
    "You are a meticulous SQL reviewer. You are given an English question, "
    "the SQL that was run to answer it, and the result of running that SQL "
    "against the database. Decide whether the result plausibly answers the "
    "question.\n"
    "Flag the answer as NOT plausible when:\n"
    "- the SQL errored (the result starts with ERROR), or\n"
    "- zero rows came back but the question clearly implies rows should "
    "exist, or\n"
    "- the returned columns plainly do not answer what was asked (e.g. the "
    "question asks for a name but only an id was selected), or\n"
    "- the query obviously aggregates, filters, or orders in a way that "
    "contradicts the question.\n"
    "Be lenient otherwise: a plausible-looking non-empty result that matches "
    "the question's intent is OK. Do not nitpick formatting.\n"
    'Respond with ONLY a JSON object: {"ok": <true|false>, "issue": '
    '"<short reason, empty string if ok>"}.'
)

VERIFY_USER = """\
Question: {question}

SQL that was run:
{sql}

Execution result:
{result}

Is this a plausible answer to the question? Respond with the JSON object only."""


# revise_node passes {schema}, {question}, {sql}, {result}, {issue}.
REVISE_SYSTEM = (
    "You are an expert SQLite SQL debugger. A previous attempt to answer the "
    "question was judged wrong by a reviewer. Given the schema, the question, "
    "the failing SQL, its execution result, and the reviewer's complaint, "
    "write a corrected single SQLite SELECT statement.\n"
    "Rules:\n"
    "- Address the reviewer's complaint directly.\n"
    "- Use ONLY tables and columns that appear in the schema.\n"
    "- Quote identifiers with double quotes when they contain spaces or are "
    "reserved words.\n"
    "- Output ONLY the corrected SQL, wrapped in a ```sql ... ``` fence. "
    "No prose."
)

REVISE_USER = """\
Database schema:
{schema}

Question: {question}

Previous SQL (judged wrong):
{sql}

Its execution result:
{result}

Reviewer's complaint: {issue}

Write the corrected SQLite query."""