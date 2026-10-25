"""GroundClaim: check what an AI agent says it did against evidence of what actually happened."""

from .claims import extract_claims
from .model import SCHEMA_VERSION, Assessment, Claim, Evidence, Link, Report
from .recorder import Recorder
from .verify import CommandRun, Sources, verify

__version__ = "0.1.0"
__all__ = [
    "SCHEMA_VERSION",
    "Assessment",
    "Claim",
    "CommandRun",
    "Evidence",
    "Link",
    "Recorder",
    "Report",
    "Sources",
    "__version__",
    "extract_claims",
    "verify",
]
