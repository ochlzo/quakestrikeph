from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.domain.testers import account_view, identity, selection
from quakestrike.alert_testing.ports import AccountReader


class Testers:
    def __init__(self, accounts: AccountReader, sessions):
        self.accounts = accounts
        self.sessions = sessions

    def _active(self, session_id):
        session = self.sessions.read()
        if session.get("status") != "active" or session.get("session_id") != session_id:
            raise SessionConflict

    def search(self, session_id, query, selected, page, size, event):
        session_id = identity(session_id)
        if not isinstance(query, str) or len(query) > 100:
            raise ValueError("Search is too long.")
        if type(page) is not int or not 1 <= page <= 10000:
            raise ValueError("Invalid page.")
        if type(size) is not int or size not in {5, 10, 25, 50}:
            raise ValueError("Invalid page size.")
        if not isinstance(event, dict) or set(event) != {"magnitude", "latitude", "longitude"}:
            raise ValueError("Invalid event preview.")
        if any(not isinstance(value, str) or len(value) > 250 for value in event.values()):
            raise ValueError("Invalid event preview.")
        selected = selection(selected) if selected is not None else None
        self._active(session_id)
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        result = self.accounts.search(pattern, selected, page, size)
        result["accounts"] = [account_view(account, event) for account in result["accounts"]]
        # Account reads cannot return private data after closure becomes established.
        self._active(session_id)
        return result
