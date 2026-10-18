#!/usr/bin/env python3
"""预下载 torch wheel 的完整依赖闭包（含 extras 传递）到 backend/.wheelcache。

Range 断点续传 + sha256 校验；Docker 构建时离线安装，规避代理大文件截断。

用法（在 backend/ 目录下）：
    WHEEL_PROXY=http://172.31.144.1:7897 python scripts/predownload_torch_wheels.py
不设 WHEEL_PROXY 则直连。默认下载 CUDA 版 torch；TORCH_FLAVOR=cpu 可切到 CPU 版。
脚本同时按 requirements.txt 解析全部业务依赖，产出 Docker 可完全离线安装的 wheel 集。
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

_HERE = os.path.dirname(os.path.abspath(__file__))
PROXY = os.environ.get("WHEEL_PROXY", "").strip()
DST = os.path.normpath(os.path.join(_HERE, "..", ".wheelcache"))
REQUIREMENTS = os.path.normpath(os.path.join(_HERE, "..", "requirements.txt"))
TORCH_VER = os.environ.get("TORCH_VER", "2.14.1")
# 本机为 RTX 4060（WSL2 + nvidia-container-toolkit 透传），默认 CUDA 版 torch。
# 无 GPU 环境设 TORCH_FLAVOR=cpu 可改用 CPU wheel（镜像约小 10GB）。
TORCH_FLAVOR = os.environ.get("TORCH_FLAVOR", "cuda").lower()
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
os.makedirs(DST, exist_ok=True)

_handlers = []
if PROXY:
    _handlers.append(urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}))
opener = urllib.request.build_opener(*_handlers)

MENV = default_environment()
MENV.update({
    "python_version": "3.12",
    "python_full_version": "3.12.7",
    "platform_system": "Linux",
    "sys_platform": "linux",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "implementation_name": "cpython",
})

# pkg -> {"specs": SpecifierSet 累积约束, "extras": set 被请求的 extras}
constraints: dict[str, dict] = {}
json_cache: dict[str, dict] = {}


def get_version_json(pkg: str, version: str) -> dict:
    key = f"{pkg}@{version}"
    if key not in json_cache:
        url = f"https://pypi.org/pypi/{pkg}/{version}/json"
        last = None
        for attempt in range(6):
            try:
                with opener.open(url, timeout=30) as r:
                    json_cache[key] = json.load(r)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 + attempt)
        else:
            raise RuntimeError(f"获取元数据失败 {key}: {last}")
    return json_cache[key]


_WHEEL_RE = re.compile(r"^(?P<name>.+?)-(?P<ver>[^-]+)-(?P<rest>.+)\.whl$")


def rank_artifact(fname: str) -> int | None:
    """cp312 / linux x86_64 适配优先级；不适配返回 None。"""
    m = _WHEEL_RE.match(fname)
    if not m:
        return None
    parts = m.group("rest").split("-")
    pythons, plats = parts[0], "-".join(parts[2:])
    if not (("cp312" in pythons) or ("abi3" in pythons)
            or ("py3" in pythons) or ("py2.py3" in pythons)):
        return None
    if plats == "any":
        pr = 10
    elif "x86_64" in plats and ("manylinux" in plats or "linux_x86_64" in plats):
        pr = 25
        m2 = re.search(r"manylinux_2_(\d+)", plats)
        if m2:
            pr = 20 + min(int(m2.group(1)), 28)
        elif "manylinux2014" in plats:
            pr = 21
        elif "manylinux1" in plats:
            pr = 20
    else:
        return None
    pr += 3 if "cp312" in pythons else (2 if "abi3" in pythons else 1)
    return pr


def choose_version(pkg: str, specs: SpecifierSet) -> str:
    # 取包索引页
    if pkg not in json_cache:
        for attempt in range(6):
            try:
                with opener.open(f"https://pypi.org/pypi/{pkg}/json",
                                 timeout=30) as r:
                    json_cache[pkg] = json.load(r)
                break
            except Exception as e:  # noqa: BLE001
                time.sleep(2 + attempt)
        else:
            raise RuntimeError(f"无法获取 {pkg} 索引")
    releases = json_cache[pkg]["releases"]
    # OTel 等包常态发布 b1/rc 预发版；约束本身钉了预发号时必须放行
    pre_pinned = bool(re.search(r"(a|b|rc|dev)\d", str(specs)))

    def collect(allow_pre: bool):
        out = []
        for v, files in releases.items():
            try:
                ver = Version(v)
            except InvalidVersion:
                continue
            if not allow_pre and (ver.is_prerelease or ver.is_devrelease):
                continue
            if not specs.contains(v, prereleases=allow_pre):
                continue
            if not any(f.get("packagetype") == "bdist_wheel"
                       and rank_artifact(f["filename"]) is not None
                       for f in files):
                continue
            out.append(ver)
        return out

    candidates = collect(pre_pinned) or (collect(True) if not pre_pinned else [])
    if not candidates:
        raise RuntimeError(f"{pkg} 无满足 {specs} 的 cp312/linux wheel")
    return str(max(candidates))


def marker_ok(req: Requirement, active_extras: set[str]) -> bool:
    if req.marker is None:
        return True
    tries = [None] + sorted(active_extras)
    for ex in tries:
        env = dict(MENV)
        env["extra"] = ex or ""
        if req.marker.evaluate(env):
            return True
    return False


def resolve(pkg: str, specs: SpecifierSet, extras: set[str], depth: int = 0):
    rec = constraints.setdefault(pkg, {"specs": SpecifierSet(), "extras": set()})
    first_visit = "version" not in rec
    # 字符串交集合并（SpecifierSet 用逗号即 AND）
    merged = ",".join(p for p in (str(rec["specs"]), str(specs)) if p)
    combined = SpecifierSet(merged) if merged else SpecifierSet()
    need_walk = first_visit or (str(combined) != str(rec["specs"])) \
        or bool(extras - rec["extras"])
    rec["specs"] = combined
    rec["extras"] |= extras
    if not need_walk and depth > 0:
        return
    version = choose_version(pkg, combined)
    data = get_version_json(pkg, version)
    info = data["info"]
    rec["version"] = version
    for raw in (info.get("requires_dist") or []):
        try:
            dep = Requirement(raw)
        except Exception:  # noqa: BLE001
            continue
        if not marker_ok(dep, extras):
            continue
        resolve(dep.name, dep.specifier, set(dep.extras), depth + 1)


def select_file(pkg: str, version: str) -> dict:
    data = get_version_json(pkg, version)
    best = None
    for f in data["urls"]:
        if f.get("packagetype") != "bdist_wheel":
            continue
        r = rank_artifact(f["filename"])
        if r is None:
            continue
        if best is None or r > best[0]:
            best = (r, f)
    if best is None:
        raise RuntimeError(f"{pkg}=={version} 无适配 wheel")
    return best[1]


def download_resume(f: dict) -> str:
    fn, url = f["filename"], f["url"]
    expect_sha, expect_size = f["digests"]["sha256"], f["size"]
    path = os.path.join(DST, fn)
    for _full in range(3):
        for _attempt in range(40):
            have = os.path.getsize(path) if os.path.exists(path) else 0
            if have >= expect_size:
                break
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"})
            try:
                with opener.open(req, timeout=60) as r, open(path, "ab") as out:
                    while True:
                        chunk = r.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
            except Exception as e:  # noqa: BLE001
                print(f"    续传@{os.path.getsize(path) if os.path.exists(path) else 0}: "
                      f"{type(e).__name__} {str(e)[:80]}", flush=True)
                time.sleep(2)
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have != expect_size:
            print(f"  {fn} 尺寸不符 {have}/{expect_size}，重下", flush=True)
            os.remove(path)
            continue
        if hashlib.sha256(open(path, "rb").read()).hexdigest() == expect_sha:
            return path
        print(f"  {fn} sha256 不符，重下", flush=True)
        os.remove(path)
    raise RuntimeError(f"{fn} 下载失败")


def find_cpu_torch_file() -> dict:
    """从 PyTorch CPU 简索引找到 torch 版本对应的 cp312/linux x86_64 wheel。"""
    import urllib.parse as up
    with opener.open(f"{TORCH_CPU_INDEX}/torch/", timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    pat = re.compile(
        r'href="([^"]*?torch-' + re.escape(TORCH_VER)
        + r'(?:%2B|\+)cpu-cp312-cp312-[^"]*?x86_64\.whl)(?:#sha256=([0-9a-f]+))?"',
        re.IGNORECASE)
    found = []
    for href, sha in pat.findall(html):
        quoted = href.rsplit("/", 1)[-1]
        fn = up.unquote(quoted)
        if rank_artifact(fn) is None:
            continue
        url = href if href.startswith("http") else f"{TORCH_CPU_INDEX}/{quoted}"
        found.append((rank_artifact(fn), fn, url, sha or None))
    if not found:
        raise RuntimeError(f"CPU 索引无 torch {TORCH_VER} cp312 wheel")
    _, fn, url, sha = max(found, key=lambda x: x[0])
    # size 走 HEAD 取 Content-Length
    req = urllib.request.Request(url, method="HEAD")
    with opener.open(req, timeout=30) as r:
        size = int(r.headers.get("Content-Length", "0"))
    if not sha:  # 兜底：无 hash 时下载后仍能靠 pip 自身校验
        raise RuntimeError(f"{fn} 索引未提供 sha256")
    return {"filename": fn, "url": url, "size": size,
            "digests": {"sha256": sha}, "packagetype": "bdist_wheel"}


def seed_from_wheel(f: dict):
    """下载（或复用）一个 wheel，并按其 METADATA 把依赖加入闭包。"""
    path = os.path.join(DST, f["filename"])
    ok = (os.path.exists(path) and os.path.getsize(path) == f["size"]
          and hashlib.sha256(open(path, "rb").read()).hexdigest()
          == f["digests"]["sha256"])
    if not ok:
        print(f"下载 {f['filename']} ({f['size']/1e6:.0f}MB)", flush=True)
        download_resume(f)
    with zipfile.ZipFile(path) as z:
        mname = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")][0]
        meta_txt = z.read(mname).decode("utf-8", "replace")
    return [ln[len("Requires-Dist:"):].strip()
            for ln in meta_txt.splitlines() if ln.startswith("Requires-Dist:")]


def main():
    print(f"解析依赖闭包（cp312 / linux x86_64），torch={TORCH_VER}/{TORCH_FLAVOR}",
          flush=True)

    # ① torch：CPU 版从 PyTorch 索引取，CUDA 版走 PyPI
    if TORCH_FLAVOR == "cpu":
        tf = find_cpu_torch_file()
        tv = Version(tf["filename"].split("-")[1].split("+")[0]
                     ).base_version  # 2.14.1
        deps = seed_from_wheel(tf)
        rec = constraints.setdefault("torch",
                                     {"specs": SpecifierSet(f"=={tv}"),
                                      "extras": set()})
        rec["version"] = tf["filename"].split("-")[1]  # 2.14.1+cpu
        rec["file"] = tf
        for raw in deps:
            d = Requirement(raw)
            if marker_ok(d, set()):
                resolve(d.name, d.specifier, set(d.extras))
    else:
        resolve("torch", SpecifierSet(f"=={TORCH_VER}"), set())

    # ② requirements.txt 其余顶层依赖（torch 已播种，自动跳过）
    for line in open(REQUIREMENTS, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(" #", 1)[0].strip()
        try:
            req = Requirement(line)
        except Exception:  # noqa: BLE001
            continue
        if req.name.lower() == "torch":
            continue
        resolve(req.name, req.specifier, set(req.extras))

    chosen: dict[str, dict] = {}
    for pkg, rec in sorted(constraints.items()):
        if "file" in rec:  # 非 PyPI 来源（torch CPU）
            chosen[pkg] = rec["file"]
            print(f"  {pkg} {rec['specs'] or '(无约束)'} -> {rec['version']} (本地索引)")
            continue
        version = rec.get("version") or choose_version(pkg, rec["specs"])
        chosen[pkg] = select_file(pkg, version)
        print(f"  {pkg} {rec['specs'] or '(无约束)'} -> {version}")

    keep = {f["filename"] for f in chosen.values()}
    for stale in os.listdir(DST):
        if stale.endswith(".whl") and stale not in keep:
            print(f"裁剪闭包外旧 wheel: {stale}")
            os.remove(os.path.join(DST, stale))

    for pkg, f in chosen.items():
        path = os.path.join(DST, f["filename"])
        ok = (os.path.exists(path) and os.path.getsize(path) == f["size"]
              and hashlib.sha256(open(path, "rb").read()).hexdigest()
              == f["digests"]["sha256"])
        if ok:
            print(f"已有 {f['filename']}（校验通过）", flush=True)
        else:
            print(f"下载 {f['filename']} ({f['size']/1e6:.0f}MB)", flush=True)
            download_resume(f)
    print(f"闭包完成：{len(chosen)} 个包 -> {DST}")


if __name__ == "__main__":
    sys.exit(main())
