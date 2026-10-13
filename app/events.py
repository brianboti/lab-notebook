"""The activity feed: events are published to the declared topic and read back from its subscription.

Both happen inside a request. Cloud Run gives CPU only while a request runs, so publishing waits for the server's
answer instead of leaving work for after the response, and reading is a synchronous pull when someone opens the page.
Messages are acknowledged only after the caller has stored them, so a failed write means redelivery, not loss.
"""

import datetime
import json
import uuid


def envelope(kind: str, detail: str, actor: str) -> dict:
    return {"kind": kind, "detail": detail, "actor": actor, "at": datetime.datetime.now(datetime.UTC).isoformat()}


class MemoryEvents:
    def __init__(self):
        self.queue: list[dict] = []
        self.pending: dict[str, dict] = {}

    def publish(self, kind: str, detail: str, actor: str) -> None:
        self.queue.append({**envelope(kind, detail, actor), "id": uuid.uuid4().hex})

    def pull(self, limit: int = 20) -> list[tuple[dict, str]]:
        taken, self.queue = self.queue[:limit], self.queue[limit:]
        self.pending.update({event["id"]: event for event in taken})
        return [(event, event["id"]) for event in taken]

    def ack(self, ack_ids: list[str]) -> None:
        for ack_id in ack_ids:
            self.pending.pop(ack_id, None)


class PubSubEvents:
    def __init__(self, topic: str, subscription: str):
        from google.cloud import pubsub_v1

        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()
        self.topic, self.subscription = topic, subscription

    def publish(self, kind: str, detail: str, actor: str) -> None:
        self.publisher.publish(self.topic, json.dumps(envelope(kind, detail, actor)).encode()).result(timeout=10)

    def pull(self, limit: int = 20) -> list[tuple[dict, str]]:
        from google.api_core.exceptions import DeadlineExceeded

        try:
            response = self.subscriber.pull(request={"subscription": self.subscription, "max_messages": limit}, timeout=5)
        except DeadlineExceeded:
            return []
        return [({**json.loads(m.message.data or b"{}"), "id": m.message.message_id}, m.ack_id) for m in response.received_messages]

    def ack(self, ack_ids: list[str]) -> None:
        if ack_ids:
            self.subscriber.acknowledge(request={"subscription": self.subscription, "ack_ids": ack_ids})
