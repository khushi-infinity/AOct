"""Decision helpers: does the request actually authorise deletion?

Requests arrive in many languages and some of them are *not* deletion
requests at all (access, correction, export, marketing opt-out, login help).
The classifier therefore works on intent phrases rather than one language's
keywords, and it checks refusals/negations before it looks for deletion words.
"""

from __future__ import annotations

import re
import unicodedata

# Phrases that explicitly withdraw or contradict a deletion request.  These are
# checked first because several of them contain the word "delete" themselves.
_NON_DELETION = (
    # English
    r"not asking for deletion",
    r"not a (?:request|deletion) to (?:erase|delete)",
    r"do not (?:delete|close|remove)",
    r"don'?t (?:delete|close|remove)",
    r"without (?:removing|deleting|closing)",
    r"leave (?:my|the) (?:account|profile|records?)",
    r"keep (?:the|my) account",
    r"(?:still|want to) (?:need|use) (?:the|my) account",
    r"continue using",
    r"marketing (?:lists?|emails?) only",
    r"stop the promotional",
    r"unsubscribe",
    r"opt[- ]?out",
    r"reset(?:ting)? (?:the|my) (?:password|login)",
    r"(?:can'?t|cannot) access",
    r"surname is misspelled",
    r"correct (?:it|my|the) (?:name|surname|details)",
    r"change (?:the|my) email",
    r"information (?:request|held)",
    # Spanish / Portuguese
    r"no solicito (?:la )?(?:eliminaci[oó]n|el borrado)",
    r"no quiero (?:eliminar|borrar)",
    r"n[aã]o (?:solicito|quero) (?:a )?(?:exclus[aã]o|elimina[cç][aã]o)",
    # French
    r"je ne demande pas (?:la )?suppression",
    r"ne supprimez pas",
    # German / Italian
    r"keine l[oö]schung",
    r"nicht l[oö]schen",
    r"nicht entfernen",
    r"l[oö]schen sie\b.{0,60}\bnicht\b",
    r"\bnicht zu l[oö]schen\b",
    r"non richiedo la cancellazione",
    r"non cancellare",
    r"non eliminare",
    # French / Spanish / Portuguese negations placed after the verb
    r"ne (?:pas )?(?:supprimer|effacer|fermer)",
    r"supprimez pas",
    r"no (?:eliminar|borrar|suprimir)\b",
    r"n[aã]o (?:excluir|eliminar|apagar)\b",
    # Japanese / Korean / Chinese
    r"削除(?:は|を)?(?:希望|依頼)しません",
    r"삭제(?:를)?\s*(?:요청하지|원하지)\s*않",
    r"不(?:要|申请)删除",
)

# Words that express "make my data go away" across the languages present in the
# corpus.  They are stems so that inflection (deleted/deletion/deleting) works.
_DELETION = (
    r"\bdelet", r"\beras", r"\bremove", r"\bremov", r"\bclos(?:e|ed|ing)\b",
    r"\bwipe\b", r"\bpurge", r"\bscrub", r"\bsuppress",
    r"\bclean (?:my|out)", r"\bopt[- ]?out of (?:all|everything)",
    # Requests that ask the agent to audit or confirm a deletion the person
    # already believes happened still authorise the deletion decision.
    r"\baudit (?:the|my|this) (?:deletion|request|removal)",
    r"\bverify (?:that|whether) (?:my|the) (?:account|profile|data|records?)",
    r"confirm (?:that|whether) .{0,40}(?:is|are|was|were|be) (?:gone|deleted|removed|erased|absent)",
    r"check (?:the )?(?:latest|current) (?:state|status)",
    r"remaining (?:records?|copies|copies of)",
    r"supprim", r"effac", r"elimin", r"borr", r"exclu", r"cancela",
    r"l[oö]sch", r"entfern", r"cancell", r"rimuov",
    r"削除", r"消去", r"삭제", r"删除", r"刪除", r"消除",
    r"حذف", r"삭제요청",
)

_NON_DELETION_RE = [re.compile(pattern) for pattern in _NON_DELETION]
_DELETION_RE = [re.compile(pattern) for pattern in _DELETION]


def normalize(text: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", text or "").strip().casefold().split()
    )


def is_deletion_request(text: str) -> bool:
    """True only when the message authorises deletion of the account data."""

    value = normalize(text)
    if not value:
        return False
    for pattern in _NON_DELETION_RE:
        if pattern.search(value):
            return False
    return any(pattern.search(value) for pattern in _DELETION_RE)
