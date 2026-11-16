# -*- coding: utf-8 -*-
"""CAS 号 -> SMILES。

chem.py 保持纯 RDKit / 纯离线，所有联网查询都放在这里。只有输入长得像
CAS（如 64-17-5、7732-18-5）才会调用；命中 cas_cache.json 就不联网。

调用方必须把 resolve() 放进后台线程，别卡住 Tk 主线程。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

from paths import app_dir

HERE = app_dir()
CACHE_PATH = os.path.join(HERE, "cas_cache.json")
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
UA = "ELN/1.0 (local single-user)"
TIMEOUT = 8


def _clean(text: str) -> str:
    """允许 'CAS: 64-17-5' 这种写法。"""
    t = (text or "").strip().replace(" ", "")
    return re.sub(r"(?i)^cas[:#]?", "", t)


def is_cas(text: str) -> bool:
    return bool(CAS_RE.match(_clean(text)))


def _load() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass                      # 缓存写不了不影响主流程


def remember(cas: str, smiles: str, source: str):
    d = _load()
    d[_clean(cas)] = {"smiles": smiles, "source": source,
                      "ts": time.strftime("%Y-%m-%d %H:%M")}
    _save(d)


def _get(url: str, timeout: int = TIMEOUT) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA,
                      "Accept": "application/json, text/plain, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def from_cactus(cas: str) -> str | None:
    """NCI Cactus：一次请求直接返回 SMILES，最快。"""
    try:
        s = _get("https://cactus.nci.nih.gov/chemical/structure/"
                 + urllib.parse.quote(cas, safe="") + "/smiles").strip()
        if not s or s.startswith("<") or "\n" in s:
            return None
        return s
    except Exception:
        return None


def from_pubchem(cas: str) -> str | None:
    """PubChem PUG-REST 兜底，并尽量核对别名里确实有这个 CAS。"""
    try:
        q = urllib.parse.quote(cas, safe="")
        d = json.loads(_get(
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/" + q
            + "/property/SMILES,IsomericSMILES,Title/JSON"))
        p = (d.get("PropertyTable", {}).get("Properties") or [{}])[0]
        smi = p.get("SMILES") or p.get("IsomericSMILES")
        cid = p.get("CID")
        if not smi or not cid:
            return None
        try:
            syn = json.loads(_get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}"
                "/synonyms/JSON"))
            names = (syn.get("InformationList", {}).get("Information")
                     or [{}])[0].get("Synonym", [])
            if names and cas not in names:
                return None        # 疑似同名误配
        except Exception:
            pass                  # 别名接口挂了不否定主结果
        return smi
    except Exception:
        return None


def resolve(text: str, use_network: bool = True):
    """CAS -> (smiles, 来源/失败原因)。失败时 smiles 为 None。"""
    cas = _clean(text)
    if not is_cas(cas):
        return None, "不是 CAS 格式"
    hit = _load().get(cas)
    if hit and hit.get("smiles"):
        return hit["smiles"], "本地缓存"
    if not use_network:
        return None, "本地无缓存且未联网"
    smi = from_cactus(cas)
    if smi:
        remember(cas, smi, "Cactus")
        return smi, "NCI Cactus"
    smi = from_pubchem(cas)
    if smi:
        remember(cas, smi, "PubChem")
        return smi, "PubChem"
    return None, "在线库未收录或网络不通"
