# COST 実験の運用手順と検証記録

2026-09-26 時点。実資金の注文機能は存在しない。データと run の生記録は `data/private/`、実行ログは `logs/` に保存し、Git では公開しない。

## 段階 0 の凍結値

機械可読の正本は [`config/experiment.json`](../config/experiment.json)。COST/CIK `0000909832`、SEC submissions と Company Facts の２ API、当該 accession の SEC 原文添付、Costco IR の指定３ページ、yfinance COST/SPY を許可する。SEC 連絡先は `.env` の `SEC_USER_AGENT` に置き、Git から除外する。値と根拠を変更するときは新しい設定版を作り、過去判断には適用しない。

| 項目 | 凍結値 |
| --- | --- |
| データ判定 | SEC は判断日より前の `filed` のみ。決算 8-K の EX-99.1 を accession から限定取得。原文 URL とハッシュを保存 |
| 価格 | yfinance 1.2.0、１日足、`auto_adjust=False`、`repair=False`、OHLCV と配当・分割。前日 Close を判断に、当日 Open を仮想約定の代理価格に使用 |
| L0 | Close 前営業日比の絶対値 5%、当日出来高が過去20営業日中央値の２倍、新規 10-K/10-Q/8-K/訂正を検知 |
| PM | 08:00–09:00 ET に判断を終える。初回 L3 は必須。その後 L0/L1/L2/L3 を PM が選ぶ |
| Paper Risk | 初期 USD 100,000、現物ロング上限 20%、弱気時の全資産損失上限 2%、片道コスト 10 bp。弱気損失率が 0 以下で比率計算の分母が成立しない場合は計画書 §6 に従い新規買付を保留。新規売買はルールが拒否可能 |
| モデル | Flash が shadow alert・Fundamental・Red Team、Luna が調査深度と最終判断、Sol が査読。米東部日付ごとの本番呼出し試行上限はそれぞれ 8/4/2 回、開発 draft は別台帳で 20/10/5 回（503 や 429 の代替経路を含む）。Gemini API の 429 は `modelctl` の Antigravity `gemini-3.8-flash-low` へ１回切替える。入力文字数上限 32,000 |
| 査読 | 09:05 ET 以降に L2/L3 の判断束だけを Sol に渡す。`fill_and_pnl` は入力しない。結果を見る前の工程品質を採点 |
| 引け後 | 17:00–20:00 ET、同日の日足が取れた時点で仮想約定と P&L を一度だけ記録。欠損なら未処理として再試行。次回稼働時は飛ばした NYSE 営業日から順に補完し、後日取得値はその旨を記録 |
| 日次監査 | 20:00–21:00 ET、run・Sol 査読・仮想口座の証拠を突き合わせ、`cycle_audit.json` に実行基盤、LLM の指示／推論、工程品質を別々に記録 |

## コマンド

```sh
python3 -m pip install -e .
cp .env.example .env   # 実在の SEC 連絡先に置換。公開しない
python3 -m fund.cli research --date 2026-09-28 --draft
python3 -m fund.cli review 2026-09-28-draft
python3 -m fund.cli status
python3 -m fund.cli audit --date 2026-09-28
python3 scripts/install_scheduler.py
```

`research --draft` は先行研究であり、その日の仮想注文を凍結しない。SEC・価格の生資料は draft と本番を run ID ごとに保存する。NYSE 営業日は launchd が５分間隔で `tick` を呼び、時刻に応じて `research`、`review`、`close` を実行する。`tick.lock` で重複起動を防ぎ、成功済みまたは失敗確定した run は自動で呼び直さない。供給モデル 503 は同一経路で１回再試行し、Gemini API 429 は上記の代替経路へ切り替える。代替は agent mode なので repo 外の空ディレクトリで起動し、凍結済み入力テキストだけを渡す。これは OS レベルの完全な隔離ではないため、査読上は使用経路を記録する。スケジューラは当該 macOS ユーザーの `~/Library/LaunchAgents/com.tana-alt.llm-hedge-fund.plist` に入り、マシンが停止・スリープ中には動かない。予定時刻を逃した判断は次の `tick` で `late_not_frozen` とし、新規注文へ進めない。判断が失敗した日も価格が取れれば配当・分割・NAV を記録し、裁量売買だけ止める。NYSE 休場日は実行を飛ばす。

## 失敗の読み方

`python3 -m fund.cli status` の run と各 `data/private/runs/<ID>/result.json` の `stages` を見る。`system_data` は SEC/yfinance・抽出、`system_runtime` は modelctl/供給モデルの起動、`system_input` は固定入力上限、`system_budget` は日次モデル枠、`system_workflow` は判断未凍結や順序、`llm_instruction` は JSON/必須フィールド/権限制約、`llm_reasoning` は数値前提・引用・シナリオの矛盾を表す。Sol の指摘は `review.json` に残し、`gate=pass` でも確認済みの誤りを未修正のまま正しい事実として使わない。

## 実機で確認した経路

- SEC submissions、Company Facts、FY2026 9月24日 8-K の EX-99.1、COST/SPY の価格を取得。FY2026 速報の売上、CFO、CapEx、現金、負債などを抽出し、出典 URL・ハッシュ・期間を保存。
- 確定した段階０の設定版 `cost-v3-2026-09-26` で先行 L3 `2026-09-28-draft-v4` を実行。Flash の分析、算術 DCF、Red Team、Luna の調査依頼と WATCH 判断、Risk 上限、Sol の盲検査読まで通過。査読 `gate=pass`、評点 4/5、確認済み欠陥０件。予測 FCFF への事業上の橋渡しは未解決。詳細は [初回レポート](../reports/2026-09-28-draft.md)。
- 初回の Flash shadow alert は供給側 503 で失敗し、同一の凍結資料で再実行して成功。これは `system_runtime`。次の draft は shadow alert の引用が原文と一致せず `llm_reasoning`、その後 Gemini API の日次 quota 429 によって Red Team が `system_runtime` で失敗した。さらに試作呼出しが本番用の上限を消費して `system_budget` になったため、両台帳を分離した。別種の失敗として残し、確認済みの代替経路で再検証する。
- launchd サービスが登録され、週末の `tick` が実際に起動して `weekend` を記録。launchd 相当の最小環境変数から `modelctl` の Flash/Luna 呼出しも成功した。次の開場前実行と引け後の日足・P&L は、時刻到来後に確認する。
- `python3 -m unittest discover -s tests -v` の 12 件で FCFF/DCF・逆 DCF の境界、速報単位、仮想約定費用、企業行動、営業日補完、保存中断からの復旧、判断時刻、日次の失敗分類を検証。

Codex Scheduled task によるユーザー通知は、ローカルの研究実行とは別の接続作業として未設定。初回の外部査読は本書とレポートでユーザーに提示する。
