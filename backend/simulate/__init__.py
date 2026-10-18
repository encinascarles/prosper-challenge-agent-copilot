"""Simulated calls: an agent's tests, run in text on the same Pipecat pipeline
as its voice calls, against a model playing the caller, and checked."""

from .checks import parse
from .suite import REPEATS, Services, run_suite

__all__ = ["REPEATS", "Services", "parse", "run_suite"]
