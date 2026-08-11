import sys
from dataclasses import dataclass
from typing import Any, Callable, Union

from src.config.setting import initDirPath, MIN_THICKNESS, CORE_NUM
import src.blastfoam as blastfoam
import src.fds as fds

PROJECT_NAME = "minyung_blast"
CASE_NAME = "minyung_360s"


@dataclass
class Step:
    key: str                          
    label: str                        
    action: Union[Callable[[dict], Any], list[Callable[[dict], Any]]]
    critical: bool = False             


class Pipeline:
    def __init__(self, steps: list[Step]):
        self._steps = steps
        self.context: dict[str, Any] = {}

    def run(self) -> dict[str, Any]:
        total = len(self._steps)
        for i, step in enumerate(self._steps, start=1):
            print(f"[{i}/{total}] {step.label}")
            try:
                actions = step.action if isinstance(step.action, list) else [step.action]
                results = []                
                for idx, act_func in enumerate(actions, start=1):
                    res = act_func(self.context)
                    results.append(res)
                self.context[step.key] = results[0] if len(results) == 1 else results

            except Exception as e:
                print(f"[ERROR] {step.label} 失敗：{e}")
                if step.critical:
                    sys.exit(1)
                print(f"--> {step.label} 失敗（非關鍵步驟，繼續執行下一步）")
                continue

            print(f"--> {step.label} 成功")

        return self.context


def build_steps() -> list[Step]:
    return [
        Step(
            key="init_dir",
            label="Blastfoam 初始化目錄",
            action=lambda ctx: initDirPath(PROJECT_NAME, CASE_NAME),
            critical=True
        ),
        Step(
            key="init_blastfoam",
            label="創建 Blastfoam 目錄",
            action=lambda ctx: blastfoam.initBlastFileCreate(),
            critical=True
        ),
        Step(
            key="parse_fds",
            label="讀取 FDS",
            action=lambda ctx: fds.parseFDS(),
        ),
        Step(
            key="generate_blastfoam_0",
            label="寫入 blastfoam/0 初始檔案",
            action=[
                lambda ctx: blastfoam.gen_U(
                                surf_id=ctx["parse_fds"].VENT_SURF_ID,
                                case_name=CASE_NAME
                                ),
                lambda ctx: blastfoam.gen_alpha(
                                spec_name_list=ctx["parse_fds"].SPEC_ID,
                                case_name=CASE_NAME
                                ),
                lambda ctx: blastfoam.gen_rho(
                                spec_name_list=ctx["parse_fds"].SPEC_ID,
                                case_name=CASE_NAME
                                )
            ]
        ),
        Step(
            key="generate_blastfoam_constant",
            label="寫入 blastfoam/constant 初始檔案",
            action=[
                lambda ctx: blastfoam.gen_stl(
                            obst_list=ctx["parse_fds"].OBST_XB,
                            min_thickness=MIN_THICKNESS,
                            ),
                lambda ctx: blastfoam.gen_dynamicMeshDict(),
                lambda ctx: blastfoam.gen_phaseProperties(
                                spec_name_list=ctx["parse_fds"].SPEC_ID
                                )
            ]
        ),
        Step(
            key="generate_blastfoam_system",
            label="寫入 blastfoam/system 初始檔案",
            action=[
                lambda ctx: blastfoam.gen_blockMeshDict(
                            mesh_xb=ctx["parse_fds"].MESH_XB,
                            mesh_ijk=ctx["parse_fds"].MESH_IJK
                            ),
                lambda ctx: blastfoam.gen_surfaceFeaturesDict(
                            case_name=CASE_NAME
                            ),
                lambda ctx: blastfoam.gen_decomposeParDict(
                            core_num=CORE_NUM
                            ),
                lambda ctx: blastfoam.gen_fvSchemes(),
                lambda ctx: blastfoam.gen_fvSolution(),
            ]
        )
    ]

def main() -> None:
    Pipeline(build_steps()).run()

if __name__ == "__main__":
    main()