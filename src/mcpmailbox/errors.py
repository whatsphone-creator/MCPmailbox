"""Errors the mailbox expects and reports to the caller."""


class MailboxError(Exception):
    """A rejected mailbox operation. The message is safe to show to the client."""
