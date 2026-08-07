import os

MODEL_EXT = ".gguf"


class ModelInfo:
    __slots__ = ("path", "name", "size", "is_mmproj", "dir")

    def __init__(self, path, name, size, is_mmproj, dir_):
        self.path = path
        self.name = name
        self.size = size
        self.is_mmproj = is_mmproj
        self.dir = dir_


def _is_partial(name):
    lower = name.lower()
    return any(lower.endswith(s) for s in (".xltd", ".xltd.cfg", ".partial", ".part", ".download", ".tmp"))


def scan_models(llama_dir):
    models, mmprojs = [], []
    if not llama_dir or not os.path.isdir(llama_dir):
        return models, mmprojs
    for root, _dirs, files in os.walk(llama_dir):
        for fn in files:
            lower = fn.lower()
            if not lower.endswith(MODEL_EXT):
                continue
            if _is_partial(fn):
                continue
            path = os.path.join(root, fn)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            is_mm = lower.startswith("mmproj") or "mmproj" in lower
            info = ModelInfo(path, fn, size, is_mm, root)
            (mmprojs if is_mm else models).append(info)
    models.sort(key=lambda m: m.size, reverse=True)
    mmprojs.sort(key=lambda m: m.size, reverse=True)
    return models, mmprojs


def find_mmproj_for(model, mmprojs):
    """严格按目录配对：只使用与主模型同一目录下的视觉投影，保证主模型与视觉模型一致。"""
    if not mmprojs:
        return None
    for m in mmprojs:
        if m.dir == model.dir:
            return m
    return None


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"
