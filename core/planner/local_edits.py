"""Expand literal edits from trusted context snapshots, without filesystem access."""
import hashlib
from pathlib import PurePosixPath
from posixpath import normpath


MAX_CONTENT_BYTES = 200000
MAX_EDITS = 100


def content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def copy_sources(source_files):
    if source_files is None:
        return {}
    if not isinstance(source_files, dict):
        raise ValueError("Fontes do planejamento devem ser um objeto.")
    sources = dict(source_files)
    for path, content in sources.items():
        if not isinstance(path, str) or not path or "\\" in path:
            raise ValueError("Caminho inválido nas fontes do planejamento.")
        relative = PurePosixPath(path)
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path:
            raise ValueError("Caminho não normalizado nas fontes do planejamento.")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("Conteúdo inválido nas fontes do planejamento.")
    return sources


def expand_local_edits(data, sources):
    # Keep legacy validation and its error messages for the existing format.
    if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
        return data
    result = dict(data)
    changes = data["changes"]
    expanded = []
    for item in changes:
        if not isinstance(item, dict) or "edits" not in item:
            expanded.append(item)
            continue
        kind = item.get("change_type")
        if kind is None:
            kind = item.get("type")
        if kind != "modify" or "content" in item:
            raise ValueError("Edições locais exigem MODIFY sem o campo content.")
        path = item.get("path")
        if not isinstance(path, str) or path not in sources:
            raise ValueError("Edição local exige arquivo completo presente no contexto.")
        if sum(isinstance(change, dict) and isinstance(change.get("path"), str)
               and normpath(change["path"]) == path for change in changes) != 1:
            raise ValueError("Arquivo repetido em alterações com edição local.")
        original = sources[path]
        if item.get("base_sha256") != content_hash(original):
            raise ValueError("Hash da edição local não corresponde ao contexto.")
        edits = item["edits"]
        if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
            raise ValueError("Edição local exige de 1 a 100 substituições.")
        content = original
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"old", "new"}:
                raise ValueError("Cada substituição exige somente old e new.")
            old, new = edit["old"], edit["new"]
            if not isinstance(old, str) or not old or not isinstance(new, str) or old == new:
                raise ValueError("Substituição local inválida ou sem alteração.")
            first = content.find(old)
            if first < 0 or content.find(old, first + 1) >= 0:
                raise ValueError("Trecho old precisa ocorrer exatamente uma vez.")
            content = content[:first] + new + content[first + len(old):]
            if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
                raise ValueError("Conteúdo reconstruído excede o limite de 200000 bytes.")
        normalized = {key: value for key, value in item.items() if key not in {"edits", "base_sha256"}}
        normalized["content"] = content
        expanded.append(normalized)
    result["changes"] = expanded
    return result
