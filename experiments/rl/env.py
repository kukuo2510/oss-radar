"""包裝 oss-radar 的 SQLite 資料表成一個最簡化的 Gymnasium 環境 —— 跟
HuBu/experiments/rl/env.py 是同一套模式，只是改成配合 oss-radar 實際擁有的資料欄位。

跟 HuBu 最關鍵的差異，也是這裡目前還沒辦法從真實使用者回饋學習的原因：
oss-radar 真正的獎勵訊號應該是使用者的按讚/略過點擊（見 src/db.py 的
`interactions` 表），但截至撰寫這份程式碼為止，總共只有 6 筆互動紀錄
（4 個讚、2 個略過）——遠遠不夠拿來訓練任何東西。相較之下，HuBu 的獎勵
（股票的未來報酬）可以直接從公開的股價歷史自動算出來，所以 HuBu 一開始
就免費擁有超過 17,000 筆帶標籤的訓練資料。

因此這裡改用 trend.py 算出來的百分位熱度分數，當作一個「替代獎勵」
（proxy reward）來訓練——邏輯是「如果當初把這個項目推薦出去，事後看它的熱度
表現，這個決定算不算合理」，而不是真正的使用者偏好。這是刻意、而且有清楚標示
的替代做法，不是偷偷藏起來的捷徑——可以參考 train.py 印出來的提示訊息。
等累積到足夠多的真實互動紀錄之後，再把 `_load_reward_proxy` 換成真正的
interactions 資料即可。

每一步（step）對應一筆項目（source, source_id），依 items.published_at 排序，
確保策略（policy）不會提前看到「未來」的資料。狀態（state）就是 src/embed.py
已經算好的 384 維 embedding 向量；動作（action）是離散的 {0: 略過, 1: 推薦}。
"""
import sqlite3
from pathlib import Path

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "oss_radar.db"
EMBEDDING_DIM = 384

ACTION_SKIP, ACTION_RECOMMEND = 0, 1


def load_panel(db_path: Path = DB_PATH, eval_holdout_frac: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """回傳 (train_df, eval_df)，依 published_at 時間切分，確保 eval 是真正沒被訓練
    看過的「未來」那一段資料。只有同時具備 embedding 與熱度分數的項目才會被納入
    （原因見本檔案開頭的模組說明）。
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            """
            SELECT i.source, i.source_id, i.published_at, e.vector, t.score AS trend_score
            FROM items i
            JOIN embeddings e ON e.source = i.source AND e.source_id = i.source_id
            JOIN trend_scores t ON t.source = i.source AND t.source_id = i.source_id
            """,
            conn,
        )
    df["vector"] = df["vector"].apply(lambda b: np.frombuffer(b, dtype="float32"))
    df = df.sort_values("published_at").reset_index(drop=True)

    split_idx = int(len(df) * (1 - eval_holdout_frac))
    return df.iloc[:split_idx].reset_index(drop=True), df.iloc[split_idx:].reset_index(drop=True)


def fit_normalizer(train_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """依訓練集算出每個 embedding 維度的平均值與標準差，供後續標準化觀測值使用。
    標準差為 0 的維度視為常數維度，改設為 1，避免除以 0。
    """
    stacked = np.stack(train_df["vector"].to_numpy())
    mean = stacked.mean(axis=0).astype(np.float32)
    std = stacked.std(axis=0)
    std[std == 0] = 1.0
    return mean, std.astype(np.float32)


class OssRadarRankingEnv(gym.Env):
    """逐列走訪 (項目, 熱度分數) 這個資料表；獎勵訊號是用熱度百分位分數，
    來代表「這個項目值不值得被推薦」，而不是真正的按讚/略過紀錄。
    """

    def __init__(self, panel: pd.DataFrame, feature_mean: np.ndarray, feature_std: np.ndarray):
        super().__init__()
        self.panel = panel.reset_index(drop=True)
        self.feature_mean = feature_mean
        self.feature_std = feature_std
        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(low=-10.0, high=10.0, shape=(EMBEDDING_DIM,), dtype=np.float32)
        self._i = 0

    def _state(self, row) -> np.ndarray:
        """把原始 embedding 向量標準化（減平均、除標準差）並裁切到 [-10, 10] 範圍內，
        避免極端值讓下游模型訓練不穩定。
        """
        return np.clip((row["vector"] - self.feature_mean) / self.feature_std, -10.0, 10.0).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._i = 0
        return self._state(self.panel.iloc[self._i]), {}

    def step(self, action: int):
        row = self.panel.iloc[self._i]
        # trend_score 原本落在 [0, 1]，這裡轉成以 0 為中心、範圍 [-1, 1] 的訊號：
        # 正值代表「值得推薦」、負值代表「不值得推薦」。
        signal = (float(row["trend_score"]) - 0.5) * 2
        # 選擇推薦（ACTION_RECOMMEND）時，獎勵跟 signal 同號；
        # 選擇略過時，獎勵則是 signal 的相反數——也就是說，
        # 略過一個熱度低的項目，或推薦一個熱度高的項目，都會拿到正獎勵。
        reward = signal if action == ACTION_RECOMMEND else -signal

        self._i += 1
        terminated = self._i >= len(self.panel)
        obs = self._state(self.panel.iloc[self._i]) if not terminated else np.zeros(EMBEDDING_DIM, dtype=np.float32)
        return obs, reward, terminated, False, {
            "source": row["source"], "source_id": row["source_id"], "trend_score": row["trend_score"],
        }
