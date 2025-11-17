from asyncio import gather
from functools import cache
from pathlib import Path
from sys import modules
from traceback import format_exception, walk_tb
from types import TracebackType
from typing import TYPE_CHECKING

from js import console
from pyodide.code import find_imports
from pyodide.ffi import to_js

if TYPE_CHECKING:
    sources: dict[str, str] = {}

    LOCKFILE_PACKAGES: dict[str, dict] = {}

    async def load_packages_from_imports(source: str): ...

    class Toast:
        def loading(self, message: str, /, *, id: str): ...
        def success(self, message: str, /, *, id: str): ...

    toast = Toast()

else:
    import pyodide_js

    LOCKFILE_PACKAGES = pyodide_js._api.lockfile_packages.to_py()
    load_packages_from_imports = pyodide_js.loadPackagesFromImports


def reload_module(name: str):
    if name in modules:
        del modules[name]
        console.warn("reloading module", name)

        if "." in name:
            parent_module, _ = name.rsplit(".", 1)
            reload_module(parent_module)


for name, content in sources.items():
    path = Path.cwd() / name

    content = content.replace("\r\n", "\n").replace("\r", "\n")

    if not path.is_file() or path.read_text() != content:
        console.log("detected change in", name)

        reload_module(name.replace(".py", "").replace("/", ".").replace(".__init__", ""))
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)
        path.write_text(content)


ENTRY = "__main__.py"


def num_frames_to_keep(tb: TracebackType | None) -> int:
    keep_frames = False
    kept_frames = 0
    for frame, _ in walk_tb(tb):
        keep_frames = keep_frames or frame.f_code.co_filename == ENTRY
        kept_frames += keep_frames
    return kept_frames


def formattraceback(e: BaseException):
    nframes = num_frames_to_keep(e.__traceback__)
    return "".join(format_exception(type(e), e, e.__traceback__, -nframes))


@cache
def build_reversed_index() -> dict[str, tuple[str, str]]:
    return {import_name: (package_name, info["version"]) for package_name, info in LOCKFILE_PACKAGES.items() for import_name in info["imports"]}


def get_install_name(import_name: str):
    if import_name not in modules:
        return build_reversed_index().get(import_name)


def find_packages_to_install(source: str):
    return list(filter(None, map(get_install_name, find_imports(source))))


async def auto_load_packages(source: str):
    if packages := find_packages_to_install(source):
        prompt = f"auto installing {'\n'.join(f'{name}=={version}' for name, version in packages)}"
        toast.loading(prompt, id=prompt)
        await load_packages_from_imports(source)
        toast.success(prompt, id=prompt)


async def run():
    from pyodide.code import eval_code_async

    await gather(*map(auto_load_packages, sources.values()))

    try:
        return to_js([str(await eval_code_async(Path(ENTRY).read_text(), {"__name__": "__main__", "__file__": ENTRY}, filename=ENTRY, return_mode="last_expr_or_assign")), None])
    except BaseException as e:
        return to_js([None, formattraceback(e)])


run
