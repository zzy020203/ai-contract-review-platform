"""RAG 向量检索子系统：Milvus（开发期 milvus-lite 本地文件）+ BGE Embedding。

- collection 按库类型划分：rule / history / template（技术设计文档 3.2.2）
- 规则按版本建 partition（v1/v2/...），升级时旧向量同步删除，检索只命中最新版本
- 相似度阈值过滤，低于阈值不注入提示词，避免噪声
"""
from pymilvus import MilvusClient

from app.core.config import settings
from app.services import embedding

LIB_TYPES = ("rule", "history", "template")
SEARCH_THRESHOLD = 0.5  # COSINE 相似度阈值

_client: MilvusClient | None = None


def get_client() -> MilvusClient:
    """进程级单例；milvus-lite 指向本地文件，生产切 MILVUS_URI 服务地址。"""
    global _client
    if _client is None:
        uri = settings.MILVUS_URI or str(settings.STORAGE_DIR / "milvus_lite.db")
        _client = MilvusClient(uri=uri)
    return _client


def _ensure_collection(client: MilvusClient, name: str) -> None:
    if client.has_collection(name):
        client.load_collection(name)  # 跨进程访问时集合处于 released 态，需显式加载
        return
    client.create_collection(
        collection_name=name,
        dimension=embedding.DIM,
        metric_type="COSINE",
        auto_id=True,
        enable_dynamic_field=True,
    )


def _ensure_partition(client: MilvusClient, collection: str, partition: str) -> None:
    if not client.has_partition(collection, partition):
        client.create_partition(collection, partition)


def chunk_text(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    """语义切片：按段落聚合，保持章节/条款边界；超长段落硬切。"""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        while len(p) > max_chars:  # 超长段落先按长度硬切
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:max_chars])
            p = p[max_chars - overlap:]
        if buf and len(buf) + len(p) + 1 > max_chars:
            chunks.append(buf)
            buf = (buf[-overlap:] + "\n" + p) if overlap else p
        else:
            buf = f"{buf}\n{p}" if buf else p
    if buf.strip():
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


# ---------- 规则库 ----------

def index_rule(rule_id: int, code: str, name: str, content: str, version: int) -> None:
    """规则向量化入库（先删旧版向量，再写入 v{version} 分区）。"""
    client = get_client()
    _ensure_collection(client, "rule")
    client.delete("rule", filter=f"rule_id == {rule_id}")
    partition = f"v{version}"
    _ensure_partition(client, "rule", partition)

    text = f"{name}\n{content}"
    chunks = chunk_text(text)
    vectors = embedding.encode(chunks)
    data = [
        {"vector": v, "rule_id": rule_id, "code": code, "name": name,
         "version": version, "content": c}
        for v, c in zip(vectors, chunks)
    ]
    client.insert("rule", data, partition_name=partition)


def delete_rule_vectors(rule_id: int) -> None:
    client = get_client()
    if client.has_collection("rule"):
        client.delete("rule", filter=f"rule_id == {rule_id}")


def search_rules(query: str, top_k: int = 3, threshold: float = SEARCH_THRESHOLD) -> list[dict]:
    """规则检索：全分区 Top-K，命中结果由调用方按启用状态过滤。"""
    return _search("rule", query, top_k, threshold,
                   output_fields=["rule_id", "code", "name", "version", "content"])


# ---------- 知识库（历史合同 / 标准模板） ----------

def index_document(doc_id: int, lib_type: str, title: str, text: str) -> int:
    """知识库文档切片向量化入库，返回切片数。"""
    if lib_type not in LIB_TYPES:
        raise ValueError(f"非法库类型：{lib_type}（可选 {LIB_TYPES}）")
    client = get_client()
    _ensure_collection(client, lib_type)
    client.delete(lib_type, filter=f"doc_id == {doc_id}")

    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors = embedding.encode(chunks)
    data = [
        {"vector": v, "doc_id": doc_id, "lib_type": lib_type, "title": title, "content": c}
        for v, c in zip(vectors, chunks)
    ]
    client.insert(lib_type, data)
    return len(chunks)


def delete_document_vectors(lib_type: str, doc_id: int) -> None:
    client = get_client()
    if client.has_collection(lib_type):
        client.delete(lib_type, filter=f"doc_id == {doc_id}")


def search_knowledge(lib_type: str, query: str, top_k: int = 3,
                     threshold: float = SEARCH_THRESHOLD) -> list[dict]:
    if lib_type not in LIB_TYPES:
        raise ValueError(f"非法库类型：{lib_type}（可选 {LIB_TYPES}）")
    return _search(lib_type, query, top_k, threshold,
                   output_fields=["doc_id", "title", "content"])


# ---------- 内部 ----------

def _search(collection: str, query: str, top_k: int, threshold: float,
            output_fields: list[str]) -> list[dict]:
    client = get_client()
    if not client.has_collection(collection):
        return []
    client.load_collection(collection)  # 跨进程访问时集合处于 released 态，需显式加载
    vector = embedding.encode([query])[0]
    res = client.search(
        collection, data=[vector], limit=top_k,
        output_fields=output_fields,
        search_params={"metric_type": "COSINE"},
    )
    hits: list[dict] = []
    for hit in (res[0] if res else []):
        if hit["distance"] < threshold:
            continue
        item = {k: hit["entity"].get(k) for k in output_fields}
        item["score"] = round(hit["distance"], 4)
        hits.append(item)
    return hits
