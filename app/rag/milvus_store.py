from functools import lru_cache

from pymilvus import MilvusClient, DataType

from AICustomeRobort.app.config import get_settings

settings = get_settings()
COLLECTION_NAME = settings.COLLECTION_NAME
MILVUS_URI = settings.MILVUS_URI
DIM = settings.DIM

@lru_cache
def get_milvus_client()->MilvusClient:
    return MilvusClient(uri=MILVUS_URI)

def ensure_collection()->None:
    client = get_milvus_client()
    if client.has_collection(name=COLLECTION_NAME):
        return
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.UUID, is_primary=True)
    schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=DIM)
    index_params = client.prepare_index_params(index_type="AUTOINDEX", field_names=["vector"], metric_type="COSINE")
    client.create_collection(name=COLLECTION_NAME, schema=schema, index_params=index_params)

