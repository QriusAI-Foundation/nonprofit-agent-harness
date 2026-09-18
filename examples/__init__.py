"""Reference agents.

Deliberately no eager imports. Importing the submodules here would make
`python -m examples.iati_portfolio` warn that the module was already in `sys.modules`,
and nothing needs them loaded up front. Refer to an agent by its full path:

    HARNESS_AGENTS=examples.summarizer:SummarizerAgent
"""
