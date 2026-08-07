"""Document provenance and trust semantics shared by review and reconciliation."""

from enum import StrEnum


class DocumentSourceKind(StrEnum):
    """How a canonical document version entered the system."""

    INVOICE_UPLOAD = "invoice_upload"
    EXTERNAL_RECEIVE_NOTE_UPLOAD = "external_receive_note_upload"
    TAPTOUCH_RECEIVING = "taptouch_receiving"


class DocumentTrustMethod(StrEnum):
    """Why a canonical version may be trusted for reconciliation."""

    HUMAN_APPROVED = "human_approved"
    UPSTREAM_AUTHORITATIVE = "upstream_authoritative"
    UNTRUSTED = "untrusted"


class UpstreamRecordStatus(StrEnum):
    """Lifecycle state supplied by the authoritative upstream system."""

    ACTIVE = "active"
    VOIDED = "voided"
