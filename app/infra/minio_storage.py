from io import BytesIO

from minio import Minio


class MinioObjectStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket_name = bucket_name

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket_name):
            self._client.make_bucket(self._bucket_name)

    def put(self, object_key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(
            self._bucket_name,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def delete(self, object_key: str) -> None:
        self._client.remove_object(self._bucket_name, object_key)

