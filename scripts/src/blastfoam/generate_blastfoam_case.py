import numpy as np
from pathlib import Path
from typing import List, Tuple
import jinja2
from molmass import Formula

from src.config.setting import *

current_dir:Path = Path(__file__).parent
template_path:Path = current_dir / "templates"

env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_path))


# 生成初始目錄與檔案
def initBlastFileCreate():    
    with open(template_path / "comment.j2", mode="r", encoding="utf-8") as f:
        content = f.read()

        for directory in blastPath.keys():
            if directory in ("case_root_dir", "zero_dir", "constant_dir", "system_dir", "triSurface_dir"):
                Path(blastPath[directory]).mkdir(parents=True, exist_ok=True)
            elif directory == "case.stl":
                blastPath[directory].write_text("", encoding="utf-8")
            else:
                blastPath[directory].write_text(content, encoding="utf-8")

def write_template(j2_file_name: str, parameter: dict = None):
    try:
        template = env.get_template(f"{j2_file_name}.j2")
    except jinja2.exceptions.TemplateNotFound as e:
        print(f"錯誤：找不到模板檔案 {e}")
        return

    if parameter is None:
        content = template.render()
    else:
        content = template.render(parameter)

    with open(blastPath[j2_file_name], mode="w", encoding="utf-8") as f:
        f.write(content)

    print(f"> 成功寫入 {blastPathDict[j2_file_name]} 檔案並儲存至：{blastPath[j2_file_name]}")


## ------------------------------------------------------------------------ ##
# 0/ 目錄
# 0/U.orig
def gen_U(surf_id: List, case_name: str):
    parameter = {
        "open" : "",
        "inert": "",
        "case_name" : case_name
    }
    for value in surf_id:
        match value:
            case "OPEN":
                parameter["open"] = "OPEN"
            case "INERT":
                parameter["inert"] = "INERT"
    write_template("U", parameter)

# 0/alpha
def gen_alpha(spec_name_list: List[str], case_name: str):
    parameter = {
        "case_name" : case_name
    }
    write_template("alpha_air", parameter)
    for spec_name in spec_name_list:
        parameter = {
            "spec_name" : spec_name,
            "case_name" : case_name
        }
        write_template("alpha_explosive", parameter)

# 0/rho
def gen_rho(spec_name_list: List[str], case_name: str):
    parameter = {
        "case_name" : case_name
    }
    write_template("rho_air", parameter)
    for spec_name in spec_name_list:
        parameter = {
            "spec_name" : spec_name,
            "case_name" : case_name
        }
        write_template("rho_explosive", parameter)


## ------------------------------------------------------------------------ ##

# constant/ 目錄
# constant/triSurface/case.stl: 根據 &OBST 生成 
def gen_stl(obst_list:List, min_thickness=0.01):
    if not obst_list:
        raise ValueError("STL 轉換錯誤: OBST_list 為空，無法產生模型")
    
    faces = [
        [0, 3, 1], [1, 3, 2],  # 底面 Z1 (法向量 -Z)
        [4, 5, 7], [5, 6, 7],  # 頂面 Z2 (法向量 +Z)
        [0, 1, 5], [0, 5, 4],  # 前面 Y1 (法向量 -Y)
        [2, 3, 7], [2, 7, 6],  # 後面 Y2 (法向量 +Y)
        [1, 2, 6], [1, 6, 5],  # 右面 X2 (法向量 +X)
        [3, 0, 4], [3, 4, 7]   # 左面 X1 (法向量 -X)
    ]

    try:
        with open(blastPath["case.stl"], 'w', encoding='utf-8') as f_out:
            f_out.write("solid FDS_Model\n")
            
            for b in obst_list:
                x1, x2, y1, y2, z1, z2 = b
                
                # 校正厚度：確保 STL 可以合法產生 3D 模型
                if abs(x2 - x1) < min_thickness:
                    x1 -= min_thickness / 2.0
                    x2 += min_thickness / 2.0
                if abs(y2 - y1) < min_thickness:
                    y1 -= min_thickness / 2.0
                    y2 += min_thickness / 2.0
                if abs(z2 - z1) < min_thickness:
                    z1 -= min_thickness / 2.0
                    z2 += min_thickness / 2.0
                
                vertices = np.array([
                    [x1, y1, z1], [x2, y1, z1], [x2, y2, z1], [x1, y2, z1],
                    [x1, y1, z2], [x2, y1, z2], [x2, y2, z2], [x1, y2, z2]
                ], dtype=np.float64)

                for face in faces:
                    v0, v1, v2 = vertices[face[0]], vertices[face[1]], vertices[face[2]]
                    
                    normal = np.cross(v1 - v0, v2 - v0)
                    norm_length = np.linalg.norm(normal)
                    if norm_length > 0:
                        normal = normal / norm_length
                    else:
                        normal = np.array([0.0, 0.0, 0.0])

                    f_out.write(f"    facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n")
                    f_out.write(f"      outer loop\n")
                    f_out.write(f"        vertex {v0[0]:.6f} {v0[1]:.6f} {v0[2]:.6f}\n")
                    f_out.write(f"        vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}\n")
                    f_out.write(f"        vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}\n")
                    f_out.write(f"      endloop\n")
                    f_out.write(f"    endfacet\n")
                    
            f_out.write("endsolid FDS_Model\n")
    except (FileNotFoundError, PermissionError) as e:
            raise OSError(f"STL 寫入錯誤：無法在路徑 '{blastPath['case.stl']}' 建立檔案")
    except Exception as e:
            raise RuntimeError(f"STL 寫入錯誤，發生未知錯誤：{e}") from e
        
    print(f"> 成功寫入 constant/triSurface/case.stl 檔案並儲存至：{blastPath['case.stl']}")


# constant/dynamicMeshDict
def gen_dynamicMeshDict():
    write_template("dynamicMeshDict")


# constants/phaseProperties
def gen_phaseProperties(spec_name_list: List[str]):
    molmass_list = []
    for spec in spec_name_list:
        f = Formula(spec)
        molmass_list.append(round(f.mass, 3))

    spec_list = [(a, molmass_list[i]) for i, a in enumerate(spec_name_list)]

    parameter = {
        "spec_list": spec_list,
        "is_explosive" : ""
    }
    write_template("phaseProperties", parameter)

## ------------------------------------------------------------------------ ##

# system/ 目錄
# system/blockMeshDict: 根據 &MESH 生成 
def gen_blockMeshDict(mesh_xb: List[Tuple[float, float, float, float, float, float]], mesh_ijk: List[Tuple[float, float, float]]):
    if isinstance(mesh_ijk, tuple) and len(mesh_ijk) >= 3 and isinstance(mesh_ijk[0], (int, float)):
        mesh_ijk = [mesh_ijk]
    elif isinstance(mesh_ijk, list) and len(mesh_ijk) >= 3 and isinstance(mesh_ijk[0], (int, float)):
        mesh_ijk = [tuple(mesh_ijk)]
    if not mesh_ijk:
        mesh_ijk = [(1, 1, 1)]
    
    vertices = []
    vertex_map = {}
    
    def get_vid(x, y, z):
        key = (round(x, 4), round(y, 4), round(z, 4))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append(key)
        return vertex_map[key]

    blocks = []
    face_registry = {}
    
    global_z_min = float('inf')

    for idx, xb in enumerate(mesh_xb):
        x1, x2, y1, y2, z1, z2 = xb
        global_z_min = min(global_z_min, z1)
        
        current_ijk = mesh_ijk[idx] if idx < len(mesh_ijk) else mesh_ijk[-1]
        ni, nj, nk = int(current_ijk[0]), int(current_ijk[1]), int(current_ijk[2])
        
        v0 = get_vid(x1, y1, z1)
        v1 = get_vid(x2, y1, z1)
        v2 = get_vid(x2, y2, z1)
        v3 = get_vid(x1, y2, z1)
        v4 = get_vid(x1, y1, z2)
        v5 = get_vid(x2, y1, z2)
        v6 = get_vid(x2, y2, z2)
        v7 = get_vid(x1, y2, z2)
        
        v_list = [v0, v1, v2, v3, v4, v5, v6, v7]
        blocks.append({
            "vertices": v_list,
            "ijk": [ni, nj, nk]
        })
        
        faces = [
            (v0, v4, v7, v3), # x-min (左面)
            (v1, v2, v6, v5), # x-max (右面)
            (v0, v1, v5, v4), # y-min (前面)
            (v3, v7, v6, v2), # y-max (後面)
            (v0, v3, v2, v1), # z-min (底面)
            (v4, v5, v6, v7)  # z-max (頂面)
        ]
        
        for face in faces:
            sorted_key = tuple(sorted(face))
            if sorted_key in face_registry:
                face_registry[sorted_key]['count'] += 1
            else:
                face_registry[sorted_key] = {
                    'count': 1,
                    'face': face
                }

    boundaries = {
        "ground": {"type": "wall", "faces": []},
        "atmosphere": {"type": "patch", "faces": []}
    }
    
    for data in face_registry.values():
        if data['count'] == 1:
            face_vids = data['face']
            is_ground = all(vertices[vid][2] == global_z_min for vid in face_vids)
            
            if is_ground:
                boundaries["ground"]["faces"].append(face_vids)
            else:
                boundaries["atmosphere"]["faces"].append(face_vids)
                
    boundaries = {k: v for k, v in boundaries.items() if len(v["faces"]) > 0}

    content = {
        "vertices" : vertices,
        "blocks" : blocks,
        "boundaries" : boundaries
    }
    write_template("blockMeshDict", content)


# system/surfaceFeaturesDict
def gen_surfaceFeaturesDict(case_name: str):
    content = {
        "case_name" : case_name
    }
    write_template("surfaceFeaturesDict", content)


# system/decomposeParDict
def gen_decomposeParDict(core_num: int):
    content = {
        "core_num" : core_num
    }
    write_template("decomposeParDict", content)


# system/fvSchemes
def gen_fvSchemes():
    write_template("fvSchemes")


# system/fvSolution
def gen_fvSolution():
    write_template("fvSolution")
