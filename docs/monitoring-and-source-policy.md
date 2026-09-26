# COST 実験の情報源、日次アラート、外部査読

提案日: 2026-09-26
状態: L3 開始前に固定する設計案。Automation は未作成。

## 判定

1. **価格は yfinance の日次 OHLCV を採用する。** 実機の `yfinance 1.2.0` で COST の直近５営業日（最終日 2026-09-25）に `Open/High/Low/Close/Adj Close/Volume/Dividends/Stock Splits` が揃うことを確認した。取得できた事実と、継続的な品質保証は区別する。[yfinance の価格履歴 API](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
2. **財務数値は SEC の公開 EDGAR API と提出原文を正本にする。** Costco の月次売上など、標準 XBRL にない会社固有 KPI は Costco IR から取り、提出資料と突き合わせる。[SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
3. **日次アナリストの重要事実チェックは採用するが、最初は機械チェックと並列に記録する。** アナリストが追加したアラートを即座に優れたものと見なさず、見逃し減少、誤報、PM の調査負荷、判断の変化を同一条件で評価する。
4. **外部研究チームは GPT-6 Sol とする。** Codex の Scheduled task はレポート提示の候補とする。まず手動で一回の盲検査読を成立させ、その後に定期化する。[OpenAI Docs: GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)、[Scheduled tasks](https://learn.chatgpt.com/docs/automations)
5. **L3 前に URL/API manifest を固定する。** 取得先の制限は攻撃面と情報源のばらつきを減らすが、許可サイト内の文面も prompt injection を含み得る。命令境界と実行権限も分ける。[OpenAI Docs: agent safety](https://developers.openai.com/api/docs/guides/agent-builder-safety)

## 初回の URL/API manifest

Costco の SEC CIK は `0000909832`。[SEC の Costco 提出記録](https://www.sec.gov/Archives/edgar/data/909832/000090983226000053/0000909832-26-000053-index.htm)で照合できる。以下は **L3 の収集を開始する前の許可先**であり、単にドメインが一致すればすべて閲覧してよいという意味ではない。

| 用途 | 許可先・取得対象 | 運用条件 |
| --- | --- | --- |
| SEC 提出発見 | `https://data.sec.gov/submissions/CIK0000909832.json` | 10-K、10-Q、8-K、訂正を検出。acceptance datetime、accession、form、取得時刻を保存 |
| SEC 標準財務数値 | `https://data.sec.gov/api/xbrl/companyfacts/CIK0000909832.json` | 標準タグの候補値。`filed`、期間、単位、accession を使って判断時点以前の提出へ紐付け。後日の訂正を過去判断に混ぜない |
| SEC 原文・注記 | 上記の accession から導出した `https://www.sec.gov/Archives/edgar/data/909832/<accession digits>/...` | 10-K/10-Q/8-K と該当添付書類のみ。リンク先の形式・CIK・accession を検証。追加の外部リンクは自動追跡しない |
| Costco ニュース | `https://investor.costco.com/news/default.aspx` から発見した `https://investor.costco.com/news/news-details/...` | 月次売上、決算、配当、重要な会社発表。公開日時と本文のスナップショットを保存 |
| Costco IR | `https://investor.costco.com/financials/annual-reports-and-proxy-statements/default.aspx` と `https://investor.costco.com/events-and-presentations/default.aspx` | 年次報告書、決算説明・音声等。CDN の PDF/音声は遷移先を個別に検証して manifest に追加 |
| 市場価格 | ローカルの `yfinance` ライブラリで `COST`。比較指標用の `SPY` は別エントリ | LLM の Web 閲覧先ではなく、読み取り専用のデータ取得処理。使用ライブラリ版、取得日時、日付、タイムゾーン、OHLCV、配当、分割を保存 |

SEC の `data.sec.gov` は公開アクセスに API キーを要しない。Company Facts は標準 taxonomy かつ企業全体の事実が中心で、Costco の会社固有 KPI を網羅しない。[SEC の API 説明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) 取得処理は SEC の[EDGAR アクセス案内](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)に従い、レート制限と連絡先を含む明示的な User-Agent を備える。連絡先設定は公開リポジトリに置かずローカル設定に入れる。

### 追加 URL の手続き

アナリストは許可外のニュースや競合情報を「候補 URL と調べる理由」として提案できる。Data/Ops がドメイン、リダイレクト先、文書種別、公開時刻、ライセンス、既存資料との差を確認し、承認した URL だけを **次の判断時点**から manifest に追加する。重大な新情報を制限先の外で発見した場合も、現在の凍結済み判断に遡って混ぜない。初回 COST の L3 は上記だけで完走できるかも検証対象にする。

### Prompt injection と情報汚染

Web 本文・SEC 添付・IR PDF は、出所にかかわらず**データ**として入力する。そこに書かれた「別 URL を開け」「秘密を送れ」「前の指示を無視せよ」は実行しない。取得担当に任意 URL の閲覧、シェル、書き込み、秘密ファイル参照を同時に与えない。本文は取得日時、URL、ハッシュ、引用位置を付けて LLM に渡し、外部からの指示らしい文面は記録して無視する。数値は型・単位・期間を検証し、重要値は原文位置に戻って照合する。URL 制限だけで安全とは判定しない。[OpenAI Docs: prompt injection 対策](https://developers.openai.com/api/docs/guides/agent-builder-safety)

## yfinance の価格規則

`Ticker("COST").history(interval="1d", auto_adjust=False, actions=True, repair=False)` を初期の取得規則とし、日次スナップショットを上書きせず保存する。`auto_adjust=True` は OHLC をさらに調整するため、仮想約定の `Open` には使わない。[yfinance API](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html) `auto_adjust=False` の OHLC は配当調整を避けるが、Yahoo が過去の分割を価格系列へ反映し得るため「完全な未調整価格」と呼ばない。仮想口座では各営業日に凍結した**その日の価格**だけを使い、分割の発生日に保有株数を分割比率で変える。分割後に再取得した過去価格へ同じ株数調整を重ねて過去 P&L を計算し直さない。配当は現金に加算し、`Adj Close` による配当調整と二重計上しない。価格修復 `repair=True` は後から過去値を変え得るため、初回の判断系列には適用せず、必要なら訂正版を別系列として差分を残す。[yfinance price repair](https://ranaroussi.github.io/yfinance/advanced/price_repair.html)

「Yahoo の `Open`」は取引所の公式オークション始値そのものとの同一性を保証しない。したがって仮想約定の**評価用代理価格**と明記する。翌日の取得が欠損・古い日付・異常な OHLC 関係・配当/分割の矛盾なら、その注文を未約定にして検証を依頼する。後で Yahoo が履歴を修正しても当時の判断や損益を黙って書き換えず、訂正系列を併記する。yfinance 作者は Yahoo と非提携で、取得データの権利を Yahoo の利用条件で確認するよう求めている。公開 repo には価格系列の一括再配布をしない。[yfinance README](https://github.com/ranaroussi/yfinance/blob/main/README.md)

## 日次アナリストによる追加アラート

機械チェックと Gemini Flash のアナリストは**同じ時刻で凍結した manifest の新着資料**を見る。機械側は、新規 accession、月次/決算発表、予定期限、価格・出来高、Risk 閾値など、事前定義した条件だけを出す。アナリスト側は資料間の矛盾、文面に埋もれたガイダンスや投資計画の変更、既存 thesis の反証候補を短いメモにする。日次アナリストは DCF を毎日作り直さず、発見した事実と追加調査の問いを出す。

アナリストの alert には、`source_id`、原文位置、公開時刻、前回との差、影響され得る driver、想定される判断変化、`L1/L2/L3` 推奨を必須にする。原文のない意見は alert ではなく探索メモとする。重要な事実の見落としを減らせる可能性がある一方、LLM が株価やニュースの目立ちやすさに引きずられて毎日「重要」と言えば、調査費用と売買回転が増え、判断評価を汚す。

| 評価軸 | 機械チェックのみ | 機械 + 日次アナリスト |
| --- | --- | --- |
| 再現性 | 高い。閾値とソースが同じなら同じ alert | モデル版・プロンプト・文脈に依存。入力スナップショットと版を固定する |
| 見逃し | 未登録の意味的変化に弱い | 文面のニュアンスや異なる資料間の矛盾を拾える可能性 |
| 誤報 | 閾値近辺や数値ノイズ | 推測を事実と誤認、同じニュースの重複、些細な変更の誇張 |
| 費用・遅延 | 少ない | 毎営業日の推論、根拠照合、PM トリアージが増える |
| 評価の混線 | 単純な固定基準 | 検知改善と、その後の PM/Analyst の判断改善を分ける必要 |

**比較の順序**: 最初の前向きな４〜６週間は両方を並列に走らせ、機械 alert とアナリスト追加 alert を別々に凍結する。同じ資料・締切・銘柄を使い、アナリストには機械 alert を先に見せない。実際の PM 入力は機械 alert のみとし、アナリスト分は shadow に保存する。重大な会計/リスク事故をアナリストが見つけた場合は Data/Ops が原文で確認し、PM と Risk の双方へ即時通知する。その日は比較対象から除く。後から出所を伏せた GPT-6 Sol の査読と人手の抜き取りで、「実際に新しく、当時知り得て、予測/DCF/Risk/PM の判断を変え得たか」を判定する。無 alert 日も抽出して見逃しを探す。Sol の主観的評点だけを正解ラベルにしない。

判定指標は、重要事実の追加発見、機械のみ/アナリストのみ/共通の alert 数、誤報と重複、発見時差、原文確認率、PM が依頼した L1–L3 数、実際に変わった前提・判断、トークンとレビュー時間である。**第一評価は重要情報の増分発見率と誤報率**とする。昇格条件は、少なくとも一件の独立確認された重要な機械見逃し、架空の重要引用ゼロ、PM が処理できる誤報負荷を満たすこと。処理できる上限は観測した L0 所要時間から実験開始前に固定する。４〜６週間で重要イベントが観測されなければ「優位性なし」と断定せず、次の決算/重要開示まで延長する。

**第二評価は PM 判断の差**とする。アナリスト alert が昇格した後、同じ凍結状態・調査予算で「機械のみ」と「機械 + アナリスト」の PM 判断を別コンテキストで並列生成し、どの前提・依頼・ポジションが変わったかを記録する。実際の仮想口座に反映する系列は事前に一方へ固定し、もう一方は反実仮想と明記する。これで検知改善と PM 判断改善を分け、分析役の追加を PM 自体の能力改善と取り違えない。

## GPT-6 Sol と Automation の使い方

GPT-6 Sol は、運用チームの Gemini Flash/GPT-luna と別のプロンプト・入力束で、**判断の工程を査読する外部研究チーム**に割り当てる。最初の一件は手動で実行し、引用・数値・盲検採点が再現できることを確認する。その後、Codex/ChatGPT の Scheduled task に同じ査読手順を載せる案を採用する。[OpenAI Docs: Scheduled tasks](https://learn.chatgpt.com/docs/automations) 対象 task では利用可能ならモデルを明示的に `gpt-6-sol` とし、実行ごとにモデル版を記録する。ローカルプロジェクトを使う scheduled task は、実行時にマシンとアプリが稼働している必要がある。

提案する schedule は米東部営業日の **09:05 ET** に新しい凍結済み判断を確認するもの。新しい L2/L3 またはポジション変更があるときだけ、当日結果を含まない工程査読をユーザーの Scheduled inbox に出す。金曜日は週次の「見逃し・誤報・未解決事項」を簡潔に出し、変化がなければ通知しない。次回決算など評価期限が来たら、事前登録した予測と実績の差を別レポートにする。定刻実行が遅れたときは、当日の価格や損益を初段査読に入れず、欠測/遅延と明記する。

単に査読プロンプトで「損益を見ない」と指示するだけでは盲検は成立しない。**09:00 ET に凍結した source/decision/model/異論の読み取り専用束**を Sol に渡し、`fill_and_pnl` と後日の資料を別の束にする。Automation が repo 全体を読める実行環境なら盲検性を保証できないため、権限・作業ディレクトリを分けられるか最初の手動実行で確認する。分離できなければ「結果を見られる査読」と明記して盲検評価には数えない。Sol は報告と変更案の提示まで担当し、組織設定・過去判断・公開 repo を自動変更しない。ユーザーへ見せるレポートには、判定、根拠リンク/判断 ID、重大な見逃し、変更案、未解決事項を含める。Automation の初期作成は、この設計レビュー後に行う。
