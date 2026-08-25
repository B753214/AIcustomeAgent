from functools import lru_cache

from pymilvus import MilvusClient, DataType

from app.config import get_settings

settings = get_settings()
COLLECTION_NAME = settings.COLLECTION_NAME
MILVUS_URI = settings.MILVUS_URI
DIM = settings.DIM

@lru_cache
def get_milvus_client()->MilvusClient:
    return MilvusClient(uri=MILVUS_URI)

def ensure_collection()->None:
    client = get_milvus_client()
    if client.has_collection(collection_name=COLLECTION_NAME):  # 不是 name=
        return
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
    schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=DIM)
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=COLLECTION_NAME,  # 不是 name=
        schema=schema,
        index_params=index_params,
    )


def upset_chunk_vector(chunk_id: str, doc_id: str, vector: list[float]) -> None:
    client = get_milvus_client()
    client.upsert(
        collection_name=COLLECTION_NAME,
        data=[{
            "id": chunk_id,
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "vector": vector,
        }],
    )
def search_vectors(query_vector: list[float], top_k: int = 5) -> list[dict]:
    if not query_vector:
        return []
    client = get_milvus_client()

    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        top_k=top_k,
        metric_type="COSINE",
        output_fields=["chunk_id", "doc_id"],
    )
    print("results:", results)
    hits=[]
    for group in results:
        for hit in group:
            entry = hit.get("entity") or {}
            hits.append({
                "chunk_id": entry.get("chunk_id"),
                "doc_id": entry.get("doc_id"),
            })

    return hits

if __name__ == '__main__':
    client = get_milvus_client()
    # if client.has_collection(collection_name=COLLECTION_NAME):
    #     client.drop_collection(collection_name=COLLECTION_NAME)
    #     print(f"已删除旧集合: {COLLECTION_NAME}")
    #
    # # ② 创建新集合（dim=1024）
    ensure_collection()
    # print(f"已创建新集合: {COLLECTION_NAME}, dim={DIM}")
    info = client.describe_collection(collection_name=COLLECTION_NAME)
    print("=== Collection Schema ===")
    print(info)
    from app.rag.retriever import build_embedding
    texts: str ="退货运费由卖家承担"
    llm = build_embedding()
    vector = llm.embed_query(texts)

    # upset_chunk_vector("1", "1", vector)
    # query="运费谁出"
    # query_vector = llm.embed_query(query)
    # print(f"query_vector: {query_vector}")
    # hits = search_vectors(query_vector)
    # print(f"hits: {hits}")

