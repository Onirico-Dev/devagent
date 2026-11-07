"""Expand literal edits from trusted context snapshots, without filesystem access."""
import hashlib
from pathlib import PurePosixPath
from posixpath import normpath


MAX_CONTENT_BYTES = 200000
MAX_EDITS = 100


class LocalEditAnchorError(ValueError):
    """Identifies a literal anchor failure without including source content."""

    def __init__(self, path, edit_number, reason):
        self.path = path
        self.edit_number = edit_number
        self.reason = reason
        detail = "não encontrado" if reason == "missing" else "ambíguo"
        super().__init__(f"Trecho old precisa ocorrer exatamente uma vez: {path}, edição {edit_number}, {detail}.")


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


def _validate_local_change(item, changes, sources):
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
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"old", "new"}:
            raise ValueError("Cada substituição exige somente old e new.")
        old, new = edit["old"], edit["new"]
        if not isinstance(old, str) or not old or not isinstance(new, str) or old == new:
            raise ValueError("Substituição local inválida ou sem alteração.")
        if len(new.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("Conteúdo reconstruído excede o limite de 200000 bytes.")
    return original, edits


def expand_local_edits(data, sources):
    # Validate static constraints across the whole response before anchors can
    # trigger a retry. Occurrences still depend on sequential reconstruction.
    if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
        return data
    changes = data["changes"]
    prepared = []
    for item in changes:
        local = (_validate_local_change(item, changes, sources)
                 if isinstance(item, dict) and "edits" in item else None)
        prepared.append((item, local))

    expanded = []
    for item, local in prepared:
        if local is None:
            expanded.append(item)
            continue
        content, edits = local
        path = item["path"]
        for edit_number, edit in enumerate(edits, 1):
            old, new = edit["old"], edit["new"]
            first = content.find(old)
            if first < 0:
                raise LocalEditAnchorError(path, edit_number, "missing")
            if content.find(old, first + 1) >= 0:
                raise LocalEditAnchorError(path, edit_number, "ambiguous")
            content = content[:first] + new + content[first + len(old):]
            if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
                raise ValueError("Conteúdo reconstruído excede o limite de 200000 bytes.")
        normalized = {key: value for key, value in item.items() if key not in {"edits", "base_sha256"}}
        normalized["content"] = content
        expanded.append(normalized)
    return {**data, "changes": expanded}
