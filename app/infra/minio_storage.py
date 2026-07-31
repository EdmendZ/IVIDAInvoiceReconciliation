"""ObjectStorage Port 的 MinIO 实现。"""

from io import BytesIO

from minio import Minio


class MinioObjectStorage:
    """为本项目 Bucket 提供 put/get/delete，并在启动时确保 Bucket 存在。"""

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
        """幂等创建 Bucket；并发创建由 MinIO 端约束。"""

        if not self._client.bucket_exists(self._bucket_name):
            self._client.make_bucket(self._bucket_name)

    def put(self, object_key: str, data: bytes, content_type: str) -> None:
        """把完整 bytes 写入指定 Object Key。"""

        self._ensure_bucket()
        self._client.put_object(
            self._bucket_name,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def delete(self, object_key: str) -> None:
        """删除补偿或治理流程指定的单个对象。"""

        self._client.remove_object(self._bucket_name, object_key)

    def get(self, object_key: str) -> bytes:
        """读取对象并始终关闭/释放 HTTP Response 连接。"""

        response = self._client.get_object(self._bucket_name, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
