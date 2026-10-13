from quakestrike.alert_testing.domain.testers import identity


class Consumer:
    def __init__(self, store, delivery, name):
        self.store, self.delivery, self.name = store, delivery, name

    def once(self, owner):
        command = self.store.next_command(owner, self.name)
        if command is None:
            return False
        message_id, fields = command
        try:
            if set(fields) != {"message_version", "session_id", "event_id", "job_id"}:
                raise ValueError
            if fields["message_version"] != "1" or fields["session_id"] != owner:
                raise ValueError
            event = identity(fields["event_id"])
            if fields["job_id"] != event:
                raise ValueError
        except ValueError:
            self.store.ack(owner, message_id)
            return True
        self.delivery.process(owner, event)
        self.store.ack(owner, message_id)
        return True
