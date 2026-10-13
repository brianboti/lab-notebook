"""Attachment storage: the declared bucket on Google Cloud, a dictionary locally and in tests."""


class MemoryStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, name: str, data: bytes, content_type: str) -> None:
        self.objects[name] = (data, content_type)

    def get(self, name: str) -> bytes:
        return self.objects[name][0]

    def delete(self, name: str) -> None:
        self.objects.pop(name, None)


class BucketStorage:
    """The bucket the platform created (BUCKET_UPLOADS); the app's own identity may read and write objects in it."""

    def __init__(self, bucket: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def put(self, name: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(name).upload_from_string(data, content_type=content_type)

    def get(self, name: str) -> bytes:
        return self.bucket.blob(name).download_as_bytes()

    def delete(self, name: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(name).delete()
        except NotFound:
            pass
