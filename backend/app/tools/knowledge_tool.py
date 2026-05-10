from app.tools.base import BaseTool, ToolResult
from app.rag.engine import get_rag_engine


class KnowledgeIndexTool(BaseTool):
    name = "knowledge_index"
    description = "将本地文件或文件夹加入知识库，建立向量索引。支持 .txt, .md, .py, .js, .ts, .json, .yaml, .csv, .html 等纯文本格式。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "绝对路径，文件或文件夹"},
            "recursive": {"type": "boolean", "default": True, "description": "如果是文件夹，是否递归索引子目录"}
        },
        "required": ["path"]
    }

    async def execute(self, path: str, recursive: bool = True) -> ToolResult:
        engine = get_rag_engine()
        result = engine.index_file(path, recursive=recursive)
        if "error" in result:
            return ToolResult(error=result["error"])
        return ToolResult(
            output=f"索引完成：{result['indexed']} 个文件，{result['chunks']} 个文本块"
            + (f"，跳过 {result['skipped']} 个" if result.get("skipped") else "")
        )


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = "基于语义相似度检索知识库中的相关文本片段。当用户询问与本地文档、代码、笔记相关的问题时使用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索 query，描述你想查找的内容"},
            "top_k": {"type": "integer", "default": 5, "description": "返回的最相似片段数量"},
            "source_filter": {"type": "string", "description": "可选：限制来源路径前缀，例如 /path/to/project"},
            "min_score": {"type": "number", "default": 0.3, "description": "最低相关度阈值（0-1），低于此分数的结果将被过滤"}
        },
        "required": ["query"]
    }

    async def execute(self, query: str, top_k: int = 5, source_filter: str = "", min_score: float = 0.3) -> ToolResult:
        engine = get_rag_engine()
        results = engine.search(query, top_k=top_k, source_filter=source_filter or None)
        if min_score > 0:
            results = [r for r in results if r.score >= min_score]
        if not results:
            return ToolResult(output="知识库中未找到相关内容。")
        lines = []
        for r in results:
            lines.append(f"【来源: {r.source_path} | 相关度: {r.score}】\n{r.content}\n")
        return ToolResult(output="\n---\n".join(lines))


class KnowledgeListTool(BaseTool):
    name = "knowledge_list"
    description = "列出当前已索引的文档和统计信息。"
    parameters = {
        "type": "object",
        "properties": {}
    }

    async def execute(self) -> ToolResult:
        engine = get_rag_engine()
        docs = engine.list_docs()
        if not docs:
            return ToolResult(output="知识库为空，尚未索引任何文档。")
        lines = [f"共 {len(docs)} 个源文件："]
        for d in docs:
            lines.append(f"- {d['source_path']} ({d['chunk_count']} chunks)")
        return ToolResult(output="\n".join(lines))


class KnowledgeClearTool(BaseTool):
    name = "knowledge_clear"
    description = "清空整个知识库，删除所有已索引的文档和向量数据。此操作不可逆！"
    parameters = {
        "type": "object",
        "properties": {}
    }

    async def execute(self) -> ToolResult:
        engine = get_rag_engine()
        result = engine.clear_all()
        if result.get("cleared"):
            return ToolResult(output="知识库已清空。")
        return ToolResult(error="清空知识库失败")
