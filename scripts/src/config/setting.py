import os
from pathlib import Path
from typing import Final

# 定義路徑
PROJECT_ROOT:Final[Path] = Path(__file__).parents[3]
BLASTFOAM_PATH:Final[Path] = PROJECT_ROOT / "blastfoam"
FDS_PATH:Final[Path] = PROJECT_ROOT / "fds"

# case.stl: 預設把零厚度的物件增厚 0.01 公尺，可自行根據網格解析度調整
MIN_THICKNESS = 0.01

# decomposeParDict: 平行運算的核心數，預設為 4
CORE_NUM:int = 4

blastPathDict = {
    "case_root_dir" : "",
    "Allrun" : "Allrun",
    "Allclean" : "Allclean",
    "zero_dir" : "0",
    "constant_dir" : "constant",
    "system_dir" : "system",
    "T" : "0/T.orig",
    "U" : "0/U.orig",
    "p" : "0/p.orig",
    "alpha_explosive" : "0/alpha.C16H32O4.orig",
    "alpha_air" : "0/alpha.air.orig",
    "rho_explosive" : "0/rho.C16H32O4.orig",
    "rho_air" : "0/rho.air.orig",
    "dynamicMeshDict" : "constant/dynamicMeshDict",
    "phaseProperties" : "constant/phaseProperties",
    "triSurface_dir" : "constant/triSurface",
    "case.stl" : "constant/triSurface",
    "blockMeshDict" : "system/blockMeshDict",
    "controlDict" : "system/controlDict",
    "decomposeParDict" : "system/decomposeParDict",
    "fvSchemes" : "system/fvSchemes",
    "fvSolution" : "system/fvSolution",
    "setFieldsDict" : "system/setFieldsDict",
    "snappyHexMeshDict" : "system/snappyHexMeshDict",
    "surfaceFeaturesDict" : "system/surfaceFeaturesDict",
}

blastPath = {}
fdsPath = {}

def initDirPath(blastfoam_dir_path:Path, fds_dir_path:Path = None):
    for key, rel_path in blastPathDict.items():
        if key == "case.stl":
            stl_name = f"{blastfoam_dir_path}.stl"
            blastPath[key] = BLASTFOAM_PATH / blastfoam_dir_path / rel_path / stl_name
        else:
            blastPath[key] = BLASTFOAM_PATH / blastfoam_dir_path / rel_path
    
    if fds_dir_path:
        fds_dir_path_str = str(fds_dir_path)
        fdsPath["fds_dir"] = FDS_PATH / fds_dir_path
        fdsPath["fds"] = FDS_PATH / fds_dir_path / f"{fds_dir_path_str}.fds"