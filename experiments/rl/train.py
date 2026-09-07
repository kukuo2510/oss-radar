"""在 OssRadarRankingEnv 上訓練一個 PPO 策略，並拿它跟兩個「傻瓜基準」
（永遠略過、永遠推薦）在一段沒被訓練看過的「未來」日期範圍上比較表現。

執行方式（在 oss-radar/experiments/rl/ 底下，用它自己的 venv）：
    ./.venv/Scripts/python.exe train.py

執行前請先看過 env.py 開頭的模組說明：這裡訓練用的是熱度分數的「替代獎勵」，
不是真正的按讚/略過回饋，因為目前真實互動紀錄只有 6 筆。
"""
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor

from env import ACTION_RECOMMEND, ACTION_SKIP, OssRadarRankingEnv, fit_normalizer, load_panel

TIMESTEPS = 50_000


def evaluate(env: OssRadarRankingEnv, policy=None) -> float:
    """在給定環境裡跑完整個 episode，回傳整段過程累積的獎勵總和。

    policy 可以是字串 "recommend"/"skip"（代表固定動作的傻瓜基準），
    也可以是一個真正訓練好的 PPO 模型（用 predict() 決定每一步的動作）。
    """
    obs, _ = env.reset()
    total = 0.0
    done = False
    while not done:
        if policy == "recommend":
            action = ACTION_RECOMMEND
        elif policy == "skip":
            action = ACTION_SKIP
        else:
            action, _ = policy.predict(obs, deterministic=True)
        obs, reward, done, _, _ = env.step(int(action))
        total += reward
    return total


def main() -> None:
    """載入資料、訓練 PPO 策略，再跟兩個傻瓜基準一起在 held-out 資料集上評估比較。"""
    train_df, eval_df = load_panel()
    print("=== proxy-reward exercise, not real user feedback (see env.py docstring) ===")
    print(f"train rows: {len(train_df)}, eval rows (held-out published_at): {len(eval_df)}")
    if len(train_df) < 50:
        print("WARNING: very little data — this is a mechanics exercise, not a real result.")

    mean, std = fit_normalizer(train_df)
    train_env = Monitor(OssRadarRankingEnv(train_df, mean, std))

    model = PPO("MlpPolicy", train_env, verbose=0, seed=0)
    model.learn(total_timesteps=TIMESTEPS)

    # 三種策略都在同一份「未來」資料（eval_df）上各自跑一輪，才能公平比較。
    skip_reward = evaluate(OssRadarRankingEnv(eval_df, mean, std), policy="skip")
    rec_reward = evaluate(OssRadarRankingEnv(eval_df, mean, std), policy="recommend")
    ppo_reward = evaluate(OssRadarRankingEnv(eval_df, mean, std), policy=model)

    print("\n=== held-out eval (sum of trend-proxy reward) ===")
    print(f"always-skip      : {skip_reward:8.2f}")
    print(f"always-recommend : {rec_reward:8.2f}")
    print(f"PPO policy       : {ppo_reward:8.2f}")

    model.save(Path(__file__).parent / "ppo_ossradar_toy.zip")


if __name__ == "__main__":
    main()
