"""Adapters for the sector's own open data.

A data source's job is to produce `Document`s. Once it does, everything else in the
harness applies unchanged: an agent consumes them like any other input, and a claim
citing them is verified against the same text the agent was given.
"""

from nonprofit_harness.datasources.iati import IatiActivity, IatiClient

__all__ = ["IatiActivity", "IatiClient"]
