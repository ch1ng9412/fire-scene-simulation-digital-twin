import re
from dataclasses import dataclass
from typing import List, Tuple, Optional
from src.config.setting import *

@dataclass
class FDSParseData:
    OBST_XB: List[Tuple[float, ...]]
    MESH_XB: List[Tuple[float, ...]]
    MESH_IJK:  List[Tuple[float, ...]]
    VENT_SURF_ID: List[str]
    SPEC_ID: List[str]

# 讀取 FDS 提取關鍵字
def parseFDS(fds_path: Optional[str] = None) -> FDSParseData:
    if fds_path is None:
        fds_path = fdsPath["fds"]
    
    _NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
    _RECORD_PATTERN = re.compile(r"&(OBST|MESH|VENT|SPEC)\b(.*?)/", re.IGNORECASE | re.DOTALL)
    _COMMENT_PATTERN = re.compile(r"!.*")

    # &OBST, &MESH
    _XB_PATTERN = re.compile(r"XB\s*=\s*" + r"\s*,\s*".join([f"({_NUM})"] * 6))
    _JIK_PATTERN = re.compile(r"IJK\s*=\s*" + r"\s*,\s*".join([f"({_NUM})"] * 3))

    # &VENT
    _SURF_ID = re.compile(r"SURF_ID\s*=\s*'([^']+)'", re.IGNORECASE)

    # &SPEC
    _SPEC_ID = re.compile(r"ID\s*=\s*'([^']+)'", re.IGNORECASE)

    try:
        with open(fds_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (FileNotFoundError, IsADirectoryError) as e:
        raise FileNotFoundError(f"FDS 讀取錯誤：找不到檔案 '{fds_path}'") from e
    except OSError as e:
        raise RuntimeError(f"FDS 讀取錯誤，發生未知錯誤：{e}") from e
    
    content = _COMMENT_PATTERN.sub("", content)
    obst_xb, mesh_xb, mesh_ijk, surf_id, spec_id = [], [], [], [], []

    for group_name, body in _RECORD_PATTERN.findall(content):
        xb_match = _XB_PATTERN.search(body)
        if xb_match:
            xb_box = tuple(float(v) for v in xb_match.groups())
            match group_name.upper():
                case "OBST":
                    obst_xb.append(xb_box)
                case "MESH":
                    mesh_xb.append(xb_box)
                    ijk_match = _JIK_PATTERN.search(body)
                    ijk_box = tuple(float(v) for v in ijk_match.groups())
                    mesh_ijk.append(ijk_box)
                case "VENT":
                    surf_id_match = _SURF_ID.search(body)
                    surf_id_box = surf_id_match.group(1)
                    if surf_id_box not in surf_id:
                        surf_id.append(surf_id_box)
        else:
            match group_name.upper():
                case "SPEC":
                    spec_id_match = _SPEC_ID.search(body)
                    spec_id_box = spec_id_match.group(1)
                    if spec_id_box not in spec_id:
                        spec_id.append(spec_id_box)


    print(f"> 成功讀取了 {len(obst_xb)} 個 &OBST")
    print(f"> 成功讀取了 {len(mesh_xb)} 個 &MESH")
    print(f"> 成功讀取了 {len(surf_id)} 個 &VENT")
    print(f"> 成功讀取了 {len(spec_id)} 個 &SPEC")
    return FDSParseData(
            OBST_XB=obst_xb, 
            MESH_XB=mesh_xb, 
            MESH_IJK=mesh_ijk,
            VENT_SURF_ID=surf_id,
            SPEC_ID=spec_id,
        )

def main():
    fdsParse = parseFDS()
    print(fdsParse.SPEC_ID)
    print(fdsParse.VENT_SURF_ID)

if __name__ == "__main__":
    initDirPath("minyung_blast", "minyung_360s")
    main()