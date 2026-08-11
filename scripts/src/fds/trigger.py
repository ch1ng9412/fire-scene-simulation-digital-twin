#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger("trigger")


DEFAULT_FUEL_LIBRARY: dict[str, dict[str, float]] = {
    # C40-P 有機過氧化物之簡化化學式；此處數值為近似估計，非官方量測值
    "C16H32O4": {
        "LEL": 0.6,
        "UEL": 6.0,
        "heat_of_combustion_kJ_per_kg": 25000.0,
        "autoignition_K": 615.0,
    },
    "CH4": {
        "LEL": 5.0,
        "UEL": 15.0,
        "heat_of_combustion_kJ_per_kg": 50000.0,
        "autoignition_K": 810.0,
    },
    "CO": {
        "LEL": 12.5,
        "UEL": 74.0,
        "heat_of_combustion_kJ_per_kg": 10100.0,
        "autoignition_K": 882.0,
    },
}

DEFAULT_O2_THRESHOLD_PCT = 12.0
DEFAULT_MIN_TRIGGER_VOLUME_M3 = 0.5
DEFAULT_MIN_CONSECUTIVE_STEPS = 3
DEFAULT_SCREENING_INTERVAL_S = 1.0

def _find_project_root(
    start: Optional[Path] = None,
    markers: Sequence[str] = (".git", "mingyang_project.yaml", "pyproject.toml", "requirements.txt"),
) -> Path:
    """從 `start`（預設為本檔案所在目錄）向上尋找標記檔案/目錄，找到就回傳該層。
    找不到任何標記時退回 `start` 本身，確保永遠有一個可用的根目錄，不會崩潰。
    """
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if any((candidate / m).exists() for m in markers):
            return candidate
    return here


def _resolve_path(value: "str | Path", base: Path) -> Path:
    """把 `value` 解析為絕對路徑；若已是絕對路徑則直接回傳，否則相對 `base` 解析。"""
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def _latest_matching_dir(pattern_root: Path, glob: str = "*") -> Optional[Path]:
    """回傳 `pattern_root` 底下最近修改時間的子目錄，用來自動銜接上游 Step
    （例如「跑 FDS」的 Step）最新產生的案例目錄，不需要寫死案例名稱。
    """
    if not pattern_root.exists():
        return None
    candidates = sorted(
        (p for p in pattern_root.glob(glob) if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


@dataclass
class ReaderHooks:
    """可注入的 I/O 後端。刻意留成 callable 而非直接 import，理由：
        1. scripts/read_smv.py、scripts/read_plot3d.py 尚未寫好前，trigger.py
           仍要能被 import 與單元測試，不能因為缺檔案而整支腳本壞掉。
        2. 測試時可以塞入 mock 版本，不必真的跑 FDS 也能測 Stage 4/5/6 的邏輯。
    """
    read_smv: Optional[Callable[[Path], dict]] = None
    read_plot3d: Optional[Callable[[Path, Path, dict], "list[PLOT3DFrame]"]] = None
    read_devc_csv: Optional[Callable[[Path], "pd.DataFrame"]] = None


@dataclass
class TriggerConfig:
    """trigger.py 的中央設定物件，由 load_config() 產生。"""

    project_root: Path
    fds_cases_root: Path
    fds_case_dir: Optional[Path]
    fds_chid: str
    blastfoam_data_dir: Path
    trigger_json_path: Path
    tnt_params_json_path: Path

    fuel_species: str
    fuel_library: dict = field(default_factory=lambda: dict(DEFAULT_FUEL_LIBRARY))
    o2_threshold_pct: float = DEFAULT_O2_THRESHOLD_PCT
    min_trigger_volume_m3: float = DEFAULT_MIN_TRIGGER_VOLUME_M3
    min_consecutive_steps: int = DEFAULT_MIN_CONSECUTIVE_STEPS
    screening_interval_s: float = DEFAULT_SCREENING_INTERVAL_S
    # 若為 None，執行時由 PLOT3D frame 的 mesh 間距自動推算，不需事先知道網格解析度
    grid_cell_volume_m3: Optional[float] = None

    reader_hooks: ReaderHooks = field(default_factory=ReaderHooks)

    @property
    def fuel_params(self) -> dict:
        try:
            return self.fuel_library[self.fuel_species]
        except KeyError as exc:
            raise KeyError(
                f"燃料 '{self.fuel_species}' 不在 fuel_library 中，"
                f"可用項目：{list(self.fuel_library)}。"
                " 請在 config.yaml 的 fuel_library 區塊補上該物質的 LEL/UEL/自燃溫度，"
                " 建議來源：NFPA 86 或該化學品之 SDS。"
            ) from exc


def load_config(
    config_path: Optional["str | Path"] = None,
    *,
    project_root: Optional["str | Path"] = None,
    overrides: Optional[dict[str, Any]] = None,
    reader_hooks: Optional[ReaderHooks] = None,
) -> TriggerConfig:
    
    env_root = os.environ.get("MINGYANG_PROJECT_ROOT")
    root = Path(project_root) if project_root else (Path(env_root) if env_root else _find_project_root())
    root = root.resolve()

    merged: dict[str, Any] = {
        "fds_cases_root": "fds/cases",
        "fds_case_dir": None,  # 若仍為 None，稍後自動偵測最新案例目錄
        "fds_chid": "0928minyung",
        "blastfoam_data_dir": "data",
        "fuel_species": "C16H32O4",
        "fuel_library": dict(DEFAULT_FUEL_LIBRARY),
        "o2_threshold_pct": DEFAULT_O2_THRESHOLD_PCT,
        "min_trigger_volume_m3": DEFAULT_MIN_TRIGGER_VOLUME_M3,
        "min_consecutive_steps": DEFAULT_MIN_CONSECUTIVE_STEPS,
        "screening_interval_s": DEFAULT_SCREENING_INTERVAL_S,
        "grid_cell_volume_m3": None,
    }

    # --- layer 2: YAML 檔（選用）---------------------------------------------------
    if config_path is not None:
        resolved_config_path = _resolve_path(config_path, root)
        if not resolved_config_path.exists():
            raise FileNotFoundError(f"找不到設定檔：{resolved_config_path}")
        import yaml  # 延後 import，沒用到 YAML 時不強制要求安裝 PyYAML

        with open(resolved_config_path, "r", encoding="utf-8") as fh:
            yaml_data = yaml.safe_load(fh) or {}
        merged.update({k: v for k, v in yaml_data.items() if v is not None})

    # --- layer 3: 環境變數 TRIGGER_* -----------------------------------------------
    env_map = {
        "TRIGGER_FDS_CASE_DIR": "fds_case_dir",
        "TRIGGER_FDS_CHID": "fds_chid",
        "TRIGGER_BLASTFOAM_DATA_DIR": "blastfoam_data_dir",
        "TRIGGER_FUEL_SPECIES": "fuel_species",
        "TRIGGER_O2_THRESHOLD_PCT": "o2_threshold_pct",
        "TRIGGER_MIN_TRIGGER_VOLUME_M3": "min_trigger_volume_m3",
        "TRIGGER_MIN_CONSECUTIVE_STEPS": "min_consecutive_steps",
        "TRIGGER_SCREENING_INTERVAL_S": "screening_interval_s",
    }
    for env_key, field_name in env_map.items():
        if env_key in os.environ:
            merged[field_name] = os.environ[env_key]

    # --- layer 4: 執行期覆寫（Pipeline 串接的關鍵入口）------------------------------
    if overrides:
        merged.update(overrides)

    # --- 數值欄位型別校正（YAML/環境變數帶進來的可能是字串）--------------------------
    for numeric_field in (
        "o2_threshold_pct",
        "min_trigger_volume_m3",
        "min_consecutive_steps",
        "screening_interval_s",
        "grid_cell_volume_m3",
    ):
        v = merged.get(numeric_field)
        if isinstance(v, str):
            merged[numeric_field] = float(v)
    if merged.get("min_consecutive_steps") is not None:
        merged["min_consecutive_steps"] = int(merged["min_consecutive_steps"])

    # --- 路徑解析 --------------------------------------------------------------
    fds_cases_root = _resolve_path(merged["fds_cases_root"], root)
    blastfoam_data_dir = _resolve_path(merged["blastfoam_data_dir"], root)

    fds_case_dir_raw = merged.get("fds_case_dir")
    if fds_case_dir_raw:
        fds_case_dir = _resolve_path(fds_case_dir_raw, root)
    else:
        # 路徑銜接重點：沒有明確指定時，自動抓 fds/cases/ 底下最新的案例目錄，
        # 讓上游「跑 FDS」的 Step 不需要知道 trigger.py 的設定細節。
        fds_case_dir = _latest_matching_dir(fds_cases_root)
        if fds_case_dir is None:
            logger.warning(
                "在 %s 底下找不到任何案例目錄；fds_case_dir 暫時留空，"
                "main_controller() 執行時若仍找不到會直接報錯。",
                fds_cases_root,
            )

    blastfoam_data_dir.mkdir(parents=True, exist_ok=True)
    trigger_json_path = blastfoam_data_dir / "trigger.json"
    tnt_params_json_path = blastfoam_data_dir / "tnt_params.json"

    cfg = TriggerConfig(
        project_root=root,
        fds_cases_root=fds_cases_root,
        fds_case_dir=fds_case_dir,
        fds_chid=str(merged["fds_chid"]),
        blastfoam_data_dir=blastfoam_data_dir,
        trigger_json_path=trigger_json_path,
        tnt_params_json_path=tnt_params_json_path,
        fuel_species=str(merged["fuel_species"]),
        fuel_library=merged["fuel_library"],
        o2_threshold_pct=float(merged["o2_threshold_pct"]),
        min_trigger_volume_m3=float(merged["min_trigger_volume_m3"]),
        min_consecutive_steps=int(merged["min_consecutive_steps"]),
        screening_interval_s=float(merged["screening_interval_s"]),
        grid_cell_volume_m3=merged.get("grid_cell_volume_m3"),
        reader_hooks=reader_hooks or ReaderHooks(),
    )
    logger.info(
        "設定載入完成：project_root=%s, fds_case_dir=%s, fuel=%s",
        cfg.project_root, cfg.fds_case_dir, cfg.fuel_species,
    )
    return cfg


def read_devc_screening(
    csv_path: Path,
    config: TriggerConfig,
    time_window: Optional[tuple[float, float]] = None,
) -> tuple[bool, "pd.DataFrame"]:
    """讀取 FDS `_devc.csv`，做第一層輕量化過濾。

    Returns
    -------
    (is_potential_hazard, devc_df)
        is_potential_hazard: 任一可燃氣體監測點濃度達 LEL 安全裕度（80%）以上時為 True，
            代表值得進一步花成本做 3D 場解析；否則 False，讓 FDS 直接跑下一個時間步。
        devc_df: 完整監測時序 DataFrame（索引為時間），供除錯或繪圖使用。
    """
    hook = config.reader_hooks.read_devc_csv
    if hook is not None:
        df = hook(csv_path)
    else:
        # FDS 的 _devc.csv 第一列是 quantity 名稱、第二列才是欄位名稱
        df = pd.read_csv(csv_path, header=1)
        df = df.rename(columns={df.columns[0]: "Time"}).set_index("Time")

    if time_window is not None:
        lo, hi = time_window
        df = df.loc[(df.index >= lo) & (df.index <= hi)]

    fuel_cols = [c for c in df.columns if c.lower().startswith("fuel_")]
    if not fuel_cols:
        logger.warning("devc.csv 中找不到任何 fuel_* 欄位，快篩略過，強制進入深度解析以策安全。")
        return True, df
    if df.empty:
        return False, df

    lel_vol_pct = config.fuel_params["LEL"]
    safety_margin = 0.8  # 在到達 LEL 之前提早觸發深度檢查，避免取樣頻率錯過瞬間峰值
    threshold = lel_vol_pct * safety_margin

    latest = df[fuel_cols].iloc[-1]
    is_potential_hazard = bool((latest >= threshold).any())
    return is_potential_hazard, df


@dataclass
class PLOT3DFrame:
    """單一 mesh、單一時間點的 5 大 PLOT3D 場資料。"""
    time: float
    mesh_id: str
    temperature: np.ndarray          # K
    fuel_volume_fraction: np.ndarray  # 體積分率 (0–1)
    o2_volume_fraction: np.ndarray    # 體積分率 (0–1)
    pressure: np.ndarray              # Pa
    hrrpuv: np.ndarray                # kW/m^3
    cell_volume_m3: float
    origin_xyz: tuple[float, float, float]
    spacing_xyz: tuple[float, float, float]


def read_plot3d_fields(
    smv_path: Path,
    data_dir: Path,
    target_time: float,
    config: TriggerConfig,
) -> "list[PLOT3DFrame]":
    """深度三維場解析（Stage 3）。

    絕不自行手寫二進位解析器；優先順序：
        1. config.reader_hooks.read_plot3d（例如注入 scripts/read_plot3d.py 的實作）
        2. fdsreader 套件（fallback）
        3. 兩者皆無時直接丟出清楚的錯誤，而不是靜默回傳空結果
    """
    hook = config.reader_hooks.read_plot3d
    if hook is not None:
        smv_meta = config.reader_hooks.read_smv(smv_path) if config.reader_hooks.read_smv else {}
        return hook(smv_path, data_dir, {"target_time": target_time, "smv_meta": smv_meta})

    try:
        import fdsreader  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "read_plot3d_fields 需要 scripts/read_plot3d.py 的注入版本，"
            "或安裝 fdsreader 作為 fallback（pip install fdsreader --break-system-packages）。"
            "目前兩者皆不可用。"
        ) from exc

    sim = fdsreader.Simulation(str(data_dir))
    frames: "list[PLOT3DFrame]" = []
    for mesh in sim.meshes:
        pl3d = mesh.plot3ds.get_nearest(target_time)
        if pl3d is None:
            continue
        data = pl3d.data  # 預期 shape: (5, Ni, Nj, Nk)，順序 T / Fuel / O2 / P / HRRPUV
        n_i, n_j, n_k = data.shape[1:]
        mins, maxs = mesh.extent.mins, mesh.extent.maxs
        spacing = (
            (maxs[0] - mins[0]) / max(n_i - 1, 1),
            (maxs[1] - mins[1]) / max(n_j - 1, 1),
            (maxs[2] - mins[2]) / max(n_k - 1, 1),
        )
        cell_vol = float(spacing[0] * spacing[1] * spacing[2])
        frames.append(
            PLOT3DFrame(
                time=target_time,
                mesh_id=str(mesh.id),
                temperature=data[0],
                fuel_volume_fraction=data[1],
                o2_volume_fraction=data[2],
                pressure=data[3],
                hrrpuv=data[4],
                cell_volume_m3=cell_vol,
                origin_xyz=tuple(mins),
                spacing_xyz=spacing,
            )
        )
    if not frames:
        raise RuntimeError(f"在 target_time={target_time}s 附近找不到任何 PLOT3D frame（data_dir={data_dir}）")
    return frames


def _burgess_wheeler_correction(
    lel_298: float,
    uel_298: float,
    heat_of_combustion_kJ_per_kg: float,
    temperature_field_K: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Burgess-Wheeler 定律：依溫度動態修正 LEL/UEL（皆為體積百分比 vol%）。

    注意：UEL 的修正式文獻上並無如 LEL 般廣泛驗證的標準公式，此處採對稱外推
    作為工程級近似（隨溫度同比例放寬上限）。正式使用前請以文獻或實驗數據核實，
    並在期末報告中註明此為簡化假設。
    """
    delta_t = temperature_field_K - 298.0
    lel_t = lel_298 * (1.0 - 0.75 / heat_of_combustion_kJ_per_kg * delta_t)
    uel_t = uel_298 * (1.0 + 0.75 / heat_of_combustion_kJ_per_kg * delta_t)
    return np.clip(lel_t, a_min=0.0, a_max=None), uel_t


def evaluate_explosion_criteria(
    frame: PLOT3DFrame,
    config: TriggerConfig,
) -> tuple[bool, np.ndarray]:
    """Stage 4 — 爆炸臨界條件判定。

    三要件：可燃氣體濃度（溫度修正後）落在 [LEL_T, UEL_T]、O2 ≥ 門檻、
    溫度達自燃門檻或鄰近網格有明火（HRRPUV > 0）。再以連通體積 ≥
    min_trigger_volume_m3 做空間濾波，剔除單點數值雜訊造成的偽觸發。

    Returns
    -------
    (is_triggered, mask)
        mask 與 frame 場同形狀的布林陣列，標記出通過所有檢驗的網格。
    """
    fuel = config.fuel_params
    lel_t, uel_t = _burgess_wheeler_correction(
        lel_298=fuel["LEL"],
        uel_298=fuel["UEL"],
        heat_of_combustion_kJ_per_kg=fuel["heat_of_combustion_kJ_per_kg"],
        temperature_field_K=frame.temperature,
    )
    fuel_pct = frame.fuel_volume_fraction * 100.0
    o2_pct = frame.o2_volume_fraction * 100.0

    concentration_ok = (fuel_pct >= lel_t) & (fuel_pct <= uel_t)
    oxygen_ok = o2_pct >= config.o2_threshold_pct
    ignition_ok = (frame.temperature >= fuel["autoignition_K"]) | (frame.hrrpuv > 0.0)

    raw_mask = concentration_ok & oxygen_ok & ignition_ok
    if not raw_mask.any():
        return False, raw_mask

    from scipy import ndimage  # 延後 import，未觸發時不需要 scipy 也能跑

    labeled, n_labels = ndimage.label(raw_mask)
    cell_vol = config.grid_cell_volume_m3 or frame.cell_volume_m3
    keep_mask = np.zeros_like(raw_mask)
    for label_id in range(1, n_labels + 1):
        region = labeled == label_id
        region_volume = float(region.sum()) * cell_vol
        if region_volume >= config.min_trigger_volume_m3:
            keep_mask |= region

    return bool(keep_mask.any()), keep_mask


def integrate_combustible_mass(
    mask: np.ndarray,
    frame: PLOT3DFrame,
    config: TriggerConfig,
) -> dict[str, Any]:
    """Stage 5 — 對 mask 範圍內的燃料做質量積分，並求出質心座標與背景熱力狀態。

    以理想氣體方程式由溫度、壓力反算局部密度（以空氣分子量近似，供工程級初估）。
    """
    R_SPECIFIC = 287.0  # J/(kg·K)，空氣比氣體常數近似值
    cell_vol = config.grid_cell_volume_m3 or frame.cell_volume_m3

    if not mask.any():
        raise ValueError("integrate_combustible_mass 收到空的 mask，請先確認 evaluate_explosion_criteria 的結果。")

    rho = frame.pressure / (R_SPECIFIC * frame.temperature)  # kg/m^3
    fuel_mass_per_cell = np.where(mask, frame.fuel_volume_fraction * rho * cell_vol, 0.0)
    fuel_mass_kg = float(fuel_mass_per_cell.sum())

    idx = np.argwhere(mask)
    weights = fuel_mass_per_cell[mask]
    if weights.sum() <= 0:
        weights = np.ones_like(weights)  # 極端情況下質量積分為 0，退化為幾何質心

    ox, oy, oz = frame.origin_xyz
    sx, sy, sz = frame.spacing_xyz
    coords_xyz = np.stack(
        [ox + idx[:, 0] * sx, oy + idx[:, 1] * sy, oz + idx[:, 2] * sz],
        axis=1,
    )
    centroid = np.average(coords_xyz, axis=0, weights=weights)

    return {
        "fuel_mass_kg": fuel_mass_kg,
        "xyz_explosion": [float(c) for c in centroid],
        "T_ambient": float(frame.temperature[mask].mean()),
        "p_ambient": float(frame.pressure[mask].mean()),
        "n_cells_triggered": int(mask.sum()),
    }


def export_trigger_payload(
    t_explosion: float,
    integration_result: dict[str, Any],
    config: TriggerConfig,
) -> Path:
    """Stage 6 — 打包並寫出 trigger.json，作為與 BlastFOAM/Abaqus 交接的唯一憑證。"""
    payload = {
        "t_explosion": t_explosion,
        "xyz_explosion": integration_result["xyz_explosion"],
        "T_ambient": integration_result["T_ambient"],
        "p_ambient": integration_result["p_ambient"],
        "fuel_mass_kg": integration_result["fuel_mass_kg"],
        "fuel_species": config.fuel_species,
        "n_cells_triggered": integration_result["n_cells_triggered"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config_snapshot": {
            "o2_threshold_pct": config.o2_threshold_pct,
            "min_trigger_volume_m3": config.min_trigger_volume_m3,
            "min_consecutive_steps": config.min_consecutive_steps,
        },
    }
    config.trigger_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("已寫出 trigger.json → %s", config.trigger_json_path)
    return config.trigger_json_path


@dataclass
class ConsecutiveTracker:
    """追蹤「連續達到條件」的時間步數，避免單一時間點的雜訊被誤判為引爆。"""
    required_steps: int
    _count: int = field(default=0, init=False, repr=False)
    _last_mask: Optional[np.ndarray] = field(default=None, init=False, repr=False)

    def update(self, triggered: bool, mask: Optional[np.ndarray]) -> bool:
        if triggered:
            self._count += 1
            self._last_mask = mask
        else:
            self._count = 0
            self._last_mask = None
        return self._count >= self.required_steps

    @property
    def last_mask(self) -> Optional[np.ndarray]:
        return self._last_mask


def main_controller(
    config: TriggerConfig,
    *,
    live: bool = False,
    poll_interval_s: Optional[float] = None,
) -> Optional[Path]:
    """Stage 2–6 的總協調者。

    Parameters
    ----------
    live:
        True  — 假設 FDS 正在背景運算，持續輪詢 devc.csv 的新資料（適合正式
                3600s 模擬，搭配 run_pipeline.sh 常駐執行）。
        False — 對一份已跑完的 devc.csv 做批次回放（適合驗證 300s 短測試，
                或做單元測試）。
    poll_interval_s:
        live 模式下的輪詢間隔；預設沿用 config.screening_interval_s。

    Returns
    -------
    寫出的 trigger.json 路徑；若整段資料都未觸發爆炸條件則回傳 None。
    """
    if config.fds_case_dir is None:
        raise FileNotFoundError(
            "fds_case_dir 未設定且自動偵測失敗，請確認 fds/cases/ 底下是否已有 FDS 輸出，"
            "或呼叫 load_config(overrides={'fds_case_dir': ...}) 手動指定。"
        )

    output_dir = config.fds_case_dir / "output"
    csv_path = output_dir / f"{config.fds_chid}_devc.csv"
    smv_path = output_dir / f"{config.fds_chid}.smv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 devc.csv：{csv_path}")

    tracker = ConsecutiveTracker(required_steps=config.min_consecutive_steps)
    poll_interval_s = poll_interval_s if poll_interval_s is not None else config.screening_interval_s
    seen_times: set[float] = set()

    while True:
        _, devc_df = read_devc_screening(csv_path, config)
        new_times = sorted(t for t in devc_df.index if t not in seen_times)

        for t in new_times:
            seen_times.add(t)
            step_hazard, _ = read_devc_screening(csv_path, config, time_window=(t, t))
            if not step_hazard:
                tracker.update(False, None)
                continue

            frames = read_plot3d_fields(smv_path, output_dir, t, config)

            triggered_this_step = False
            chosen_frame: Optional[PLOT3DFrame] = None
            for frame in frames:
                is_triggered, mask = evaluate_explosion_criteria(frame, config)
                if is_triggered:
                    triggered_this_step = True
                    chosen_frame = frame
                    tracker.update(True, mask)
                    break
            if not triggered_this_step:
                tracker.update(False, None)
                continue

            if tracker._count >= config.min_consecutive_steps and chosen_frame is not None:
                logger.info("爆炸條件於 t=%.1fs 確認成立（已連續 %d 步）", t, config.min_consecutive_steps)
                integration_result = integrate_combustible_mass(tracker.last_mask, chosen_frame, config)
                return export_trigger_payload(t, integration_result, config)

        if not live:
            break
        time.sleep(poll_interval_s)

    logger.info("整段資料掃描完畢，未達到爆炸觸發條件。")
    return None

# CLI 入口
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FDS → BlastFOAM 爆炸觸發偵測 (trigger.py)")
    parser.add_argument("--config", type=str, default=None, help="config.yaml 路徑（可省略）")
    parser.add_argument("--project-root", type=str, default=None, help="專案根目錄（可省略，自動偵測）")
    parser.add_argument("--fds-case-dir", type=str, default=None, help="覆寫 FDS 案例目錄")
    parser.add_argument("--fds-chid", type=str, default=None, help="覆寫 FDS CHID")
    parser.add_argument("--fuel-species", type=str, default=None, help="覆寫燃料物種代號")
    parser.add_argument("--live", action="store_true", help="持續輪詢模式（正式 3600s 模擬時使用）")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    args = _build_arg_parser().parse_args()

    overrides = {
        k: v
        for k, v in {
            "fds_case_dir": args.fds_case_dir,
            "fds_chid": args.fds_chid,
            "fuel_species": args.fuel_species,
        }.items()
        if v is not None
    }

    config = load_config(args.config, project_root=args.project_root, overrides=overrides)
    result = main_controller(config, live=args.live)
    if result is None:
        raise SystemExit(1)  # 非零結束碼，方便 run_pipeline.sh 判斷「本次未觸發爆炸」


if __name__ == "__main__":
    main()
