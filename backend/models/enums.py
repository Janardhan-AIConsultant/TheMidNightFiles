from enum import Enum


class RevisionKind(str, Enum):
    ORIGINAL = "original"
    HUMANISED = "humanised"
    FINAL = "final"


class EditorialStatus(str, Enum):
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class SafetyStatus(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEWING = "REVIEWING"
    PASSED = "PASSED"
    NEEDS_REVISION = "NEEDS_REVISION"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class ContinuityStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    ISSUES_FOUND = "ISSUES_FOUND"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
